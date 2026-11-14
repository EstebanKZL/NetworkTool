"""Partes compartidas de los scripts de build (Nuitka).

Tiene que correr con Python 3.8 (línea de Windows 7/8) y con Python 3.11+ (Linux, Windows 10/11).
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = DIST / "nuitka"
RELEASE = DIST / "release"                 # lo que se sube al release y nada más
APP_NAME = "NetworkTool"                   # nombre visible
APP_ARTIFACT = "NetworkTool"               # nombre de los archivos publicados
COMPANY = "EstebanKZL"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def artifact(system: str, arch: str, kind: str, ext: str) -> Path:
    """<AppName>-<versión>-<os>-<arq>-<variante>.<ext>; sin variante en Linux."""
    parts = [APP_ARTIFACT, VERSION, system, arch] + ([kind] if kind else [])
    return RELEASE / ("-".join(parts) + "." + ext)


def qt_backend() -> str:
    """PySide6 (Windows 10/11, Linux x86_64) o PySide2 (Windows 7/8)."""
    for name in ("PySide6", "PySide2"):
        if importlib.util.find_spec(name):
            return name
    sys.exit("No hay PySide6 ni PySide2 instalado en este Python")


def numeric_version() -> str:
    """Windows pide cuatro números en los datos del .exe: 7.4.0 -> 7.4.0.0."""
    return ".".join((VERSION.split(".") + ["0", "0", "0"])[:4])


def nuitka_base(output_dir: Path, extra: list, qt: str) -> list:
    """Comando de Nuitka común a Windows y Linux (--standalone: una carpeta con Python,
    Qt y todo lo demás adentro). VERSION y los íconos viajan como datos; QtSvg se pide
    explícito porque qt_compat lo importa con importlib y Nuitka no lo vería solo."""
    other = "PySide2" if qt == "PySide6" else "PySide6"
    return [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--enable-plugin=" + qt.lower(),
        "--include-module={}.QtSvg".format(qt),
        "--include-package=networktool",
        "--include-data-files={}=VERSION".format(ROOT / "VERSION"),
        "--include-data-files={}=assets/icon.png".format(ROOT / "assets" / "icon.png"),
        "--include-data-files={}=assets/icon.ico".format(ROOT / "assets" / "icon.ico"),
        "--nofollow-import-to=" + other,
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=unittest",
        "--output-dir={}".format(output_dir),
        "--output-filename=" + APP_ARTIFACT + (".exe" if os.name == "nt" else ""),
        "--assume-yes-for-downloads",
    ] + list(extra) + [str(ROOT / "src" / "main.py")]


def standalone_dir() -> Path:
    return BUILD / "main.dist"


def run(cmd: list, dry_run: bool, env: dict = None) -> None:
    print("$ " + subprocess.list2cmdline([str(c) for c in cmd]), flush=True)
    if not dry_run:
        full_env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        full_env.update(env or {})
        subprocess.run([str(c) for c in cmd], check=True, cwd=str(ROOT), env=full_env)


def clean(dry_run: bool) -> None:
    """Build limpio: no se cuela nada de una compilación anterior."""
    print("Limpiando {}".format(DIST))
    if not dry_run:
        shutil.rmtree(str(DIST), ignore_errors=True)
        RELEASE.mkdir(parents=True)


def list_release() -> None:
    if RELEASE.exists():
        for f in sorted(RELEASE.iterdir()):
            print("  {}  ({:.1f} MB)".format(f.name, f.stat().st_size / 1e6))
