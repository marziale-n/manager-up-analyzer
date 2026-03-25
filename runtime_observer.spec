# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 1. DEFINIZIONE DEGLI IMPORT NASCOSTI
hidden_imports = [
    'comtypes',
    'comtypes.stream',
    'comtypes.gen',
    'pywinauto',
    'pynput.keyboard._win32',
    'pynput.mouse._win32',
    'pytesseract',
    'PIL._tkinter_finder',
]
hidden_imports.extend(collect_submodules('comtypes'))

# 2. DEFINIZIONE DEI FILE AGGIUNTIVI (ASSETS)
added_files = [
    ('tesseract_bin', 'tesseract_bin'),
]

# 3. ANALISI DEL PROGETTO
a = Analysis(
    ['gui_app.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# 4. CREAZIONE DELL'ESEGUIBILE
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='RuntimeObserver', 
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
    icon=None,                   # Se in futuro vorrai aggiungere un'icona, scrivi es: 'assets/icona.ico'
)