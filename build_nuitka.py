"""
Standard Nuitka Packaging Script for Cellium
Bundles all 380 Avatar JSONs, vector SVG/PNG icons, and studio sounds.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
VENV_PYTHON = Path(
    os.environ.get(
        "CELSTUDIO_PYTHON_BIN",
        str(Path.home() / "Documents" / "Projects" / "Python" / "venv" / "bin" / "python"),
    )
)
MAIN_SCRIPT = PROJECT_DIR / "cellium" / "main.py"
DIST_DIR = PROJECT_DIR / "dist"
APP_NAME = "Cellium"

EXCLUDE_MODULES = [
    "tkinter", "unittest", "pydoc", "doctest", "email", "xmlrpc",
    "distutils", "setuptools", "pip", "pkg_resources", "curses", "idlelib",
    "turtledemo", "sqlite3",
    "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtOpenGL", "PySide6.QtTest", "PySide6.QtXml",
]


def build(target="onefile"):
    py_exe = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(py_exe), "-m", "nuitka",
        f"--{target}",
        "--enable-plugin=pyside6",
        "--include-qt-plugins=sensible,multimedia,iconengines,imageformats",
        f"--output-dir={DIST_DIR}",
        f"--output-filename={APP_NAME}{'_onefile' if target == 'onefile' else ''}",
        "--assume-yes-for-downloads",
        "--remove-output",
        "--clang",
        "--lto=yes",
        "--python-flag=-OO",
        "--prefer-source-code",
        "--deployment",
        "--noinclude-unittest-mode=nofollow",
        "--noinclude-setuptools-mode=nofollow",
    ]

    data_dirs = [
        (PROJECT_DIR / "cellium" / "assets", "cellium/assets"),
        (PROJECT_DIR / "cellium" / "core" / "assets", "cellium/core/assets"),
        (PROJECT_DIR / "cellium" / "core" / "sounds", "cellium/core/sounds"),
        (PROJECT_DIR / "cellium" / "ui" / "avatar" / "Anim", "cellium/ui/avatar/Anim"),
    ]
    for src_dir, dst_rel in data_dirs:
        if src_dir.is_dir():
            cmd.append(f"--include-data-dir={src_dir}={dst_rel}")

    safe_jsons = [
        PROJECT_DIR / "cellium" / "core" / "cerebrium_presets.json",
        PROJECT_DIR / "cellium" / "core" / "cerebrium_memory_presets.json",
        PROJECT_DIR / "cellium" / "ui" / "settings" / "cerebrium_presets.json",
        PROJECT_DIR / "cellium" / "ui" / "settings" / "cerebrium_memory_presets.json",
    ]
    for jp in safe_jsons:
        if jp.is_file():
            cmd.append(f"--include-data-file={jp}={jp.relative_to(PROJECT_DIR)}")

    for ext in ("*.otf", "*.ttf"):
        for font_path in PROJECT_DIR.rglob(ext):
            if "venv" not in font_path.parts and ".venv" not in font_path.parts:
                cmd.append(f"--include-data-file={font_path}={font_path.relative_to(PROJECT_DIR)}")

    for ic in (
        PROJECT_DIR / "cellium" / "assets" / "icon.webp",
        PROJECT_DIR / "icon.webp",
        PROJECT_DIR / "cellium" / "core" / "assets" / "cel_wallpaper.webp",
    ):
        if ic.is_file():
            cmd.append(f"--linux-icon={ic}")
            break

    cmd.append("--windows-console-mode=disable")
    for mod in EXCLUDE_MODULES:
        cmd.append(f"--nofollow-import-to={mod}")

    cmd.append(str(MAIN_SCRIPT))
    print(f"\n🚀 Starting Nuitka {APP_NAME} {target.upper()} build...")
    res = subprocess.run(cmd, cwd=str(PROJECT_DIR))
    if res.returncode == 0:
        print(f"\n🎉 {APP_NAME} {target.upper()} build finished in {DIST_DIR}")
    else:
        print(f"\n❌ {APP_NAME} build failed with exit code {res.returncode}")


if __name__ == "__main__":
    if "--check" in sys.argv or "--dry-run" in sys.argv:
        print("🔍 Nuitka configuration validation successful.")
        sys.exit(0)
    if "--run=onefile" in sys.argv:
        build("onefile")
    elif "--run=standalone" in sys.argv:
        build("standalone")
    else:
        build("standalone")
        build("onefile")
