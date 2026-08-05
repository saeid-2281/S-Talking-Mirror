from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
root = Path.cwd()
icon = root / "app" / "resources" / "brand" / "official" / "S-Logo.ico"
version_file = root / "packaging" / "windows" / "version_info.txt"
datas = [
    (str(root / "app" / "resources"), "app/resources"),
    (str(root / "docs" / "USER_GUIDE.md"), "docs"),
    (str(root / "docs" / "INSTALLATION.md"), "docs"),
    (str(root / "docs" / "DISTRIBUTION_READINESS_PHASE52.md"), "docs"),
    (str(root / "docs" / "TROUBLESHOOTING.md"), "docs"),
    (str(root / "docs" / "RELEASE_CHECKLIST.md"), "docs"),
    (str(root / "docs" / "SECURITY_SUPPLY_CHAIN_HARDENING_PHASE58.md"), "docs"),
    (str(root / "docs" / "STABLE_RELEASE_PROMOTION_PHASE61.md"), "docs"),
    (str(root / "docs" / "MULTI_SOURCE_PROJECTS.md"), "docs"),
    (str(root / "docs" / "PROVIDERS.md"), "docs"),
    (str(root / "docs" / "PROVIDER_CAPABILITIES.md"), "docs"),
]
datas += collect_data_files("PySide6", includes=["Qt/plugins/platforms/*", "Qt/plugins/styles/*", "Qt/plugins/imageformats/*", "Qt/plugins/multimedia/*", "Qt/plugins/audio/*"])

a = Analysis(
    [str(root / "app" / "frozen_main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("PySide6.QtMultimedia") + collect_submodules("PySide6.QtNetwork"),
    hookspath=["packaging/hooks"],
    excludes=["tests", "pytest", "ruff", "pip", "setuptools", "wheel"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="S-Talking",
    icon=str(icon) if icon.exists() else None,
    console=False,
    version=str(version_file) if version_file.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="S-Talking")
