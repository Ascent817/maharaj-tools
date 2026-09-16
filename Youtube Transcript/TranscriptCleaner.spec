# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['Remove Timestamps.pyw'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['youtube_transcript_api', 'yt_dlp'],
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
    name='Transcript Cleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
