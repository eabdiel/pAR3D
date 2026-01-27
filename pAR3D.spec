# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ["pAR3D.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets/pAR3D_icon.png", "assets"),
        ("assets/pAR3D.ico", "assets"),
    ],
    hiddenimports=[
        # Minimal, practical hidden imports
        "cv2",
        "numpy",
        "PIL",
        "pystray",

        "torch",
        "transformers",
        "huggingface_hub",
        "safetensors",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # dev/bloat (safe to exclude)
        "matplotlib", "notebook", "jupyter", "IPython", "pytest",
        "pandas", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="pAR3D",
    debug=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon="assets/pAR3D.ico",
)
