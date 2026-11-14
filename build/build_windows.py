"""Build de Windows: portable (.zip) + instalador (Inno Setup).

Corre en GitHub Actions al subir un tag (.github/workflows/release.yml).
La línea la define el Python con el que se corre este script:

  PySide6, x64           -> win-x64     Windows 10/11
  PySide2 (Python 3.8)   -> win7-x64    Windows 7, 8, 10 y 11, 64 bits
                         -> win7-x86    Windows 7, 8, 10 y 11, 32 bits
                            (PySide6 no existe en 32 bits)

Salida en dist/release/:
  NetworkTool-<ver>-<win|win7>-<x64|x86>-portable.zip
  NetworkTool-<ver>-<win|win7>-<x64|x86>-setup.exe

El portable es la carpeta de Nuitka en un .zip, no un --onefile: Windows Defender
marca a veces el onefile como "potencialmente no deseado" (falso positivo), tarda
más en abrir y en Windows 7 las DLL de la Universal CRT tienen que estar al lado
del .exe desde el arranque.

Uso:  python build/build_windows.py [--no-installer] [--dry-run]
"""
import argparse
import os
import shutil
import struct
import sys
import zipfile
from pathlib import Path

from _common import (APP_ARTIFACT, APP_NAME, COMPANY, ROOT, VERSION, artifact, clean, list_release,
                     numeric_version, nuitka_base, qt_backend, run, standalone_dir, BUILD)

ISCC_CANDIDATES = (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe")


def arch() -> str:
    return "x64" if struct.calcsize("P") * 8 == 64 else "x86"


def windows_flags() -> list:
    flags = [
        "--windows-console-mode=disable",
        "--windows-icon-from-ico={}".format(ROOT / "assets" / "icon.ico"),
        "--company-name=" + COMPANY,
        "--product-name=" + APP_NAME,
        "--file-version=" + numeric_version(),
        "--product-version=" + numeric_version(),
        "--file-description=" + APP_NAME,
        "--copyright=(c) {} - GPL-3.0".format(COMPANY),
    ]
    if arch() == "x86":
        flags.append("--msvc=latest")    # el MinGW que baja Nuitka es solo de 64 bits
    return flags


def ucrt_dir() -> Path:
    """DLLs de la Universal C Runtime del Windows SDK (vienen en los runners de
    GitHub). Python 3.8 depende de ellas y un Windows 7 sin la actualización
    KB2999226 no las tiene ("falta api-ms-win-crt-runtime-l1-1-0.dll").
    Microsoft permite distribuirlas junto al .exe."""
    kits = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "Redist"
    found = sorted(kits.glob("*/ucrt/DLLs/" + arch())) + [kits / "ucrt" / "DLLs" / arch()]
    for d in reversed(found):
        if (d / "ucrtbase.dll").exists():
            return d
    sys.exit("No se encontró la Universal CRT ({}) del Windows SDK en {}: sin ella "
             "la versión win7 no arranca en Windows 7".format(arch(), kits))


def add_ucrt(folder: Path) -> None:
    src = ucrt_dir()
    print("Universal CRT: {}".format(src))
    for dll in src.glob("*.dll"):
        shutil.copy2(str(dll), str(folder / dll.name))
    for name in ("ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll"):
        if not (folder / name).exists():
            sys.exit("Falta {} en {}: no arrancaría en Windows 7".format(name, folder))


def zip_folder(folder: Path, target: Path, root_name: str) -> None:
    """La carpeta adentro del .zip lleva nombre y versión: al descomprimir no se mezcla."""
    with zipfile.ZipFile(str(target), "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                z.write(str(f), str(Path(root_name) / f.relative_to(folder)))


def find_iscc() -> str:
    """Compilador de Inno Setup (viene instalado en los runners de Windows de GitHub)."""
    for candidate in (shutil.which("ISCC.exe"),) + ISCC_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-installer", action="store_true", help="Solo el portable.")
    parser.add_argument("--dry-run", action="store_true", help="Muestra los comandos sin ejecutarlos.")
    args = parser.parse_args()

    qt = qt_backend()
    legacy = qt == "PySide2"
    system = "win7" if legacy else "win"
    if not legacy and arch() == "x86":
        parser.error("PySide6 no existe para Windows de 32 bits: la x86 se arma con "
                     "Python 3.8 + PySide2 (línea win7, corre en Windows 7 a 11).")
    print("{} {} · {} · Python {} {} -> {}-{}".format(APP_NAME, VERSION, qt, sys.version.split()[0],
                                                      arch(), system, arch()))
    clean(args.dry_run)
    run(nuitka_base(BUILD, windows_flags(), qt), args.dry_run)

    folder = standalone_dir()
    portable = artifact(system, arch(), "portable", "zip")
    setup = artifact(system, arch(), "setup", "exe")
    if not args.dry_run:
        if legacy:
            add_ucrt(folder)
        zip_folder(folder, portable, "{}-{}".format(APP_ARTIFACT, VERSION))
    print("Portable:   {}".format(portable.name))

    if not args.no_installer:
        iscc = find_iscc()
        if not iscc and not args.dry_run:
            sys.exit("No se encontró Inno Setup 6 (ISCC.exe)")
        run([iscc or "ISCC.exe", "/Q", "/DAppVersion=" + VERSION, "/DArch=" + arch(),
             "/DMinWin=" + ("6.1sp1" if legacy else "10.0"),
             "/DSourceDir={}".format(folder), "/DOutputDir={}".format(setup.parent),
             "/DOutputName=" + setup.stem, str(ROOT / "build" / "installer.iss")], args.dry_run)
        print("Instalador: {}".format(setup.name))
    list_release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
