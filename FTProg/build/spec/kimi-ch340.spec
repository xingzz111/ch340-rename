# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/Users/XING/Documents/A193/DFU/tools/FTProg/src/kimi_ch340/cli.py'],
    pathex=['/Users/XING/Documents/A193/DFU/tools/FTProg/src'],
    binaries=[('/Users/XING/Documents/A193/DFU/tools/FTProg/vendor/libusb/macos/libusb-1.0.0.dylib', '.')],
    datas=[],
    hiddenimports=[],
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
    name='kimi-ch340',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
