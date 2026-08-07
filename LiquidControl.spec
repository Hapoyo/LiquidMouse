# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

try:
    import miniupnpc as _mupnpc
    _miniupnpc_imports = ['miniupnpc']
except ImportError:
    _miniupnpc_imports = []

# pywinpty: bundle dynamic libs (conpty.dll, winpty.dll) e data files (LICENSE etc.)
_winpty_bins = collect_dynamic_libs('winpty')
_winpty_data = collect_data_files('winpty')
_winpty_mods = collect_submodules('winpty')


a = Analysis(
    ['server.pyw'],
    pathex=[],
    binaries=_winpty_bins,
    # Ogni file elencato qui va elencato anche in STATIC_ROUTES
    # (liquidmouse/net/static.py) e in check_files() di build.py.
    datas=[
        ('index.html', '.'), ('app.css', '.'), ('app.js', '.'),
        ('icon.ico', '.'), ('xterm.js', '.'), ('xterm.css', '.'),
    ] + _winpty_data,
    hiddenimports=[
        # server.pyw importa la GUI dentro un try/except per poter mostrare un
        # messaggio se mancano pystray/PIL/qrcode. Dichiararla qui evita di
        # dipendere da come PyInstaller analizza gli import condizionali: senza,
        # la build resterebbe verde e l'EXE non partirebbe.
        'liquidmouse.gui',
        'liquidmouse.gui.window',
        'liquidmouse.gui.effects',
        'winpty',
        'winpty.ptyprocess',
        'websockets',
        'websockets.server',
        'websockets.client',
        'websockets.connection',
        'websockets.exceptions',
        'websockets.frames',
        'websockets.http11',
        'websockets.legacy',
        'websockets.legacy.server',
        'websockets.legacy.client',
        'websockets.legacy.protocol',
        'cryptography',
        'cryptography.hazmat.backends',
        'cryptography.hazmat.backends.openssl',
        'cryptography.hazmat.backends.openssl.backend',
        'cryptography.x509',
        'cryptography.x509.oid',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.serialization',
        'cryptography.hazmat.primitives.asymmetric',
        'cryptography.hazmat.primitives.asymmetric.rsa',
    ] + _winpty_mods + _miniupnpc_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LiquidControl',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
