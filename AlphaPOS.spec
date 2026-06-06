# PyInstaller spec for the Alpha POS desktop control panel.
#   .venv/Scripts/pyinstaller AlphaPOS.spec
# Produces dist/AlphaPOS/AlphaPOS.exe (one-folder; faster start, easier to
# bundle with Inno Setup than one-file).
#
# Django + the apps are pure Python, but their templates/migrations/static and
# several runtime-imported modules must be collected explicitly.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# The spec dir (project root) must be importable so `import alpha_pos.settings`
# works at build time, regardless of the CWD pyinstaller is invoked from.
# SPECPATH is injected by PyInstaller when it execs this spec.
sys.path.insert(0, SPECPATH)

# Configure + load Django at BUILD time so collect_submodules can import each
# app package (their __init__ chains touch settings/models). Without this,
# PyInstaller silently skips most app submodules and the exe ModuleNotFounds at
# runtime. Dummy secrets — build-time only.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alpha_pos.settings')
os.environ.setdefault('SECRET_KEY', 'build-time-secret')
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('LICENSE_FERNET_KEY', '')
import django  # noqa: E402
django.setup()

APPS = ['base', 'admins', 'customers', 'waiters', 'stock', 'hr', 'discounts',
        'notifications', 'licensing', 'fiscalization', 'alpha_pos']

hiddenimports = []
for app in APPS:
    hiddenimports += collect_submodules(app)
# Django + libs imported by string/lazily (middleware paths, etc.). These need
# their SUBMODULES collected, not just the top package, or import_string() fails
# at runtime (e.g. whitenoise.middleware, corsheaders.middleware).
hiddenimports += collect_submodules('django')
for lib in ('waitress', 'whitenoise', 'corsheaders', 'cryptography',
            'dateutil', 'requests'):
    hiddenimports += collect_submodules(lib)

datas = [
    ('desktop/ui', 'desktop/ui'),
    ('desktop/tos.txt', 'desktop'),
]
# Ship each app's migrations + templates + static.
for app in APPS:
    datas += collect_data_files(app, include_py_files=True)

block_cipher = None

a = Analysis(
    [os.path.join(SPECPATH, 'desktop', 'app.py')],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # tkinter: unused GUI toolkit. PIL/Pillow: only used at BUILD time to make
    # the icon (make_icon.py) — nothing in the app imports it at runtime (no
    # ImageField / qrcode), so it's dead weight (~11 MB) in the shipped bundle.
    excludes=['tkinter', 'PIL', 'PIL._imaging', 'PIL.Image'],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='AlphaPOS',
    console=False, icon='desktop/AlphaPOS.ico',
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name='AlphaPOS')
