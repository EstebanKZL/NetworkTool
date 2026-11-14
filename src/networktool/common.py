"""Constantes, logging, rutas de datos y utilidades compartidas."""

import ctypes
import ipaddress
import json
import logging
import os
import platform
import re
import socket
import struct
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# -----------------------------
# FUNCIONES PARA ICONOS Y BARRA DE TAREAS
# -----------------------------
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/ o la carpeta del ejecutable


def resource_path(relative_path):
    """Archivo de datos (assets/icon.ico, VERSION…): junto al ejecutable compilado o, desde el
    código, en la raíz del repositorio (un nivel arriba de src/)."""
    candidates = [getattr(sys, "_MEIPASS", None), _PKG_PARENT, os.path.dirname(_PKG_PARENT),
                  os.path.dirname(os.path.abspath(sys.argv[0] or "."))]
    for base in candidates:
        if base and os.path.exists(os.path.join(base, relative_path)):
            return os.path.join(base, relative_path)
    return os.path.join(_PKG_PARENT, relative_path)


def _read_version() -> str:
    """Única fuente de la versión: el archivo VERSION de la raíz del proyecto."""
    try:
        with open(resource_path("VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


APP_ICON_ICO = "assets/icon.ico"
APP_ICON_PNG = "assets/icon.png"

def _force_window_icon(hwnd: int, icon_path=None) -> None:
    """Fuerza el icono en barra de tareas usando HWND de Qt (int(win.winId())).
    FIX v5.2.2: ya no usa FindWindowW — usa winId() pasado desde main().
    """
    if os.name != 'nt' or not hwnd:
        return
    try:
        is_64bit = platform.machine().endswith('64')
        get_class_long = ctypes.windll.user32.GetClassLongPtrW if is_64bit else ctypes.windll.user32.GetClassLongW
        set_class_long = ctypes.windll.user32.SetClassLongPtrW if is_64bit else ctypes.windll.user32.SetClassLongW

        GCL_HICON    = -14
        GCLP_HICONSM = -34

        hicon = None
        if icon_path and os.path.exists(icon_path) and icon_path.lower().endswith('.ico'):
            hicon = ctypes.windll.user32.LoadImageW(0, icon_path, 1, 0, 0, 0x00000010)
        if not hicon:
            hicon = get_class_long(hwnd, GCL_HICON)
        if not hicon:
            hicon = ctypes.windll.user32.LoadIconW(0, 32512)

        if hicon:
            ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, hicon)
            ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, hicon)
            set_class_long(hwnd, GCL_HICON,    hicon)
            set_class_long(hwnd, GCLP_HICONSM, hicon)
    except Exception as e:
        print(f"[NetworkTool] No se pudo forzar el icono: {e}")

def setup_windows_taskbar_icon():
    if os.name == 'nt':
        try:
            myappid = f'estebankzl.networktool.v{APP_VERSION.replace(".", "")}'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception as e:
            print(f"[NetworkTool] Error al establecer AppUserModelID: {e}")

# -----------------------------
# CONFIGURACIÓN DE LOGGING
# -----------------------------
def setup_logging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    import io
    safe_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace') if hasattr(sys.stdout, 'buffer') else sys.stdout
    handlers = [logging.StreamHandler(safe_stdout)]
    if debug:
        try:
            handlers.append(logging.FileHandler("network_tool_debug.log", encoding="utf-8"))
        except Exception:
            pass
    try:
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(str(nettool_data_dir() / "networktool.log"), maxBytes=1_000_000,
                                 backupCount=3, encoding="utf-8")
        fh.setLevel(logging.INFO)
        handlers.append(fh)
    except Exception:
        pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers
    )

logger = logging.getLogger(__name__)

# -----------------------------
# VARIABLES GLOBALES Y CONFIG
# -----------------------------
APP_VERSION        = _read_version()
APP_NAME           = "NetworkTool"
APP_DEVELOPER      = "EstebanKZL"
APP_EMAIL          = "89585806+EstebanKZL@users.noreply.github.com"   # no-reply de GitHub (público)
APP_ORG            = "EstebanKZL"       # organización para QSettings (tema, idioma)
APP_REPO_URL       = "https://github.com/EstebanKZL/NetworkTool"

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
IS_MACOS = platform.system() == "Darwin"
IS_WIN_7 = IS_WINDOWS and platform.release() == "7"

UNKNOWN = "Unknown"
NA = "N/A"
STATUS_ONLINE = "Online"
STATUS_OFFLINE = "Offline"

SOCKET_CONNECT_TIMEOUT = 15
SOCKET_READ_TIMEOUT = 30
FTP_TIMEOUT = 15
VENDOR_CACHE_TTL = 3600

_CHILD_PROCESSES = []
_CHILD_PROCESSES_LOCK = threading.Lock()

_ADAPTERS_CACHE = []
_ADAPTERS_CACHE_TIME = 0
_ADAPTERS_CACHE_TTL = 5
_ADAPTER_INFO_MAP = {}

PORT_CATEGORIES = {
    "web": [80, 443, 8080, 8443, 8000, 8888, 9090],
    "streaming": [554, 1935, 8554],
    "remote": [22, 23, 3389, 5900, 5901, 5800],
    "file": [21, 445, 139, 2049],
    "database": [3306, 5432, 1433, 1521, 27017],
    "mail": [25, 110, 143, 465, 587, 993, 995],
    "camera": [80, 443, 554, 8000, 8080, 8999, 37777],
    "other": [161, 162, 123, 514, 636, 873, 3260, 8001]
}
ALL_PORTS = sorted(list(set(sum(PORT_CATEGORIES.values(), []))))

SERVICE_NAMES = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
    80: "HTTP", 110: "POP3", 123: "NTP", 139: "NetBIOS",
    143: "IMAP", 161: "SNMP", 162: "SNMP-Trap", 443: "HTTPS",
    445: "SMB", 465: "SMTPS", 514: "Syslog", 554: "RTSP",
    587: "SMTP-TLS", 636: "LDAPS", 873: "Rsync", 993: "IMAPS",
    995: "POP3S", 1433: "MSSQL", 1521: "Oracle", 2049: "NFS",
    3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 5800: "VNC-HTTP",
    5900: "VNC", 5901: "VNC-1", 8000: "HTTP-Alt", 8080: "HTTP-Alt",
    8443: "HTTPS-Alt", 8554: "RTSP-Alt", 8888: "HTTP-Alt",
    9090: "HTTP-Alt", 1935: "RTMP", 27017: "MongoDB",
    37777: "Dahua", 8999: "Camera-Alt", 8001: "HTTP-Alt"
}

# -----------------------------
# HTTP MÍNIMO (biblioteca estándar, sin dependencias externas)
# -----------------------------
class HttpResponse:
    def __init__(self, status_code: int, body: bytes, headers):
        self.status_code = status_code
        self.content = body
        self.headers = headers

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("Content-Type", "") if self.headers else ""
        m = re.search(r"charset=([\w-]+)", ctype)
        if m:
            charset = m.group(1)
        return self.content.decode(charset, errors="replace")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")


class _HttpSession:
    """Lo poco que la app usaba de requests: get/post con timeout, sin verificar
    certificados en equipos de la red local (cámaras y routers con certificados propios)."""

    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    def request(self, method: str, url: str, timeout: float = 5, data=None, headers=None,
                verify: bool = True, max_bytes: int = 64 * 1024 * 1024) -> HttpResponse:
        import ssl
        import urllib.error
        import urllib.request
        hdrs = {"User-Agent": self.user_agent}
        hdrs.update(headers or {})
        body = data.encode("utf-8") if isinstance(data, str) else data
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        ctx = None
        if url.lower().startswith("https"):
            ctx = ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return HttpResponse(resp.status, resp.read(max_bytes), resp.headers)
        except urllib.error.HTTPError as e:
            return HttpResponse(e.code, e.read(65536) if e.fp else b"", e.headers)

    def get(self, url: str, timeout: float = 5, verify: bool = True, **kw) -> HttpResponse:
        return self.request("GET", url, timeout=timeout, verify=verify, **kw)

    def post(self, url: str, data=None, headers=None, timeout: float = 5, verify: bool = True) -> HttpResponse:
        return self.request("POST", url, timeout=timeout, data=data, headers=headers, verify=verify)


_http_session = _HttpSession(f"NetworkTool/{APP_VERSION}")
_vendor_cache: Dict[str, Tuple[str, float]] = {}
_vendor_cache_lock = threading.Lock()
_hostname_cache = {}; _hostname_cache_lock = threading.Lock()


def nettool_data_dir() -> Path:
    """Carpeta de datos de NetworkTool (perfiles, historial, base de fabricantes)."""
    if os.name == "nt":
        folder = Path(os.environ.get("APPDATA", Path.home())) / "NetworkTool"
    else:
        folder = Path.home() / ".config" / "networktool"
    folder.mkdir(parents=True, exist_ok=True)
    return folder

def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"No se pudo leer {path}: {e}")
    return default

def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

# -----------------------------
# INVENTARIO PERSISTENTE (SQLite)
# -----------------------------
def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
_IPV4_RE = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"

def _cidr_to_mask(cidr: int) -> str:
    """Convierte prefijo CIDR a máscara dotted-decimal."""
    try:
        mask_int = (0xFFFFFFFF << (32 - cidr)) & 0xFFFFFFFF
        return socket.inet_ntoa(struct.pack('>I', mask_int))
    except Exception:
        return "Sin Máscara"

def _normalize_mask(mask) -> str:
    """Acepta '255.255.255.0', '24' o '/24'. Lanza ValueError si no es una máscara válida."""
    m = str(mask or "").strip().lstrip("/")
    if m.isdigit():
        prefix = int(m)
        if not 1 <= prefix <= 32:
            raise ValueError(f"Prefijo de red inválido: /{prefix}")
        return _cidr_to_mask(prefix)
    try:
        return str(ipaddress.IPv4Network(f"0.0.0.0/{m}").netmask)
    except Exception:
        raise ValueError(f"Máscara inválida: {mask}")

def mask_to_cidr(mask):
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{_normalize_mask(mask)}").prefixlen
    except Exception:
        return 24

def _normalize_mac(raw) -> Optional[str]:
    parts = re.split(r"[:-]", str(raw or "").strip())
    if len(parts) != 6:
        return None
    try:
        octets = [int(p, 16) for p in parts]
    except ValueError:
        return None
    if all(o == 0 for o in octets) or all(o == 0xFF for o in octets) or octets[:3] == [0x01, 0x00, 0x5E]:
        return None
    return ":".join(f"{o:02X}" for o in octets)

def _html_escape(value) -> str:
    return (str(value if value is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def _cleanup_child_processes():
    with _CHILD_PROCESSES_LOCK:
        for proc in _CHILD_PROCESSES:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        _CHILD_PROCESSES.clear()
