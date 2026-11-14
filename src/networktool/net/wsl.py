"""Detección de distribuciones WSL y de terminales locales (PowerShell, CMD, Git Bash...).

WSL: primero el registro (HKCU\\...\\Lxss, rápido y sin abrir procesos); si no hay datos, la
salida de `wsl.exe -l -q` (viene en UTF-16). Si WSL no está instalado, devuelve una lista vacía.
"""

import os
import shutil
import subprocess
from typing import Dict, List

from networktool.common import IS_WINDOWS, logger

_LXSS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Lxss"


def _decode_wsl_output(raw: bytes) -> str:
    """wsl.exe escribe en UTF-16 LE (a veces con BOM); versiones viejas, en la página OEM."""
    if raw.startswith(b"\xff\xfe") or (len(raw) > 1 and raw[1:2] == b"\x00"):
        return raw.decode("utf-16-le", errors="ignore").lstrip("\ufeff")
    return raw.decode("utf-8", errors="ignore")


def parse_wsl_list(text: str) -> List[str]:
    """Nombres de `wsl.exe -l -q`. Si WSL no está instalado, el texto es un aviso: se ignora."""
    names = []
    for line in text.replace("\x00", "").splitlines():
        name = line.strip().lstrip("*").strip()
        if not name or " " in name or len(name) > 64:      # los avisos traen espacios
            continue
        names.append(name)
    return names


def _from_registry() -> List[Dict]:
    import winreg
    out = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _LXSS_KEY)
    except OSError:
        return out
    with root:
        try:
            default_guid = winreg.QueryValueEx(root, "DefaultDistribution")[0]
        except OSError:
            default_guid = ""
        i = 0
        while True:
            try:
                guid = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, guid) as k:
                    name = winreg.QueryValueEx(k, "DistributionName")[0]
                    try:
                        version = int(winreg.QueryValueEx(k, "Version")[0])
                    except OSError:
                        version = 0
                out.append({"name": name, "default": guid == default_guid, "version": version})
            except OSError:
                continue
    return out


def list_distros() -> List[Dict]:
    """[{name, default, version}] de las distribuciones WSL instaladas (vacía si no hay WSL)."""
    if not IS_WINDOWS:
        return []
    try:
        distros = _from_registry()
    except Exception as e:
        logger.debug(f"WSL registro: {e}")
        distros = []
    if distros or not shutil.which("wsl.exe"):
        return sorted(distros, key=lambda d: (not d["default"], d["name"].lower()))
    try:
        raw = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, timeout=8,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        names = parse_wsl_list(_decode_wsl_output(raw))
        return [{"name": n, "default": i == 0, "version": 0} for i, n in enumerate(names)]
    except Exception as e:
        logger.debug(f"wsl.exe -l: {e}")
        return []


def wsl_command(distro: str) -> List[str]:
    """Comando que abre la distro en su carpeta de inicio."""
    return ["wsl.exe", "-d", distro, "--cd", "~"] if distro else ["wsl.exe", "--cd", "~"]


def wsl_unc_root(distro: str) -> str:
    """Carpeta de Windows con el sistema de archivos de la distro (para el explorador lateral)."""
    for prefix in (r"\\wsl.localhost", r"\\wsl$"):
        path = f"{prefix}\\{distro}"
        try:
            if os.path.isdir(path):
                return path
        except OSError:
            pass
    return rf"\\wsl.localhost\{distro}"


def local_shells() -> List[Dict]:
    """Terminales locales disponibles: [{key, name, command}]."""
    if not IS_WINDOWS:
        return []
    shells = [{"key": "powershell", "name": "Windows PowerShell", "command": ["powershell.exe", "-NoLogo"]},
              {"key": "cmd", "name": "CMD", "command": ["cmd.exe"]}]
    pwsh = shutil.which("pwsh.exe")
    if pwsh:
        shells.insert(0, {"key": "pwsh", "name": "PowerShell 7", "command": [pwsh, "-NoLogo"]})
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        bash = os.path.join(base, "Git", "bin", "bash.exe")
        if os.path.exists(bash):
            shells.append({"key": "gitbash", "name": "Git Bash", "command": [bash, "--login", "-i"]})
            break
    return shells


def has_pty() -> bool:
    """¿Se puede abrir una terminal local dentro de la app? (pywinpty en Windows)."""
    if not IS_WINDOWS:
        return False
    try:
        __import__("winpty")  # solo comprueba que esté instalado
        return True
    except Exception:
        return False
