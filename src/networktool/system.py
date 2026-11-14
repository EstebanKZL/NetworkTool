"""Ejecución de comandos del sistema, permisos y lanzadores de terminal."""

import ctypes
import os
import shutil
import subprocess
import sys
import webbrowser

from networktool.common import IS_MACOS, IS_WINDOWS, IS_WIN_7, logger
from networktool.qt_compat import QMessageBox

# -----------------------------
# FUNCIONES BASE DE RED (MEJORADAS)
# -----------------------------
def _console_encoding() -> str:
    """netsh / ipconfig / arp / ping escriben en la página de códigos OEM (cp850 en
    Windows en español). Decodificar con cp1252 convertía 'Sí' en 'S¡' y el estado
    DHCP salía como 'Desconocido'."""
    if IS_WINDOWS:
        try:
            return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        except Exception:
            return "cp850"
    return "utf-8"

_CONSOLE_ENCODING = _console_encoding()

class IPConfigError(Exception):
    pass

def _hidden_startupinfo():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si

def _run_command(cmd, timeout=3):
    try:
        kwargs = {
            "capture_output": True, "text": True, "timeout": timeout,
            "shell": isinstance(cmd, str),
            "encoding": _CONSOLE_ENCODING, "errors": "replace",
        }
        if IS_WINDOWS:
            kwargs["startupinfo"] = _hidden_startupinfo()
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(cmd, **kwargs)
        return proc.stdout or "", proc.stderr or "", proc.returncode
    except subprocess.TimeoutExpired:
        return "", "Timeout", -1
    except Exception as e:
        return "", str(e), -1

def run_command(cmd, timeout=3):
    stdout, _, _ = _run_command(cmd, timeout)
    return stdout

def _run_powershell(script, timeout=15):
    """Ejecuta un script de PowerShell y retorna (stdout, stderr, returncode).
    El .ps1 se escribe con BOM UTF-8 (PowerShell 5.1 lee como ANSI los archivos sin BOM
    y rompía nombres de adaptador con tildes) y la salida se fuerza a UTF-8."""
    if not IS_WINDOWS:
        return "", "Not Windows", -1
    import tempfile
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False, encoding='utf-8-sig') as f:
            f.write("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
                    "$ProgressPreference = 'SilentlyContinue'\n")
            f.write(script)
            temp_file = f.name
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', temp_file],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
            startupinfo=_hidden_startupinfo(), creationflags=subprocess.CREATE_NO_WINDOW
        )
        return (result.stdout or "").strip(), (result.stderr or "").strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Timeout", -1
    except Exception as e:
        return "", str(e), -1
    finally:
        if temp_file:
            try: os.unlink(temp_file)
            except Exception: pass

def _ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"

def _win_has_netcmdlets() -> bool:
    """Get-NetAdapter / New-NetIPAddress existen desde Windows 8 (6.2)."""
    if not IS_WINDOWS:
        return False
    try:
        return tuple(sys.getwindowsversion()[:2]) >= (6, 2)
    except Exception:
        return not IS_WIN_7

def is_admin():
    if IS_WINDOWS:
        try: return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception: return False
    return os.geteuid() == 0

def relaunch_as_admin() -> bool:
    """Reinicia NetworkTool elevado (UAC). Devuelve True si se lanzó la nueva instancia."""
    if not IS_WINDOWS:
        return False
    try:
        if getattr(sys, "frozen", False):
            params = sys.argv[1:]
        else:
            params = [os.path.abspath(sys.argv[0])] + sys.argv[1:]
        params = [p for p in params if p != "--elevated"] + ["--elevated"]
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, subprocess.list2cmdline(params), os.getcwd(), 1)
        return rc > 32
    except Exception as e:
        logger.error(f"No se pudo reiniciar como administrador: {e}")
        return False

def open_in_terminal(command):
    try:
        if IS_WINDOWS:
            subprocess.Popen(["cmd.exe", "/k", command], creationflags=subprocess.CREATE_NEW_CONSOLE)
        elif IS_MACOS:
            subprocess.Popen(["osascript", "-e", f'tell app "Terminal" to do script "{command}"'])
        else:
            terminals = ["gnome-terminal", "konsole", "xfce4-terminal", "lxterminal", "tilix", "alacritty", "kitty", "xterm"]
            for t in terminals:
                if shutil.which(t):
                    if t == "gnome-terminal":
                        subprocess.Popen([t, "--", "bash", "-c", f"{command}; exec bash"])
                    elif t in ["alacritty", "kitty"]:
                        subprocess.Popen([t, "-e", "bash", "-c", f"{command}; exec bash"])
                    else:
                        subprocess.Popen([t, "-e", "bash", "-c", f"{command}; exec bash"])
                    break
    except Exception:
        pass

def open_ssh(ip, port=22): open_in_terminal(f"ssh -p {port} {ip}")
def open_telnet(ip, port=23): open_in_terminal(f"telnet {ip} {port}")
def open_ping(ip): open_in_terminal(f"ping {ip} -t" if IS_WINDOWS else f"ping {ip}")
def open_traceroute(ip): open_in_terminal(f"tracert {ip}" if IS_WINDOWS else f"traceroute {ip}")
def open_nmap_quick(ip): open_in_terminal(f"nmap -F {ip}")
def open_netstat(ip): open_in_terminal(f'netstat -an | find "{ip}"' if IS_WINDOWS else f"netstat -an | grep {ip}")
def open_arp(ip): open_in_terminal(f"arp -a {ip}" if IS_WINDOWS else f"arp -n {ip}")

def open_in_vlc(stream_url):
    vlc_path = None
    if IS_WINDOWS:
        cands = [shutil.which("vlc"), r"C:\Program Files\VideoLAN\VLC\vlc.exe", r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"]
        for p in cands:
            if p and os.path.exists(p): vlc_path = p; break
    else: vlc_path = shutil.which("vlc")
    if vlc_path:
        try:
            subprocess.Popen([vlc_path, stream_url])
            return True
        except Exception: pass
    webbrowser.open(stream_url)
    return False

def _launch_rdp(ip, port=3389, username="") -> bool:
    if IS_WINDOWS:
        subprocess.Popen(["mstsc", f"/v:{ip}:{port}"])
        return True
    if shutil.which("xfreerdp"):
        subprocess.Popen(["xfreerdp", f"/v:{ip}:{port}"] + ([f"/u:{username}"] if username else []))
        return True
    if shutil.which("remmina"):
        subprocess.Popen(["remmina", "-c", f"rdp://{(username + '@') if username else ''}{ip}:{port}"])
        return True
    return False


_VNC_VIEWERS = ["vncviewer", "tvnviewer", "realvnc-vncviewer", "remmina"]
_VNC_WINDOWS_PATHS = [r"C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe",
                      r"C:\Program Files\TightVNC\tvnviewer.exe",
                      r"C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe"]


def _launch_vnc(ip, port=5900) -> bool:
    cands = [shutil.which(v) for v in _VNC_VIEWERS] + (_VNC_WINDOWS_PATHS if IS_WINDOWS else [])
    for exe in cands:
        if exe and os.path.exists(exe):
            target = f"vnc://{ip}:{port}" if os.path.basename(exe).startswith("remmina") else f"{ip}::{port}"
            subprocess.Popen([exe, target])
            return True
    webbrowser.open(f"vnc://{ip}:{port}")
    return True


def launch_external(session) -> tuple:
    """Abre una sesión RDP / VNC / Web con el cliente del sistema. Devuelve (ok, detalle)."""
    from networktool.i18n import tr
    proto, host, port = session["protocol"], session["host"], int(session["port"])
    try:
        if proto == "rdp":
            if _launch_rdp(host, port, session.get("username", "")):
                return True, ""
            return False, tr("msg.rdp_missing", target=f"{host}:{port}")
        if proto == "vnc":
            return _launch_vnc(host, port), ""
        if proto in ("http", "https"):
            default = 80 if proto == "http" else 443
            webbrowser.open(f"{proto}://{host}" + ("" if port == default else f":{port}"))
            return True, ""
    except Exception as e:
        return False, tr("msg.launch_failed", detail=e)
    return False, tr("msg.launch_failed", detail=proto)


def open_protocol(ip, port, parent=None):
    """Botón «Abrir» de un puerto: elige el cliente adecuado según el servicio."""
    from networktool.i18n import tr
    try:
        if port in [80, 8080, 8000, 8888, 9090]: webbrowser.open(f"http://{ip}:{port}")
        elif port in [443, 8443]: webbrowser.open(f"https://{ip}:{port}")
        elif port == 554: open_in_vlc(f"rtsp://{ip}:{port}")
        elif port == 22: open_ssh(ip, port)
        elif port == 23: open_telnet(ip, port)
        elif port == 3389:
            if not _launch_rdp(ip, port):
                QMessageBox.information(parent, "RDP", tr("msg.rdp_missing", target=f"{ip}:{port}"))
        elif port == 21: webbrowser.open(f"ftp://{ip}:{port}")
        elif port == 445:
            if IS_WINDOWS:
                subprocess.Popen(["explorer", f"\\\\{ip}"])
            else:
                webbrowser.open(f"smb://{ip}")
        elif port in [5900, 5901]: _launch_vnc(ip, port)
        elif port == 3306: QMessageBox.information(parent, "MySQL", f"mysql -h {ip} -P {port} -u root -p")
        elif port == 5432: QMessageBox.information(parent, "PostgreSQL", f"psql -h {ip} -p {port} -U postgres")
        elif port == 123:
            if IS_WINDOWS:
                open_in_terminal(f"w32tm /stripchart /computer:{ip} /samples:5 /dataonly")
            else:
                open_in_terminal(_make_ntp_linux_cmd(ip))
        else: QMessageBox.information(parent, tr("msg.info_title"), tr("msg.port_open", port=port, ip=ip))
    except Exception as e: QMessageBox.warning(parent, tr("msg.error_title"), tr("msg.launch_failed", detail=e))

def _make_ntp_linux_cmd(ip: str) -> str:
    import base64
    script = (
        "import socket,struct,time\n"
        f"ip='{ip}'\n"
        "try:\n"
        "    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\n"
        "    s.settimeout(5)\n"
        "    s.sendto(b'\\x1b'+47*b'\\x00',(ip,123))\n"
        "    d=s.recvfrom(1024)[0]\n"
        "    t=struct.unpack('!12I',d)[10]-2208988800\n"
        "    print('Servidor NTP : '+ip)\n"
        "    print('Hora UTC     : '+time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(t)))\n"
        "    print('Hora Local   : '+time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(t)))\n"
        "    print('Estado       : OK - el servidor NTP respondio correctamente')\n"
        "except Exception as e:\n"
        "    print('Error consultando NTP '+ip+': '+str(e))\n"
    )
    b64 = base64.b64encode(script.encode()).decode()
    py_fallback = (
        f"python3 -c \"import base64; exec(base64.b64decode('{b64}').decode())\""
    )
    return (
        f"(command -v ntpdate >/dev/null 2>&1 && ntpdate -q {ip} 2>&1) || "
        f"(command -v sntp    >/dev/null 2>&1 && sntp -t 2 {ip}   2>&1) || "
        f"(command -v ntpq    >/dev/null 2>&1 && ntpq -p {ip}     2>&1) || "
        f"{py_fallback}"
    )
