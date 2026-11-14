"""Build de Linux: AppImage x86_64.

  x86_64  Ubuntu 22.04 + PySide6 (glibc 2.35: corre en distros de 2022 en adelante)

La carpeta autocontenida de Nuitka trae Python, Qt y las librerías; se arma el
AppDir y se empaqueta con appimagetool.

Uso:
  python build/build_linux.py --appimagetool ./appimagetool             # compilar + AppImage
  python build/build_linux.py --standalone-only                         # solo compilar
"""
import argparse
import os
import platform
import shutil
import stat
import sys
from pathlib import Path

from _common import (APP_ARTIFACT, APP_NAME, BUILD, ROOT, VERSION, artifact, clean, list_release,
                     nuitka_base, qt_backend, run, standalone_dir, RELEASE)

DESKTOP = """[Desktop Entry]
Type=Application
Name={name}
Exec={exe}
Icon={exe}
Categories=Network;Utility;
Terminal=false
""".format(name=APP_NAME, exe=APP_ARTIFACT)

APPRUN = """#!/bin/sh
# Punto de entrada del AppImage: ejecuta el binario de Nuitka empaquetado.
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/{exe}/{exe}" "$@"
""".format(exe=APP_ARTIFACT)


def machine_arch() -> str:
    return "x86_64" if platform.machine().lower() in ("x86_64", "amd64") else "i686"


def write_unix(path: Path, text: str) -> None:
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:   # Python 3.8: sin write_text(newline=)
        fh.write(text)


def package(folder: Path, target_arch: str, appimagetool: str, dry_run: bool) -> Path:
    """appimagetool corre en x86_64 y toma el runtime de la arquitectura destino
    (ARCH): así el AppImage de 32 bits se arma en el mismo runner de 64."""
    appdir = BUILD / "AppDir"
    target = artifact("linux", target_arch, "", "AppImage")
    print("Armando {}".format(appdir))
    if not dry_run:
        shutil.rmtree(str(appdir), ignore_errors=True)
        (appdir / "usr" / "bin").mkdir(parents=True)
        shutil.copytree(str(folder), str(appdir / "usr" / "bin" / APP_ARTIFACT))
        shutil.copy2(str(ROOT / "assets" / "icon.png"), str(appdir / (APP_ARTIFACT + ".png")))
        (appdir / ".DirIcon").symlink_to(APP_ARTIFACT + ".png")
        write_unix(appdir / (APP_ARTIFACT + ".desktop"), DESKTOP)
        apprun = appdir / "AppRun"
        write_unix(apprun, APPRUN)
        apprun.chmod(apprun.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        RELEASE.mkdir(parents=True, exist_ok=True)
    run([appimagetool, "--no-appstream", str(appdir), str(target)], dry_run,
        env={"ARCH": target_arch, "APPIMAGE_EXTRACT_AND_RUN": "1"})
    print("AppImage: {}".format(target.name))
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--standalone-only", action="store_true", help="Solo compilar (sin AppImage).")
    parser.add_argument("--package", metavar="CARPETA", help="Empaquetar una carpeta ya compilada.")
    parser.add_argument("--arch", choices=["x86_64", "i686"], default=None)
    parser.add_argument("--appimagetool", default=os.environ.get("APPIMAGETOOL", "appimagetool"),
                        help="Ruta de appimagetool (por defecto, el del PATH o $APPIMAGETOOL).")
    parser.add_argument("--dry-run", action="store_true", help="Muestra los comandos sin ejecutarlos.")
    args = parser.parse_args()
    target_arch = args.arch or machine_arch()

    if args.package:                     # no compila: este Python no necesita Qt
        package(Path(args.package).resolve(), target_arch, args.appimagetool, args.dry_run)
    else:
        qt = qt_backend()
        print("{} {} · {} · Python {} {}".format(APP_NAME, VERSION, qt, sys.version.split()[0], machine_arch()))
        clean(args.dry_run)
        run(nuitka_base(BUILD, ["--linux-icon={}".format(ROOT / "assets" / "icon.png")], qt), args.dry_run)
        if not args.standalone_only:
            package(standalone_dir(), target_arch, args.appimagetool, args.dry_run)
    list_release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
