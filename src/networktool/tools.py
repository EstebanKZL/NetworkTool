"""Herramientas de red: ping, Wake-on-LAN y cálculo de subredes."""

import ipaddress
import re
import socket
from typing import List, Optional, Tuple

from networktool.common import IS_MACOS, IS_WINDOWS, _normalize_mac, _normalize_mask
from networktool.i18n import tr
from networktool.system import _run_command

# -----------------------------
# HERRAMIENTAS INTEGRADAS
# -----------------------------
_PING_MS_RE = re.compile(r"[=<]\s*(\d+(?:[.,]\d+)?)\s*ms?\b", re.IGNORECASE)

def ping_latency(target: str, timeout_ms: int = 1000) -> Optional[float]:
    """Un ping; devuelve la latencia en ms o None si no hubo respuesta.
    Admite 'tiempo=3ms', 'tiempo<1m' (Windows en español) y 'time=0.42 ms' (Linux/macOS)."""
    if IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), target]
    elif IS_MACOS:
        cmd = ["ping", "-c", "1", "-t", str(max(1, timeout_ms // 1000)), target]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, round(timeout_ms / 1000))), target]
    out, _, rc = _run_command(cmd, timeout=timeout_ms / 1000 + 3)
    for line in out.splitlines():
        if "ttl=" in line.lower():
            m = _PING_MS_RE.search(line.split(":", 1)[-1])
            if m:
                return float(m.group(1).replace(",", "."))
            return 0.5
    return None

def send_magic_packet(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Wake-on-LAN: 6×FF + 16 repeticiones de la MAC, por UDP broadcast."""
    norm = _normalize_mac(mac)
    if not norm:
        raise ValueError(f"MAC inválida: '{mac}'")
    payload = b"\xff" * 6 + bytes.fromhex(norm.replace(":", "")) * 16
    targets = [broadcast] if broadcast == "255.255.255.255" else [broadcast, "255.255.255.255"]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for t in targets:
            s.sendto(payload, (t, port))

def subnet_info(text: str, mask: str = "") -> List[Tuple[str, str]]:
    """Datos de una red a partir de 'IP/prefijo' o IP + máscara. Lanza ValueError."""
    text = text.strip()
    if "/" not in text:
        text = f"{text}/{_normalize_mask(mask or '24')}"
    iface = ipaddress.IPv4Interface(text)
    net = iface.network
    hosts = net.num_addresses - 2 if net.prefixlen < 31 else net.num_addresses
    first = net.network_address + (1 if net.prefixlen < 31 else 0)
    last = net.broadcast_address - (1 if net.prefixlen < 31 else 0)
    first_octet = int(str(net.network_address).split(".")[0])
    klass = "A" if first_octet < 128 else "B" if first_octet < 192 else "C" if first_octet < 224 else "D/E"
    kind = (tr("subnet.private") if net.is_private and not net.is_link_local and not net.is_loopback
            else "Link-local / APIPA (169.254.x.x)" if net.is_link_local
            else "Loopback" if net.is_loopback else tr("subnet.public"))
    return [
        ("IP", str(iface.ip)), (tr("subnet.network"), f"{net.network_address}/{net.prefixlen}"),
        (tr("subnet.mask"), str(net.netmask)), ("Wildcard", str(net.hostmask)),
        ("Broadcast", str(net.broadcast_address)),
        (tr("subnet.first"), str(first)), (tr("subnet.last"), str(last)),
        (tr("subnet.hosts"), f"{hosts:,}".replace(",", ".")),
        (tr("subnet.class"), klass), (tr("subnet.type"), kind),
        (tr("subnet.binary"), ".".join(f"{int(o):08b}" for o in str(net.netmask).split("."))),
    ]

def split_subnet(network: str, new_prefix: int, limit: int = 256) -> List[str]:
    net = ipaddress.IPv4Network(network, strict=False)
    if new_prefix < net.prefixlen or new_prefix > 32:
        raise ValueError(tr("subnet.bad_prefix", prefix=net.prefixlen))
    out = []
    for i, sub in enumerate(net.subnets(new_prefix=new_prefix)):
        if i >= limit:
            out.append(tr("subnet.more", n=2 ** (new_prefix - net.prefixlen) - limit))
            break
        hosts = list(sub.hosts()) if sub.prefixlen < 31 else list(sub)
        rng = f"{hosts[0]} – {hosts[-1]}" if hosts else "-"
        out.append(f"{str(sub):<20} {rng:<34} broadcast {sub.broadcast_address}")
    return out
