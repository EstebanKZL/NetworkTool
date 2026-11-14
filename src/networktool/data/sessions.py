"""Sesiones guardadas (SSH, SFTP, Telnet, FTP, RDP, VNC, Web, WSL, terminal local) en sessions.json.

Las contraseñas NO se guardan: se piden al conectar. Para SSH/SFTP se puede indicar
un archivo de clave privada.
"""

import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from networktool.common import _read_json, _write_json, logger, nettool_data_dir

# protocolo → (puerto por defecto, se abre dentro de la app)
PROTOCOLS: Dict[str, Dict] = {
    "ssh":    {"port": 22,   "embedded": True},
    "sftp":   {"port": 22,   "embedded": True},
    "telnet": {"port": 23,   "embedded": True},
    "ftp":    {"port": 21,   "embedded": True},
    "rdp":    {"port": 3389, "embedded": False},
    "vnc":    {"port": 5900, "embedded": False},
    "http":   {"port": 80,   "embedded": False},
    "https":  {"port": 443,  "embedded": False},
    "wsl":    {"port": 0,    "embedded": True},     # distribución de WSL (Windows)
    "shell":  {"port": 0,    "embedded": True},     # terminal local: PowerShell, CMD, Git Bash
}
LOCAL_PROTOCOLS = ("wsl", "shell")
PROTOCOL_LABELS = {"ssh": "SSH", "sftp": "SFTP", "telnet": "Telnet", "ftp": "FTP",
                   "rdp": "RDP", "vnc": "VNC", "http": "HTTP", "https": "HTTPS",
                   "wsl": "WSL", "shell": "Shell"}

# Puerto abierto → protocolo sugerido al crear una sesión desde el escáner
PORT_TO_PROTOCOL = {22: "ssh", 23: "telnet", 21: "ftp", 3389: "rdp", 5900: "vnc", 5901: "vnc",
                    80: "http", 8080: "http", 8000: "http", 443: "https", 8443: "https"}


def clean_session(s: Dict) -> Dict:
    proto = str(s.get("protocol", "ssh")).lower()
    if proto not in PROTOCOLS:
        proto = "ssh"
    try:
        port = int(s.get("port") or PROTOCOLS[proto]["port"])
    except (TypeError, ValueError):
        port = PROTOCOLS[proto]["port"]
    host = str(s.get("host", "")).strip()
    return {
        "id": str(s.get("id") or uuid.uuid4().hex),
        "name": str(s.get("name", "")).strip() or host,
        "folder": str(s.get("folder", "") or "").strip(),
        "protocol": proto,
        "host": host,
        "port": 0 if proto in LOCAL_PROTOCOLS else max(1, min(65535, port)),
        "username": str(s.get("username", "") or "").strip(),
        "key_file": str(s.get("key_file", "") or "").strip(),
        "remote_path": str(s.get("remote_path", "") or "").strip(),
        "ftp_passive": bool(s.get("ftp_passive", True)),
        "encoding": str(s.get("encoding", "") or "utf-8").strip() or "utf-8",
        "notes": str(s.get("notes", "") or ""),
        "credential_id": str(s.get("credential_id", "") or ""),
        "distro": str(s.get("distro", "") or "").strip(),      # WSL
        "shell": str(s.get("shell", "") or "").strip(),        # terminal local: powershell, cmd, pwsh, gitbash
    }


def local_session(kind: str, value: str, name: str) -> Dict:
    """Sesión WSL (kind="wsl", value=distro) o terminal local (kind="shell", value=clave del shell)."""
    key = "distro" if kind == "wsl" else "shell"
    return clean_session({"protocol": kind, key: value, "name": name, "id": f"auto-{kind}-{value or 'default'}"})


_SCHEMES = {"ssh": "ssh", "sftp": "sftp", "scp": "sftp", "telnet": "telnet", "ftp": "ftp", "rdp": "rdp",
            "vnc": "vnc", "http": "http", "https": "https"}


def parse_quick_connect(text: str) -> Optional[Dict]:
    """Conexión rápida: "equipo", "usuario@equipo", "usuario@equipo:2222", "sftp://usuario@equipo",
    "telnet equipo 2323", "rdp 10.0.0.5". Sin protocolo = SSH. Devuelve una sesión o None."""
    text = (text or "").strip()
    if not text:
        return None
    words = text.split()
    if words[0].lower() == "wsl" and len(words) <= 2:            # "wsl" o "wsl Ubuntu"
        distro = words[1] if len(words) == 2 else ""
        return local_session("wsl", distro, f"WSL {distro}".strip())
    if words[0].lower() in ("powershell", "pwsh", "cmd", "gitbash") and len(words) == 1:
        return local_session("shell", words[0].lower(), words[0])
    proto = "ssh"
    if "://" in text:
        scheme, _, text = text.partition("://")
        proto = _SCHEMES.get(scheme.lower().strip())
        if proto is None:
            return None
        text = text.rstrip("/")
    else:
        parts = text.split()
        if len(parts) > 1 and parts[0].lower() in _SCHEMES:
            proto = _SCHEMES[parts[0].lower()]
            parts = parts[1:]
        if len(parts) == 2 and parts[1].isdigit():
            text = f"{parts[0]}:{parts[1]}"
        elif len(parts) == 1:
            text = parts[0]
        else:
            return None
    user, _, hostport = text.rpartition("@")
    host, port = hostport, PROTOCOLS[proto]["port"]
    if hostport.count(":") == 1:
        host, _, p = hostport.partition(":")
        if not p.isdigit() or not 0 < int(p) < 65536:
            return None
        port = int(p)
    host = host.strip("[] ")
    if not host or " " in host:
        return None
    return clean_session({"protocol": proto, "host": host, "port": port, "username": user,
                          "name": f"{(user + '@') if user else ''}{host}"})


class SessionStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or (nettool_data_dir() / "sessions.json")
        data = _read_json(self.path, {})
        items = data.get("sessions") if isinstance(data, dict) else None
        self.sessions: List[Dict] = [clean_session(s) for s in (items or []) if isinstance(s, dict)]

    def save(self) -> None:
        try:
            _write_json(self.path, {"networktool_sessions": 1, "sessions": self.sessions})
        except Exception as e:
            logger.error(f"No se pudieron guardar las sesiones: {e}")

    def get(self, sid: str) -> Optional[Dict]:
        return next((s for s in self.sessions if s["id"] == sid), None)

    def upsert(self, session: Dict) -> Dict:
        session = clean_session(session)
        for i, s in enumerate(self.sessions):
            if s["id"] == session["id"]:
                self.sessions[i] = session
                break
        else:
            self.sessions.append(session)
        self.save()
        return session

    def delete(self, sid: str) -> None:
        self.sessions = [s for s in self.sessions if s["id"] != sid]
        self.save()

    def duplicate(self, sid: str, suffix: str) -> Optional[Dict]:
        s = self.get(sid)
        if not s:
            return None
        copy = dict(s, id=uuid.uuid4().hex, name=f"{s['name']} {suffix}")
        return self.upsert(copy)

    def folders(self) -> List[str]:
        return sorted({s["folder"] for s in self.sessions if s["folder"]}, key=str.lower)

    def rename_folder(self, old: str, new: str) -> None:
        for s in self.sessions:
            if s["folder"] == old:
                s["folder"] = new.strip()
        self.save()

    def export_to(self, path: str) -> None:
        _write_json(Path(path), {"networktool_sessions": 1, "sessions": self.sessions})

    def import_from(self, path: str) -> int:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = data.get("sessions", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("sessions")
        known = {s["id"] for s in self.sessions}
        new = []
        for item in items:
            if not isinstance(item, dict) or not item.get("host"):
                continue
            s = clean_session(item)
            if s["id"] in known:
                s["id"] = uuid.uuid4().hex
            new.append(s)
        self.sessions += new
        self.save()
        return len(new)
