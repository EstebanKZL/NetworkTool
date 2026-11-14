"""Adaptadores de red y lectura de su configuración IP."""

import re
import shutil
import socket
import struct
import time
from typing import Dict, List, Optional, Tuple

import psutil

from networktool.common import (
    IS_LINUX, IS_MACOS, IS_WINDOWS,
    _ADAPTERS_CACHE_TTL, _ADAPTER_INFO_MAP, _IPV4_RE, _cidr_to_mask, logger,
)
from networktool.system import (
    IPConfigError, _run_command, _run_powershell, _win_has_netcmdlets, run_command,
)

# -----------------------------
# ADAPTADORES
# -----------------------------
_WIN_VIRTUAL_KEYWORDS = (
    "loopback", "isatap", "teredo", "pseudo", "miniport", "virtual", "vpn", "bluetooth",
    "proxy", "vethernet", "vmware", "vmnet", "virtualbox", "hyper-v", "tailscale", "zerotier",
)
_POSIX_VIRTUAL_PREFIXES = (
    "docker", "veth", "br-", "virbr", "vmnet", "tun", "utun", "tap", "awdl", "llw",
    "gif", "stf", "anpi", "bridge", "ap1", "wg", "zt", "tailscale",
)

def _is_virtual_adapter(name: str) -> bool:
    # Antes se filtraba por la subcadena "lo", lo que ocultaba "Conexión de área local".
    low = name.lower()
    if IS_WINDOWS:
        return any(k in low for k in _WIN_VIRTUAL_KEYWORDS)
    if re.match(r"^lo\d*$", low):
        return True
    return low.startswith(_POSIX_VIRTUAL_PREFIXES)

def _win_interface_indexes() -> Dict[str, int]:
    """Nombre -> índice de interfaz (netsh funciona igual en Windows 7/10/11 y en
    cualquier idioma: las columnas Idx/Met/MTU son numéricas y el nombre va al final)."""
    result = {}
    out = run_command("netsh interface ipv4 show interfaces", timeout=4)
    for line in out.splitlines():
        m = re.match(r"^\s*(\d+)\s+\d+\s+\d+\s+\S+\s+(.+?)\s*$", line)
        if m:
            result[m.group(2)] = int(m.group(1))
    return result

def _live_ipv4(adapter: str) -> List[Tuple[str, str]]:
    """IPs IPv4 activas del adaptador según el SO (independiente del idioma).
    Las no-APIPA van primero."""
    try:
        addrs = psutil.net_if_addrs().get(adapter, [])
    except Exception:
        return []
    ips = [(a.address, a.netmask or "Sin Máscara") for a in addrs if a.family == socket.AF_INET]
    ips.sort(key=lambda t: t[0].startswith("169.254."))
    return ips

# Caché de la lista de adaptadores (propia de este módulo; ver invalidate_adapters_cache)
_ADAPTERS_CACHE: list = []
_ADAPTERS_CACHE_TIME = 0.0


def _link_is_up(adapter: str) -> Optional[bool]:
    try:
        st = psutil.net_if_stats().get(adapter)
        return st.isup if st else None
    except Exception:
        return None

def get_adapters():
    global _ADAPTERS_CACHE, _ADAPTERS_CACHE_TIME, _ADAPTER_INFO_MAP
    now = time.time()
    if _ADAPTERS_CACHE and (now - _ADAPTERS_CACHE_TIME) < _ADAPTERS_CACHE_TTL:
        return _ADAPTERS_CACHE.copy()

    adapters = []
    info_map = {}
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        win_idx = _win_interface_indexes() if IS_WINDOWS else {}
        # Adaptadores sin IPv4 en netsh (p. ej. Wi-Fi Direct "Conexión de área local* 1")
        # no se pueden configurar; solo se filtran si netsh coincidió con algún nombre.
        filter_by_idx = any(n in win_idx for n in addrs)

        for name in addrs:
            if _is_virtual_adapter(name) or (filter_by_idx and name not in win_idx):
                continue
            live = _live_ipv4(name)
            ip, mask = live[0] if live else ("Sin IP", "Sin Máscara")
            is_up = stats[name].isup if name in stats else False

            # En Windows se muestran todos los físicos aunque no tengan IP (pueden
            # estar en DHCP sin cable); en Linux/Mac solo los activos o con IP.
            if not IS_WINDOWS and not (is_up or live):
                continue
            adapters.append(name)
            info_map[name] = {
                "ip": ip,
                "mask": mask,
                "status": "Conectado" if is_up else "Desconectado",
                "index": win_idx.get(name),
            }
    except Exception as e:
        logger.error(f"Error obteniendo adaptadores: {e}")

    # En Windows, si no se encontraron adaptadores con psutil, usar ipconfig
    if not adapters and IS_WINDOWS:
        try:
            out = run_command("ipconfig", timeout=3)
            for line in out.splitlines():
                match = re.search(r"(?:adaptador|adapter)\s+(?:de\s+)?(?:\S+\s+)?(.+?):\s*$", line, re.IGNORECASE)
                if match:
                    current_adapter = match.group(1).strip()
                    if current_adapter and current_adapter not in adapters and "loopback" not in current_adapter.lower():
                        adapters.append(current_adapter)
                        info_map[current_adapter] = {
                            "ip": "Sin IP", "mask": "Sin Máscara", "status": "Desconocido", "index": None
                        }
        except Exception:
            pass

    # Conectados primero
    adapters.sort(key=lambda n: (info_map[n]["status"] != "Conectado", n.lower()))
    _ADAPTER_INFO_MAP = info_map
    _ADAPTERS_CACHE = adapters
    _ADAPTERS_CACHE_TIME = now
    return adapters.copy()

def invalidate_adapters_cache() -> None:
    global _ADAPTERS_CACHE, _ADAPTERS_CACHE_TIME
    _ADAPTERS_CACHE = []; _ADAPTERS_CACHE_TIME = 0

def _adapter_index(adapter: str) -> Optional[int]:
    idx = _ADAPTER_INFO_MAP.get(adapter, {}).get("index")
    if idx is None and IS_WINDOWS:
        idx = _win_interface_indexes().get(adapter)
        if idx is not None and adapter in _ADAPTER_INFO_MAP:
            _ADAPTER_INFO_MAP[adapter]["index"] = idx
    return idx

def _netsh_name(adapter: str) -> str:
    """netsh acepta el índice en name=, lo que evita problemas con espacios y tildes."""
    idx = _adapter_index(adapter)
    return str(idx) if idx is not None else f'"{adapter}"'

def debug_adapters():
    """Función de depuración para ver nombres reales de adaptadores"""
    print("=" * 50)
    print("ADAPTADORES DETECTADOS:")
    print("=" * 50)

    if IS_WINDOWS:
        out = run_command("netsh interface ipv4 show interfaces", timeout=3)
        print("Netsh interfaces:")
        print(out)
        if _win_has_netcmdlets():
            stdout, _, _ = _run_powershell("Get-NetAdapter | Select-Object Name, ifIndex, InterfaceDescription, Status | Format-List", 8)
            print("\nPowerShell adapters:")
            print(stdout)

    addrs = psutil.net_if_addrs()
    print("\nPsutil adapters:")
    for name in addrs.keys():
        print(f"  - {name}{'  (virtual, oculto)' if _is_virtual_adapter(name) else ''}")
    print("=" * 50)

def _win_read_config(adapter: str) -> Dict:
    """Configuración IPv4 *configurada* del adaptador (también con el cable desconectado),
    leída de 'netsh ... show config' sin depender del idioma de Windows:
      - DHCP: primera línea que contiene 'DHCP' (Sí/Yes/Ja → activo, No/Nein/Non → inactivo).
      - IP: valor IPv4 seguido de una línea 'x.x.x.x/NN'.
      - Gateway: etiqueta con 'gateway/enlace/passerelle' o IPv4 seguida de una métrica."""
    cfg = {"dhcp": None, "ips": [], "gateway": None}
    out = run_command(f"netsh interface ipv4 show config name={_netsh_name(adapter)}", timeout=4)
    rows = []
    for line in out.splitlines():
        if ":" in line:
            label, _, value = line.partition(":")
            rows.append((label.strip().lower(), value.strip()))

    for i, (label, value) in enumerate(rows):
        if cfg["dhcp"] is None and "dhcp" in label:
            cfg["dhcp"] = not value.lower().startswith("n")
            continue
        if not re.fullmatch(_IPV4_RE, value):
            continue
        nxt = rows[i + 1][1] if i + 1 < len(rows) else ""
        m_prefix = re.match(_IPV4_RE + r"/(\d+)", nxt)
        if m_prefix:
            cfg["ips"].append((value, _cidr_to_mask(int(m_prefix.group(2)))))
        elif cfg["gateway"] is None and "dns" not in label and "wins" not in label and (
                any(k in label for k in ("gateway", "enlace", "passerelle", "puerta"))
                or re.fullmatch(r"\d+", nxt)):
            if value != "0.0.0.0":
                cfg["gateway"] = value
    return cfg

def _get_ip_info_direct(adapter: str) -> Tuple[str, str, str, str]:
    """Devuelve (ip, mask, gateway, dhcp) leyendo el SO directamente (Linux / macOS)."""
    ip      = "Sin IP"
    mask    = "Sin Máscara"
    gateway = "Sin gateway"
    dhcp    = "Desconocido"

    if IS_LINUX:
        # 1. IP y máscara con 'ip addr show'
        try:
            out = run_command(["ip", "-4", "addr", "show", "dev", adapter], timeout=2)
            m   = re.search(r'inet\s+([0-9.]+)/(\d+)', out)
            if m:
                ip   = m.group(1)
                mask = _cidr_to_mask(int(m.group(2)))
        except Exception:
            pass
        # 2. Gateway
        for cmd in [["ip", "route", "show", "default", "dev", adapter],
                    ["ip", "route", "show", "default"]]:
            try:
                out = run_command(cmd, timeout=2)
                m   = re.search(r'default via\s+([0-9.]+)', out)
                if m:
                    gateway = m.group(1); break
            except Exception:
                pass
        # 3. DHCP via nmcli
        try:
            out = run_command(["nmcli", "-g", "IP4.METHOD", "device", "show", adapter], timeout=2)
            if not out.strip():
                con = _nm_connection_for(adapter)
                if con:
                    out = run_command(["nmcli", "-g", "ipv4.method", "connection", "show", con], timeout=2)
            if "auto" in out.lower():   dhcp = "Habilitado"
            elif "manual" in out.lower(): dhcp = "Deshabilitado"
        except Exception:
            pass
        # 4. Fallback DHCP via ps
        if dhcp == "Desconocido":
            try:
                out = run_command(f"ps -eo cmd 2>/dev/null | grep -E 'dhclient|dhcpcd|udhcpc' | grep {adapter}", timeout=1)
                if adapter in out: dhcp = "Habilitado"
            except Exception:
                pass

    elif IS_MACOS:
        try:
            out = run_command(["ifconfig", adapter], timeout=2)
            m   = re.search(r'inet\s+([0-9.]+)\s+netmask\s+(0x[0-9a-fA-F]+|[0-9.]+)', out)
            if m:
                ip = m.group(1); nm = m.group(2)
                mask = socket.inet_ntoa(struct.pack('>I', int(nm, 16))) if nm.startswith("0x") else nm
        except Exception:
            pass
        try:
            out = run_command(["netstat", "-rn"], timeout=2)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[0] in ("default", "0.0.0.0") and parts[-1] == adapter:
                    gateway = parts[1]; break
        except Exception:
            pass
        try:
            out = run_command(["ipconfig", "getpacket", adapter], timeout=2)
            dhcp = "Habilitado" if "yiaddr" in out else "Deshabilitado"
        except Exception:
            pass

    return ip, mask, gateway, dhcp

def get_ip_info(adapter: str) -> Tuple[str, str, str, str]:
    """Devuelve (ip, mask, gateway, dhcp) para el adaptador."""
    info = _ADAPTER_INFO_MAP.get(adapter, {})
    live = _live_ipv4(adapter)
    ip, mask = live[0] if live else (info.get("ip", "Sin IP"), info.get("mask", "Sin Máscara"))

    if IS_WINDOWS:
        cfg = _win_read_config(adapter)
        if not live and cfg["ips"]:
            # IP estática configurada en un adaptador sin cable: Windows no la publica como activa
            ip, mask = cfg["ips"][0]
        gateway = cfg["gateway"] or "Sin gateway"
        dhcp = {True: "Habilitado", False: "Deshabilitado"}.get(cfg["dhcp"], "Desconocido")
        return ip, mask, gateway, dhcp

    if IS_LINUX or IS_MACOS:
        ip_d, mask_d, gateway, dhcp = _get_ip_info_direct(adapter)
        if not live and ip_d != "Sin IP":
            ip, mask = ip_d, mask_d
        return ip, mask, gateway, dhcp

    return ip, mask, "Sin gateway", "Desconocido"

def get_adapter_link_status(adapter):
    info = _ADAPTER_INFO_MAP.get(adapter)
    return info["status"] if info else "Desconocido"

# ── Linux ──────────────────────────────────────────────────────────────
def _nm_device_managed(adapter: str) -> bool:
    out = run_command(["nmcli", "-t", "-f", "DEVICE,STATE", "device"], timeout=4)
    for line in out.splitlines():
        dev, _, state = line.partition(":")
        if dev == adapter:
            return "unmanaged" not in state
    return False

def _nm_connection_for(adapter: str, create: bool = False) -> Optional[str]:
    if not shutil.which("nmcli"):
        return None
    out = run_command(["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", adapter], timeout=4)
    con = out.strip().replace("\\:", ":")
    if con and con != "--":
        return con
    # Conexión inactiva ligada al dispositivo
    out = run_command(["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "connection", "show"], timeout=4)
    own = f"NetworkTool-{adapter}"
    for line in out.splitlines():
        parts = re.split(r"(?<!\\):", line)
        if parts and parts[0].replace("\\:", ":") == own:
            return own
    if create:
        _, err, rc = _run_command(["nmcli", "connection", "add", "type", "ethernet", "ifname", adapter,
                                   "con-name", own, "autoconnect", "yes"], timeout=10)
        if rc == 0:
            return own
        raise IPConfigError(f"nmcli no pudo crear la conexión: {err.strip()}")
    return None
