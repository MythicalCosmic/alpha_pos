# PyInstaller spec for the Alpha POS desktop control panel.
#   .venv/Scripts/pyinstaller AlphaPOS.spec
# Produces dist/AlphaPOS/AlphaPOS.exe (one-folder; faster start, easier to
# bundle with Inno Setup than one-file).
#
# Django + the apps are pure Python, but their templates/migrations/static and
# several runtime-imported modules must be collected explicitly.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

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
        'notifications', 'licensing', 'fiscalization', 'cashbox', 'alpha_pos']

hiddenimports = []
for app in APPS:
    hiddenimports += collect_submodules(app)
# Django + libs imported by string/lazily (middleware paths, etc.). These need
# their SUBMODULES collected, not just the top package, or import_string() fails
# at runtime (e.g. whitenoise.middleware, corsheaders.middleware).
hiddenimports += collect_submodules('django')
for lib in ('waitress', 'whitenoise', 'corsheaders', 'cryptography',
            'dateutil', 'requests', 'anthropic'):
    hiddenimports += collect_submodules(lib)
# Gemini SDK is lazy-imported in base/services/llm.py — collect it explicitly.
hiddenimports += collect_submodules('google.genai')
# Self-update stack: tufup + its deps (tuf, securesystemslib, bsdiff4, pynacl).
# updater.py lazy-imports tufup.client, so collect them explicitly or the frozen
# build ships without the update engine. Guarded so a build made in a venv that
# lacks tufup (e.g. the py3.14 dev venv) still succeeds — self-update just stays
# disabled in that build. bsdiff4/pynacl are C extensions, so pull their DLLs.
update_binaries = []
for _ulib in ('tufup', 'tuf', 'securesystemslib', 'bsdiff4', 'nacl'):
    try:
        hiddenimports += collect_submodules(_ulib)
    except Exception:
        print(f'AlphaPOS.spec: {_ulib} not available — self-update engine omitted from this build.')
for _ulib in ('bsdiff4', 'nacl'):
    try:
        update_binaries += collect_dynamic_libs(_ulib)
    except Exception:
        pass
# Native GUI: pywebview + pythonnet/CLR (WebView2). The hook-webview/hook-clr/
# hook-clr_loader hooks pull the .NET runtime + WebView2 DLLs; we add the
# submodules + 'clr' so the lazy `import webview` is never missed.
hiddenimports += collect_submodules('webview') + collect_submodules('clr_loader')
hiddenimports += ['clr', 'pythonnet']

datas = [
    ('desktop/ui', 'desktop/ui'),
    ('desktop/tos.txt', 'desktop'),
]
# Ship the trusted TUF root so the self-updater (desktop/updater.py) can
# bootstrap trust offline. Guarded: a build made before
# `python tools/release.py --init` (no update_repo/ yet) still succeeds —
# self-update simply stays disabled until the root is published.
_tuf_root = os.path.join(SPECPATH, 'update_repo', 'metadata', 'root.json')
if os.path.exists(_tuf_root):
    datas += [(_tuf_root, 'tuf_root')]
else:
    print('AlphaPOS.spec: update_repo/metadata/root.json not found — self-update '
          'disabled in this build. Run tools/release.py --init to enable it.')
datas += collect_data_files('webview')  # WebView2 assemblies in webview/lib
# Ship each app's migrations + templates + static.
for app in APPS:
    datas += collect_data_files(app, include_py_files=True)

block_cipher = None

a = Analysis(
    [os.path.join(SPECPATH, 'desktop', 'app.py')],
    pathex=[SPECPATH],
    binaries=update_binaries,
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
