# PyInstaller ONE-FILE spec for Alpha POS.
#   .venv/Scripts/pyinstaller AlphaPOS-onefile.spec
# Produces a SINGLE dist/AlphaPOS.exe with everything (Python, Django, app,
# DLLs, data) packed inside. Copy that one file to any Windows 10/11 PC and
# double-click — no install, no _internal folder. It self-extracts to a temp
# dir at launch (a few seconds) and keeps real data under %LOCALAPPDATA%\AlphaPOS.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

sys.path.insert(0, SPECPATH)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'alpha_pos.settings')
os.environ.setdefault('SECRET_KEY', 'build-time-secret')
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('LICENSE_FERNET_KEY', '')
import django  # noqa: E402
django.setup()

APPS = ['base', 'admins', 'customers', 'waiters', 'stock', 'hr', 'discounts',
        'notifications', 'licensing', 'fiscalization', 'cashbox', 'alpha_pos']

hiddenimports = []
for app in APPS:
    hiddenimports += collect_submodules(app)
hiddenimports += collect_submodules('django')
for lib in ('waitress', 'whitenoise', 'corsheaders', 'cryptography',
            'dateutil', 'requests', 'anthropic'):
    hiddenimports += collect_submodules(lib)
# Gemini SDK is lazy-imported in base/services/llm.py — collect it explicitly.
hiddenimports += collect_submodules('google.genai')
hiddenimports += collect_submodules('webview') + collect_submodules('clr_loader')
hiddenimports += ['clr', 'pythonnet']

datas = [
    ('desktop/ui', 'desktop/ui'),
    ('desktop/tos.txt', 'desktop'),
]
datas += collect_data_files('webview')
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
    excludes=['tkinter', 'PIL', 'PIL._imaging', 'PIL.Image'],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ONE-FILE: pass binaries + datas straight into EXE (no COLLECT) so the result
# is a single self-contained .exe.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AlphaPOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon='desktop/AlphaPOS.ico',
)
