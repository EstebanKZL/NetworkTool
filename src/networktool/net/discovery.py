"""Descubrimiento de hosts: ARP, ping, sondas TCP y tabla ARP."""

import ctypes
import os
import re
import select
import socket
import struct
import time
from typing import Dict, Optional

from networktool.common import (
    IS_LINUX, IS_MACOS, IS_WINDOWS, UNKNOWN, _hostname_cache, _hostname_cache_lock, _normalize_mac,
    logger,
)
from networktool.system import _run_command, run_command

# --- DESCUBRIMIENTO DE HOSTS ---
_ALIVE_TCP_PORTS = (80, 443, 445, 135, 139, 22, 23, 554, 8000, 8080, 8001, 3389)
_REFUSED_ERRNOS = {111, 61, 10061}   # conexión rechazada (RST): el host existe
_sendarp_fn = None

def read_arp_table() -> Dict[str, str]:
    """Tabla ARP/vecinos del sistema: {ip: MAC}. Sin entradas incompletas ni multicast."""
    table = {}
    try:
        if IS_LINUX and os.path.exists("/proc/net/arp"):
            with open("/proc/net/arp") as f:
                next(f, None)
                for line in f:
                    cols = line.split()
                    if len(cols) >= 4 and cols[2] != "0x0":
                        mac = _normalize_mac(cols[3])
                        if mac: table[cols[0]] = mac
            return table
        out = run_command("arp -a" if IS_WINDOWS else "arp -an", timeout=5)
        for m in re.finditer(r"(\d{1,3}(?:\.\d{1,3}){3})\D+?([0-9A-Fa-f]{1,2}(?:[:-][0-9A-Fa-f]{1,2}){5})", out):
            mac = _normalize_mac(m.group(2))
            if mac: table[m.group(1)] = mac
    except Exception as e:
        logger.debug(f"read_arp_table: {e}")
    return table

def _win_send_arp(ip: str) -> Optional[str]:
    """ARP vía iphlpapi.SendARP: no necesita drivers extra y usa el adaptador correcto."""
    global _sendarp_fn
    if not IS_WINDOWS:
        return None
    try:
        if _sendarp_fn is None:
            fn = ctypes.windll.iphlpapi.SendARP
            fn.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            fn.restype = ctypes.c_ulong
            _sendarp_fn = fn
        dest = struct.unpack("=I", socket.inet_aton(ip))[0]
        buf = ctypes.create_string_buffer(8)
        length = ctypes.c_ulong(6)
        if _sendarp_fn(dest, 0, buf, ctypes.byref(length)) == 0 and length.value >= 6:
            return _normalize_mac(":".join(f"{b:02x}" for b in buf.raw[:6]))
    except Exception as e:
        logger.debug(f"SendARP {ip}: {e}")
    return None

def _ping_once(ip: str, timeout_ms: int = 1000) -> bool:
    if IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    elif IS_MACOS:
        cmd = ["ping", "-c", "1", "-t", str(max(1, timeout_ms // 1000)), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, round(timeout_ms / 1000))), ip]
    out, _, rc = _run_command(cmd, timeout=timeout_ms / 1000 + 2)
    if IS_WINDOWS:
        # rc es 0 también con "Host de destino inaccesible"; TTL= solo aparece en respuestas reales
        return "TTL=" in out.upper()
    return rc == 0

def _tcp_probe(ip: str, ports=_ALIVE_TCP_PORTS, timeout: float = 1.0) -> bool:
    """Conecta a varios puertos en paralelo (no bloqueante). Abierto o rechazado = vivo."""
    socks = []
    try:
        for port in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setblocking(False)
            socks.append(s)
            rc = s.connect_ex((ip, port))
            if rc == 0 or rc in _REFUSED_ERRNOS:
                return True
        pending = list(socks)
        deadline = time.time() + timeout
        while pending:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            _, w, x = select.select([], pending, pending, remaining)
            if not w and not x:
                break
            for s in set(w) | set(x):
                err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err == 0 or err in _REFUSED_ERRNOS:
                    return True
                if s in pending:
                    pending.remove(s)
        return False
    except Exception:
        return False
    finally:
        for s in socks:
            try: s.close()
            except Exception: pass

def is_host_alive(ip: str) -> bool:
    return _tcp_probe(ip) or _ping_once(ip)

def get_mac(ip: str) -> str:
    mac = read_arp_table().get(ip)
    if not mac and IS_WINDOWS:
        mac = _win_send_arp(ip)
    return mac or UNKNOWN

def get_hostname_enhanced(ip):
    with _hostname_cache_lock:
        if ip in _hostname_cache: return _hostname_cache[ip], "cache"
    try:
        res = socket.gethostbyaddr(ip)[0]
        if res and res != ip:
            with _hostname_cache_lock: _hostname_cache[ip] = res
            return res, "dns"
    except Exception: pass
    with _hostname_cache_lock: _hostname_cache[ip] = "N/A"
    return "N/A", "none"
