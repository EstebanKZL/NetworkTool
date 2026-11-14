"""Puertos, servicios, tipo de dispositivo y base de fabricantes (OUI)."""

import csv
import os
import re
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from networktool.common import (
    SERVICE_NAMES, UNKNOWN, VENDOR_CACHE_TTL, _http_session, _read_json, _vendor_cache,
    _vendor_cache_lock, _write_json, logger, nettool_data_dir,
)

# -----------------------------
# BASE LOCAL DE FABRICANTES (OUI)
# -----------------------------
OUI_SOURCES = [
    # Lista de fabricantes que mantiene Wireshark (incluye bloques MA-M /28 y MA-S /36)
    ("wireshark", "https://www.wireshark.org/download/automated/data/manuf"),
    # Registro oficial de la IEEE (solo MA-L /24)
    ("ieee", "https://standards-oui.ieee.org/oui/oui.csv"),
]
OUI_MAX_AGE_DAYS = 90
_oui_db: Optional[Dict[int, Dict[int, str]]] = None
_oui_lock = threading.Lock()

def oui_db_path() -> Path:
    return nettool_data_dir() / "oui_db.tsv"

def _parse_wireshark_manuf(text: str) -> List[Tuple[str, int, str]]:
    rows = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        m = re.match(r"^([0-9A-Fa-f]{2}(?:[:\-.][0-9A-Fa-f]{2}){2,5})(?:/(\d+))?$", cols[0].strip())
        if not m:
            continue
        hexs = re.sub(r"[^0-9A-Fa-f]", "", m.group(1)).upper()
        bits = int(m.group(2)) if m.group(2) else len(hexs) * 4
        vendor = (cols[2] if len(cols) > 2 and cols[2].strip() else cols[1]).strip()
        if vendor and bits in (24, 28, 36):
            rows.append((hexs[:(bits + 3) // 4], bits, vendor))
    return rows

def _parse_ieee_csv(text: str) -> List[Tuple[str, int, str]]:
    rows = []
    for rec in csv.reader(text.splitlines()):
        if len(rec) >= 3 and re.fullmatch(r"[0-9A-Fa-f]{6}", rec[1].strip()):
            rows.append((rec[1].strip().upper(), 24, rec[2].strip()))
    return rows

def update_oui_db(timeout: float = 30) -> Tuple[bool, str]:
    """Descarga la base de fabricantes y la guarda en oui_db.tsv."""
    errors = []
    for name, url in OUI_SOURCES:
        try:
            r = _http_session.get(url, timeout=timeout)
            r.raise_for_status()
            rows = _parse_wireshark_manuf(r.text) if name == "wireshark" else _parse_ieee_csv(r.text)
            if len(rows) < 1000:
                raise ValueError(f"solo {len(rows)} registros")
            path = oui_db_path()
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(f"{h}\t{b}\t{v}" for h, b, v in rows), encoding="utf-8")
            os.replace(tmp, path)
            with _oui_lock:
                global _oui_db
                _oui_db = None
            return True, f"Base de fabricantes actualizada: {len(rows)} registros ({name})."
        except Exception as e:
            errors.append(f"{name}: {e}")
    return False, "No se pudo descargar la base de fabricantes.\n" + "\n".join(errors)

def _load_oui_db() -> Dict[int, Dict[int, str]]:
    global _oui_db
    with _oui_lock:
        if _oui_db is not None:
            return _oui_db
        db: Dict[int, Dict[int, str]] = {24: {}, 28: {}, 36: {}}
        try:
            path = oui_db_path()
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    h, _, rest = line.partition("\t")
                    b, _, vendor = rest.partition("\t")
                    if h and b.isdigit() and int(b) in db:
                        db[int(b)][int(h, 16) >> ((len(h) * 4) - int(b))] = vendor
        except Exception as e:
            logger.warning(f"No se pudo cargar la base de fabricantes: {e}")
        _oui_db = db
        return db

def oui_db_needs_update() -> bool:
    path = oui_db_path()
    return not path.exists() or (time.time() - path.stat().st_mtime) > OUI_MAX_AGE_DAYS * 86400

def oui_lookup(mac: str) -> Optional[str]:
    try:
        value = int(mac.replace(":", "").replace("-", ""), 16)
    except Exception:
        return None
    db = _load_oui_db()
    for bits in (36, 28, 24):   # el bloque más específico primero
        vendor = db[bits].get(value >> (48 - bits))
        if vendor:
            return vendor
    return None

def get_service_name(port): return SERVICE_NAMES.get(port, f"Port-{port}")

_vendor_api_lock = threading.Lock()
_vendor_api_state = {"last": 0.0, "offline_until": 0.0}
_vendor_disk_cache: Dict[str, str] = {}
_vendor_disk_loaded = [False]

def _load_persistent_vendor_cache() -> None:
    """Llamar con _vendor_cache_lock tomado."""
    if not _vendor_disk_loaded[0]:
        data = _read_json(nettool_data_dir() / "vendor_cache.json", {})
        if isinstance(data, dict):
            _vendor_disk_cache.update({k: v for k, v in data.items() if isinstance(v, str)})
        _vendor_disk_loaded[0] = True

def mac_vendor(mac: str) -> str:
    if not mac or mac == UNKNOWN: return UNKNOWN
    try:
        if int(mac.split(":")[0], 16) & 0x02:
            return "MAC privada/aleatoria"
    except Exception:
        pass
    vendor = oui_lookup(mac)
    if vendor:
        return vendor
    prefix = mac[:8]
    with _vendor_cache_lock:
        _load_persistent_vendor_cache()
        if prefix in _vendor_disk_cache:
            return _vendor_disk_cache[prefix]
        if mac in _vendor_cache:
            vendor, ts = _vendor_cache[mac]
            if time.time() - ts < VENDOR_CACHE_TTL:
                return vendor
    # macvendors.com admite ~1 consulta/s: en paralelo devolvía 429 y quedaba "Unknown".
    # Sin internet se deja de consultar 5 minutos en lugar de esperar 2 s por equipo.
    with _vendor_api_lock:
        if time.time() < _vendor_api_state["offline_until"]:
            return UNKNOWN
        delay = 1.1 - (time.time() - _vendor_api_state["last"])
        if delay > 0:
            time.sleep(delay)
        try:
            r = _http_session.get(f"https://api.macvendors.com/{mac}", timeout=2)
        except Exception:
            _vendor_api_state["offline_until"] = time.time() + 300
            return UNKNOWN
        finally:
            _vendor_api_state["last"] = time.time()
    if r.status_code == 200:
        vendor = r.text.strip() or UNKNOWN
        if vendor != UNKNOWN:
            # Se guarda en disco por prefijo OUI: sirve sin internet en la próxima visita
            with _vendor_cache_lock:
                _vendor_disk_cache[prefix] = vendor
                try: _write_json(nettool_data_dir() / "vendor_cache.json", _vendor_disk_cache)
                except Exception: pass
    elif r.status_code == 404:
        vendor = UNKNOWN
    else:
        return UNKNOWN   # 429 u otro error temporal: no se guarda en caché
    with _vendor_cache_lock:
        _vendor_cache[mac] = (vendor, time.time())
    return vendor

def check_onvif(ip, port=80):
    try:
        soap = """<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><soap:Body><tds:GetDeviceInformation/></soap:Body></soap:Envelope>"""
        r = _http_session.post(f"http://{ip}:{port}/onvif/device_service", data=soap, headers={"Content-Type": "application/soap+xml"}, timeout=1.5)
        if r.status_code == 200 and "onvif" in r.text.lower(): return True, "ONVIF Device"
    except Exception: pass
    return False, None

def check_hikvision(ip, port=80):
    try:
        for end in ["/onvif-http/device_service", "/ISAPI/System/deviceInfo", "/SDK/webLanguage.html", "/doc/page/login.asp"]:
            try:
                r = _http_session.get(f"http://{ip}:{port}{end}", timeout=1)
                if "HIKVISION" in r.text.upper(): return True, "Hikvision Device"
            except Exception: pass
        r = _http_session.get(f"http://{ip}:{port}", timeout=1)
        if "HIKVISION" in r.headers.get("Server", "").upper(): return True, "Hikvision Device"
    except Exception: pass
    return False, None

def check_dahua(ip, port=80):
    try:
        r = _http_session.get(f"http://{ip}:{port}", timeout=1)
        if "DAHUA" in r.text.upper() or "DAHUA" in r.headers.get("Server", "").upper(): return True, "Dahua Device"
        r = _http_session.get(f"http://{ip}:{port}/cgi-bin/magicBox.cgi?action=getSystemInfo", timeout=1)
        if "dahua" in r.text.lower(): return True, "Dahua Device"
    except Exception: pass
    return False, None

def discover_rtsp_streams(ip, port=554):
    paths = ["/live", "/stream1", "/stream2", "/video1", "/ch1", "/main", "/sub", "/cam1"]
    found = []
    for path in paths:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.8)
                if s.connect_ex((ip, port)) == 0:
                    s.send(f"DESCRIBE rtsp://{ip}:{port}{path} RTSP/1.0\r\nCSeq: 2\r\n\r\n".encode())
                    if "200 OK" in s.recv(1024).decode("utf-8", errors="ignore"): found.append(f"rtsp://{ip}:{port}{path}")
        except Exception: pass
    return found

def check_rtsp(ip, port=554):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            if s.connect_ex((ip, port)) == 0:
                s.send(f"OPTIONS rtsp://{ip}:{port} RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
                resp = s.recv(1024).decode("utf-8", errors="ignore")
                if "RTSP/1.0" in resp or "RTSP/1.1" in resp: return True, discover_rtsp_streams(ip, port)
    except Exception: pass
    return False, []

def check_vnc(ip, port=5900):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            if s.connect_ex((ip, port)) == 0:
                banner = s.recv(1024).decode("utf-8", errors="ignore")
                if "RFB" in banner: return True, banner.strip()
    except Exception: pass
    return False, None

def check_samba(ip, port=445):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            if s.connect_ex((ip, port)) == 0:
                s.send(struct.pack(">I", 0x00000000))
                if s.recv(4): return True, "SMB Share"
    except Exception: pass
    return False, None

def check_telnet(ip, port=23):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            if s.connect_ex((ip, port)) == 0: return True, s.recv(1024).decode("utf-8", errors="ignore").strip() or "Telnet"
    except Exception: pass
    return False, None

def check_ssh(ip, port=22):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            if s.connect_ex((ip, port)) == 0:
                banner = s.recv(1024).decode("utf-8", errors="ignore")
                if "SSH" in banner: return True, banner.strip()
    except Exception: pass
    return False, None

def check_ntp(ip, port=123):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.sendto(b"\x1b" + 47 * b"\0", (ip, port))
            if s.recvfrom(1024)[0]: return True
    except Exception: pass
    return False

def check_http_https(ip, port):
    proto = "https" if port == 443 else "http"
    try:
        r = _http_session.get(f"{proto}://{ip}:{port}", timeout=1.5, verify=False)
        title_match = re.search(r"<title>(.*?)</title>", r.text, re.IGNORECASE)
        return {"status": True, "server": r.headers.get("Server", "Unknown"), "title": title_match.group(1) if title_match else "No title"}
    except: return {"status": False}

def detect_service(ip, port):
    info = {"name": get_service_name(port), "details": None}
    if port in [80, 443, 8080, 8443]:
        h = check_http_https(ip, port)
        if h["status"]: info["details"] = f"{h['server']} - {h['title']}"
    elif port == 554:
        r_ok, streams = check_rtsp(ip, port)
        if r_ok:
            info["details"] = f"RTSP Streams: {len(streams)}"
            info["streams"] = streams
    elif port == 22:
        ok, ver = check_ssh(ip, port)
        if ok: info["details"] = ver
    elif port == 23:
        ok, ban = check_telnet(ip, port)
        if ok: info["details"] = ban
    elif port == 3389: info["details"] = "Windows Remote Desktop"
    elif port in [5900, 5901]:
        ok, ver = check_vnc(ip, port)
        if ok: info["details"] = ver
    elif port == 445:
        ok, _ = check_samba(ip, port)
        if ok: info["details"] = "SMB/CIFS Share"
    elif port == 123:
        if check_ntp(ip, port): info["details"] = "NTP Server (UDP)"
    return info

def scan_ports_advanced(ip: str, ports_to_scan: List[int], port_timeout: float = 0.3) -> Tuple[List[int], Dict]:
    open_ports: List[int] = []
    services: Dict = {}
    lock = threading.Lock()
    def check_port(port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(port_timeout)
                if s.connect_ex((ip, port)) == 0:
                    with lock: open_ports.append(port)
        except Exception:
            pass
    workers = min(50, len(ports_to_scan)) if ports_to_scan else 1
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(check_port, p) for p in ports_to_scan]
        wait(futures, timeout=5)
    open_ports.sort()
    for port in open_ports: services[port] = detect_service(ip, port)
    return open_ports, services

def classify_device(ip: str, ports: List[int], services: Dict) -> Tuple[str, List[Tuple[str, str]]]:
    """Tipo de dispositivo y servicios especiales. Las sondas HTTP/RTSP se hacen una
    sola vez y solo si el puerto correspondiente está abierto (antes se repetían y
    esperaban timeouts en equipos sin web)."""
    web_port = next((p for p in (80, 8080, 8000) if p in ports), None)
    no = (False, None)
    onvif = check_onvif(ip, web_port) if web_port else no
    hik = check_hikvision(ip, web_port) if web_port else no
    dahua = check_dahua(ip, web_port) if web_port else no
    rtsp_ok, streams = check_rtsp(ip) if 554 in ports else (False, [])

    device = "Unknown Device"
    if onvif[0]: device = "ONVIF Camera"
    elif hik[0]: device = "Hikvision Camera"
    elif dahua[0]: device = "Dahua Camera"
    elif 554 in ports: device = "RTSP Camera"
    elif 3389 in ports: device = "Windows RDP"
    elif 22 in ports: device = "SSH Server"
    elif 80 in ports or 443 in ports: device = "Web Server"
    elif 445 in ports: device = "SMB Share"
    elif 123 in ports: device = "NTP Server"

    special_services = []
    if onvif[0]: special_services.append(("ONVIF", onvif[1]))
    if hik[0]: special_services.append(("Hikvision", hik[1]))
    if dahua[0]: special_services.append(("Dahua", dahua[1]))
    if rtsp_ok and streams:
        for i, stream in enumerate(streams[:3]): special_services.append((f"RTSP Stream {i+1}", stream))
    elif 554 in ports:
        special_services.append(("RTSP", f"rtsp://{ip}:554"))
    if 123 in ports:
        special_services.append(("NTP Server", "NTP (UDP)"))
    return device, special_services
