"""Aplicar IP estática, DHCP e IPs secundarias (Windows, Linux, macOS)."""

import ipaddress
import re
import shutil
import time
from typing import Dict, List, Optional, Tuple

from networktool.common import IS_MACOS, IS_WINDOWS, _IPV4_RE, _normalize_mask, logger, mask_to_cidr
from networktool.net.adapters import (
    _adapter_index, _link_is_up, _live_ipv4, _netsh_name, _nm_connection_for,
    _nm_device_managed, _win_read_config, get_ip_info,
)
from networktool.system import (
    IPConfigError, _ps_quote, _run_command, _run_powershell, _win_has_netcmdlets, is_admin,
    run_command,
)
from networktool.i18n import tr

# Los mensajes de éxito con advertencia llevan este prefijo (la UI los muestra como aviso)
WARNING_PREFIX = tr("ipc.warning_prefix")

# -----------------------------
# CONFIGURACIÓN IP (ESTÁTICA / DHCP)
# -----------------------------
def _validate_static(ip, mask, gateway, dns):
    """Normaliza y valida los parámetros. Lanza ValueError con un mensaje legible."""
    ip = str(ip or "").strip()
    try:
        ipaddress.IPv4Address(ip)
    except Exception:
        raise ValueError(tr("ipc.invalid_ip", ip=ip))
    mask = _normalize_mask(mask)
    net = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
    if net.prefixlen < 31 and ip in (str(net.network_address), str(net.broadcast_address)):
        raise ValueError(tr("ipc.net_or_bcast", ip=ip, net=net))

    gateway = str(gateway or "").strip()
    if gateway:
        try:
            gw_addr = ipaddress.IPv4Address(gateway)
        except Exception:
            raise ValueError(tr("ipc.invalid_gw", gw=gateway))
        if gw_addr not in net:
            raise ValueError(tr("ipc.gw_not_in_net", gw=gateway, net=net))
        if gateway == ip:
            raise ValueError(tr("ipc.gw_is_ip"))

    dns_list = [d for d in re.split(r"[,;\s]+", str(dns or "").strip()) if d]
    for d in dns_list:
        try:
            ipaddress.IPv4Address(d)
        except Exception:
            raise ValueError(tr("ipc.invalid_dns", dns=d))
    return ip, mask, gateway, dns_list

def _parse_extra_ips(extra, default_mask: str, primary_ip: str = "") -> List[Tuple[str, str]]:
    """IPs adicionales: 'ip', 'ip/24' o (ip, mask). Lanza ValueError si alguna es inválida."""
    result = []
    for item in extra or []:
        if isinstance(item, (list, tuple)):
            a, m = item[0], item[1]
        else:
            a, _, m = str(item).strip().partition("/")
            m = m or default_mask
        a = str(a).strip()
        if not a:
            continue
        try:
            ipaddress.IPv4Address(a)
        except Exception:
            raise ValueError(tr("ipc.invalid_extra", ip=a))
        m = _normalize_mask(m)
        if a != primary_ip and a not in [x for x, _ in result]:
            result.append((a, m))
    return result

def _configured_ipv4(adapter: str) -> List[Tuple[str, str]]:
    """IPs configuradas (en Windows también las de un adaptador sin cable)."""
    if IS_WINDOWS:
        ips = _win_read_config(adapter)["ips"]
        if ips:
            return ips
    return _live_ipv4(adapter)

def _snapshot_config(adapter: str) -> Dict:
    ip, mask, gw, dhcp = get_ip_info(adapter)
    # Una 169.254.x estática (equipos con IP de fábrica) es válida; una APIPA con DHCP no se restaura
    valid_ip = bool(re.fullmatch(_IPV4_RE, ip or "")) and (
        not ip.startswith("169.254.") or dhcp == "Deshabilitado")
    return {
        "dhcp": dhcp == "Habilitado",
        "ip": ip if valid_ip else None,
        "mask": mask,
        "gateway": gw if re.fullmatch(_IPV4_RE, gw or "") else "",
        "extra": ([[a, m] for a, m in _configured_ipv4(adapter) if a != ip]
                  if dhcp == "Deshabilitado" else []),
    }

def _rollback_config(adapter: str, before: Dict) -> str:
    if not before:
        return ""
    try:
        if before["dhcp"]:
            ok, _ = set_dhcp_ip(adapter, _rollback=False, wait_lease=3)
        elif before["ip"]:
            ok, _ = set_static_ip(adapter, before["ip"], before["mask"], before["gateway"],
                                  extra_ips=before.get("extra"), _rollback=False)
        else:
            return ""
    except Exception:
        ok = False
    return ("\n\n" + tr("ipc.rolled_back") if ok else "\n\n" + tr("ipc.rollback_failed"))

# ── Windows ────────────────────────────────────────────────────────────
def _win_apply_static(adapter, ip, mask, gateway, dns_list, extra=()):
    prefix = mask_to_cidr(mask)
    idx = _adapter_index(adapter)
    ps_error = ""

    if idx is not None and _win_has_netcmdlets():
        gw_line = f"$p.DefaultGateway = {_ps_quote(gateway)}" if gateway else ""
        dns_line = ("Set-DnsClientServerAddress -InterfaceIndex $idx -ServerAddresses @("
                    + ", ".join(_ps_quote(d) for d in dns_list) + ")") if dns_list else ""
        # SkipAsSource: las IPs adicionales no se usan como origen de las conexiones salientes
        extra_lines = "\n    ".join(
            f"New-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -IPAddress {_ps_quote(a)} "
            f"-PrefixLength {mask_to_cidr(m)} -SkipAsSource $true | Out-Null" for a, m in extra)
        script = f"""
$ErrorActionPreference = 'Stop'
try {{
    $idx = {idx}
    Set-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -Dhcp Disabled
    # Borra IPs y gateways previos en ambos almacenes; si no, quedan gateways "fantasma"
    foreach ($store in 'ActiveStore', 'PersistentStore') {{
        Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -PolicyStore $store -ErrorAction SilentlyContinue |
            Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
        Get-NetRoute -InterfaceIndex $idx -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -PolicyStore $store -ErrorAction SilentlyContinue |
            Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
    }}
    $p = @{{ InterfaceIndex = $idx; AddressFamily = 'IPv4'; IPAddress = {_ps_quote(ip)}; PrefixLength = {prefix} }}
    {gw_line}
    New-NetIPAddress @p | Out-Null
    {extra_lines}
    {dns_line}
    # Detección de duplicados (DAD): la IP pasa por 'Tentative' y termina en 'Preferred' o 'Duplicate'
    $deadline = (Get-Date).AddSeconds(4)
    do {{
        $a = Get-NetIPAddress -InterfaceIndex $idx -IPAddress {_ps_quote(ip)} -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $a -or $a.AddressState -ne 'Tentative') {{ break }}
        Start-Sleep -Milliseconds 300
    }} while ((Get-Date) -lt $deadline)
    if ($a) {{ Write-Output ('STATE=' + $a.AddressState) }}
    Write-Output 'OK'
}} catch {{
    Write-Output ('ERROR=' + $_.Exception.Message)
    exit 1
}}
"""
        out, err, rc = _run_powershell(script, timeout=30)
        logger.debug(f"PowerShell static ({adapter}): rc={rc} out={out} err={err}")
        if "STATE=Duplicate" in out:
            raise IPConfigError(tr("ipc.conflict", ip=ip))
        if rc == 0 and "OK" in out.splitlines():
            return
        m = re.search(r"ERROR=(.*)", out)
        ps_error = (m.group(1) if m else (err or out or "error desconocido")).strip()
        logger.warning(f"PowerShell falló ({ps_error}); usando netsh")

    # netsh (Windows 7 o si PowerShell falló)
    name = _netsh_name(adapter)
    gw_part = f"gateway={gateway} gwmetric=1" if gateway else "gateway=none"
    out, err, rc = _run_command(
        f"netsh interface ipv4 set address name={name} source=static address={ip} mask={mask} {gw_part}",
        timeout=20)
    if rc != 0:
        detail = (out or err).strip()
        raise IPConfigError(f"netsh: {detail}" + (f"\nPowerShell: {ps_error}" if ps_error else ""))
    for a, m in extra:
        _run_command(f"netsh interface ipv4 add address name={name} address={a} mask={m}", timeout=10)
    if dns_list:
        _run_command(f"netsh interface ipv4 set dnsservers name={name} source=static address={dns_list[0]} register=primary validate=no", timeout=10)
        for i, d in enumerate(dns_list[1:], start=2):
            _run_command(f"netsh interface ipv4 add dnsservers name={name} address={d} index={i} validate=no", timeout=10)

def _win_apply_dhcp(adapter):
    idx = _adapter_index(adapter)
    ps_error = ""
    if idx is not None and _win_has_netcmdlets():
        script = f"""
$ErrorActionPreference = 'Stop'
try {{
    $idx = {idx}
    # Quitar IPs y gateways manuales; si no, Windows conserva el gateway estático junto al de DHCP
    foreach ($store in 'ActiveStore', 'PersistentStore') {{
        Get-NetRoute -InterfaceIndex $idx -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -PolicyStore $store -ErrorAction SilentlyContinue |
            Where-Object {{ $_.Protocol -ne 'Dhcp' }} | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
        Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -PolicyStore $store -ErrorAction SilentlyContinue |
            Where-Object {{ $_.PrefixOrigin -eq 'Manual' }} | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
    }}
    Set-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -Dhcp Enabled
    Set-DnsClientServerAddress -InterfaceIndex $idx -ResetServerAddresses
    Write-Output 'OK'
}} catch {{
    Write-Output ('ERROR=' + $_.Exception.Message)
    exit 1
}}
"""
        out, err, rc = _run_powershell(script, timeout=30)
        logger.debug(f"PowerShell DHCP ({adapter}): rc={rc} out={out} err={err}")
        if rc == 0 and "OK" in out.splitlines():
            _run_command(f'ipconfig /renew "{adapter}"', timeout=25)
            return
        m = re.search(r"ERROR=(.*)", out)
        ps_error = (m.group(1) if m else (err or out or "error desconocido")).strip()
        logger.warning(f"PowerShell falló ({ps_error}); usando netsh")

    name = _netsh_name(adapter)
    _run_command(f"netsh interface ipv4 delete route prefix=0.0.0.0/0 interface={name}", timeout=10)
    out, err, rc = _run_command(f"netsh interface ipv4 set address name={name} source=dhcp", timeout=20)
    _run_command(f"netsh interface ipv4 set dnsservers name={name} source=dhcp", timeout=10)
    # rc != 0 también ocurre si DHCP ya estaba activo: se decide verificando el estado
    if _win_read_config(adapter)["dhcp"] is not True:
        raise IPConfigError(f"netsh: {(out or err).strip()}" + (f"\nPowerShell: {ps_error}" if ps_error else ""))
    _run_command(f'ipconfig /renew "{adapter}"', timeout=25)

def _linux_apply_static(adapter, ip, mask, gateway, dns_list, extra=()):
    cidr = mask_to_cidr(mask)
    if shutil.which("nmcli") and _nm_device_managed(adapter):
        con = _nm_connection_for(adapter, create=True)
        out, err, rc = _run_command(
            ["nmcli", "connection", "modify", con,
             "ipv4.method", "manual",
             "ipv4.addresses", ",".join([f"{ip}/{cidr}"] + [f"{a}/{mask_to_cidr(m)}" for a, m in extra]),
             "ipv4.gateway", gateway or "", "ipv4.dns", ",".join(dns_list)], timeout=10)
        if rc != 0:
            raise IPConfigError(f"nmcli: {(err or out).strip()}")
        out, err, rc = _run_command(["nmcli", "connection", "up", con], timeout=30)
        if rc != 0:
            raise IPConfigError(f"nmcli: {(err or out).strip()}")
        return

    if not is_admin():
        raise IPConfigError(tr("ipc.nm_unmanaged"))
    if not shutil.which("ip"):
        raise IPConfigError(tr("ipc.no_nmcli_ip"))
    _run_command(["ip", "addr", "flush", "dev", adapter], timeout=5)
    _, err, rc = _run_command(["ip", "addr", "add", f"{ip}/{cidr}", "dev", adapter], timeout=5)
    if rc != 0:
        raise IPConfigError(f"ip addr add: {err.strip()}")
    for a, m in extra:
        _run_command(["ip", "addr", "add", f"{a}/{mask_to_cidr(m)}", "dev", adapter], timeout=5)
    _run_command(["ip", "link", "set", "dev", adapter, "up"], timeout=5)
    if gateway:
        _run_command(["ip", "route", "replace", "default", "via", gateway, "dev", adapter], timeout=5)
    if dns_list and shutil.which("resolvectl"):
        _run_command(["resolvectl", "dns", adapter] + dns_list, timeout=5)

def _linux_apply_dhcp(adapter):
    if shutil.which("nmcli") and _nm_device_managed(adapter):
        con = _nm_connection_for(adapter, create=True)
        out, err, rc = _run_command(
            ["nmcli", "connection", "modify", con, "ipv4.method", "auto",
             "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""], timeout=10)
        if rc != 0:
            raise IPConfigError(f"nmcli: {(err or out).strip()}")
        # 'up' puede fallar si no hay servidor DHCP; el método ya quedó en automático
        _run_command(["nmcli", "connection", "up", con], timeout=45)
        return

    if not is_admin():
        raise IPConfigError(tr("ipc.nm_unmanaged"))
    _run_command(["ip", "addr", "flush", "dev", adapter], timeout=5)
    _run_command(["ip", "link", "set", "dev", adapter, "up"], timeout=5)
    if shutil.which("dhclient"):
        _run_command(["dhclient", "-r", adapter], timeout=10)
        _run_command(["dhclient", "-1", adapter], timeout=30)
    elif shutil.which("dhcpcd"):
        _run_command(["dhcpcd", "-n", adapter], timeout=30)
    elif shutil.which("udhcpc"):
        _run_command(["udhcpc", "-i", adapter, "-n", "-q"], timeout=30)
    else:
        raise IPConfigError(tr("ipc.no_dhcp_client"))

# ── macOS ──────────────────────────────────────────────────────────────
def _mac_service_for(adapter: str) -> str:
    """en0 -> 'Wi-Fi' / 'Ethernet' (networksetup trabaja con nombres de servicio)."""
    out = run_command(["networksetup", "-listnetworkserviceorder"], timeout=4)
    service = None
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"^\((?:\d+|\*)\)\s+(.+)$", line)
        if m:
            service = m.group(1).strip()
            continue
        m = re.search(r"Device:\s*([^)\s]+)", line)
        if m and m.group(1) == adapter and service:
            return service
    return adapter

def _mac_check(out, err, rc, what):
    text = (out + err).strip()
    if rc != 0 or "error" in text.lower():
        raise IPConfigError(f"networksetup {what}: {text or rc}")

def _mac_apply_static(adapter, ip, mask, gateway, dns_list, extra=()):
    svc = _mac_service_for(adapter)
    args = ["networksetup", "-setmanual", svc, ip, mask] + ([gateway] if gateway else [])
    _mac_check(*_run_command(args, timeout=10), "-setmanual")
    for a, m in extra:   # networksetup no admite varias IPs: alias (no persiste al reiniciar)
        _run_command(["ifconfig", adapter, "alias", a, m], timeout=5)
    if dns_list:
        _run_command(["networksetup", "-setdnsservers", svc] + dns_list, timeout=10)

def _mac_apply_dhcp(adapter):
    svc = _mac_service_for(adapter)
    _mac_check(*_run_command(["networksetup", "-setdhcp", svc], timeout=10), "-setdhcp")
    _run_command(["networksetup", "-setdnsservers", svc, "Empty"], timeout=10)

# ── API pública ────────────────────────────────────────────────────────
def _verify_static(adapter: str, ip: str, timeout: float = 8.0) -> Tuple[bool, str]:
    deadline = time.time() + timeout
    while True:
        if any(a == ip for a, _ in _live_ipv4(adapter)):
            return True, ""
        if IS_WINDOWS:
            cfg = _win_read_config(adapter)
            if cfg["dhcp"] is False and any(a == ip for a, _ in cfg["ips"]):
                if _link_is_up(adapter) is False:
                    return True, WARNING_PREFIX + tr("ipc.warn_unplugged_saved")
                if time.time() >= deadline:
                    return True, ""
        if time.time() >= deadline:
            if _link_is_up(adapter) is False:
                return True, WARNING_PREFIX + tr("ipc.warn_unplugged_unverified")
            return False, tr("ipc.ip_missing", ip=ip)
        time.sleep(0.7)

def _wait_dhcp_lease(adapter: str, timeout: float) -> Tuple[Optional[str], Optional[str]]:
    """Espera una IP que no sea APIPA. Devuelve (ip, mask) o (None, ip_actual)."""
    deadline = time.time() + timeout
    current = None
    while True:
        live = _live_ipv4(adapter)
        if live and not live[0][0].startswith("169.254."):
            return live[0][0], live[0][1]
        current = live[0][0] if live else None
        if time.time() >= deadline or _link_is_up(adapter) is False:
            return None, current
        time.sleep(1)

def set_static_ip(adapter, ip, mask, gateway, dns=None, extra_ips=None, _rollback=True):
    """Aplica IP estática (más IPs adicionales opcionales) y la verifica.
    Devuelve (ok, mensaje). Si falla, intenta restaurar la configuración previa."""
    try:
        ip, mask, gateway, dns_list = _validate_static(ip, mask, gateway, dns)
        extra = _parse_extra_ips(extra_ips, mask, ip)
    except ValueError as e:
        return False, str(e)
    if IS_WINDOWS and not is_admin():
        return False, tr("ipc.need_admin")

    before = _snapshot_config(adapter) if _rollback else None
    logger.info(f"IP estática en '{adapter}': {ip}/{mask_to_cidr(mask)} gw={gateway or '-'} dns={dns_list}")
    try:
        if IS_WINDOWS:
            _win_apply_static(adapter, ip, mask, gateway, dns_list, extra)
        elif IS_MACOS:
            _mac_apply_static(adapter, ip, mask, gateway, dns_list, extra)
        else:
            _linux_apply_static(adapter, ip, mask, gateway, dns_list, extra)
        ok, detail = _verify_static(adapter, ip)
        if not ok:
            raise IPConfigError(detail)
    except IPConfigError as e:
        logger.error(f"Fallo IP estática en '{adapter}': {e}")
        return False, str(e) + _rollback_config(adapter, before)
    except Exception as e:
        logger.exception("Excepción en set_static_ip")
        return False, tr("ipc.exception", detail=e) + _rollback_config(adapter, before)

    msg = tr("ipc.static_ok", adapter=adapter, ip=f"{ip}/{mask_to_cidr(mask)}", mask=mask,
             gw=gateway or tr("common.none"))
    if dns_list:
        msg += f"\nDNS: {', '.join(dns_list)}"
    if extra:
        present = {a for a, _ in _configured_ipv4(adapter)}
        msg += "\n" + tr("lbl.extra_ips") + ": " + ", ".join(f"{a}/{mask_to_cidr(m)}" for a, m in extra)
        missing = [a for a, _ in extra if a not in present]
        if missing and not detail:
            detail = WARNING_PREFIX + tr("ipc.warn_extra_unverified", ips=", ".join(missing))
    if detail:
        msg += f"\n\n{detail}"
    return True, msg

def set_dhcp_ip(adapter, _rollback=True, wait_lease=15):
    """Pasa el adaptador a DHCP (IP y DNS automáticos), elimina IPs/gateways manuales
    y espera la concesión. Devuelve (ok, mensaje)."""
    if IS_WINDOWS and not is_admin():
        return False, tr("ipc.need_admin")

    before = _snapshot_config(adapter) if _rollback else None
    logger.info(f"DHCP en '{adapter}'")
    try:
        if IS_WINDOWS:
            _win_apply_dhcp(adapter)
            if _win_read_config(adapter)["dhcp"] is not True:
                raise IPConfigError(tr("ipc.dhcp_not_enabled"))
        elif IS_MACOS:
            _mac_apply_dhcp(adapter)
        else:
            _linux_apply_dhcp(adapter)
    except IPConfigError as e:
        logger.error(f"Fallo DHCP en '{adapter}': {e}")
        return False, str(e) + _rollback_config(adapter, before)
    except Exception as e:
        logger.exception("Excepción en set_dhcp_ip")
        return False, tr("ipc.exception", detail=e) + _rollback_config(adapter, before)

    # El modo automático ya quedó aplicado: desde aquí solo se informa el resultado
    lease_ip, mask_or_current = _wait_dhcp_lease(adapter, wait_lease)
    if lease_ip:
        gw = get_ip_info(adapter)[2]
        return True, tr("ipc.dhcp_ok", adapter=adapter, ip=f"{lease_ip}/{mask_to_cidr(mask_or_current)}", gw=gw)
    if _link_is_up(adapter) is False:
        return True, WARNING_PREFIX + tr("ipc.dhcp_unplugged", adapter=adapter)
    return True, WARNING_PREFIX + tr("ipc.dhcp_no_server", adapter=adapter, ip=mask_or_current or tr("common.none"))

def add_secondary_ip(adapter, ip, mask):
    """Agrega una IP sin tocar la configuración actual (útil para hablar con un equipo de
    otra red sin perder la red de la oficina). Con DHCP activo, Windows 10 (2004+) y 11 lo
    permiten activando 'dhcpstaticipcoexistence'. Devuelve (ok, mensaje)."""
    try:
        ip = str(ip).strip()
        ipaddress.IPv4Address(ip)
        mask = _normalize_mask(mask)
    except ValueError as e:
        return False, str(e)
    except Exception:
        return False, tr("ipc.invalid_ip", ip=ip)
    if IS_WINDOWS and not is_admin():
        return False, tr("ipc.need_admin")
    if any(a == ip for a, _ in _configured_ipv4(adapter)):
        return True, tr("ipc.already", ip=ip, adapter=adapter)
    prefix = mask_to_cidr(mask)
    try:
        if IS_WINDOWS:
            name = _netsh_name(adapter)
            if _win_read_config(adapter)["dhcp"]:
                out, err, rc = _run_command(
                    f"netsh interface ipv4 set interface {name} dhcpstaticipcoexistence=enabled", timeout=10)
                if rc != 0:
                    raise IPConfigError(tr("ipc.no_coexistence") + f"\n\nnetsh: {(out or err).strip()}")
            idx = _adapter_index(adapter)
            done = False
            if idx is not None and _win_has_netcmdlets():
                out, err, rc = _run_powershell(
                    f"$ErrorActionPreference = 'Stop'\ntry {{\n"
                    f"  New-NetIPAddress -InterfaceIndex {idx} -AddressFamily IPv4 -IPAddress {_ps_quote(ip)} "
                    f"-PrefixLength {prefix} -SkipAsSource $true | Out-Null\n  Write-Output 'OK'\n"
                    f"}} catch {{ Write-Output ('ERROR=' + $_.Exception.Message); exit 1 }}\n", timeout=20)
                done = rc == 0 and "OK" in out.splitlines()
            if not done:
                out, err, rc = _run_command(
                    f"netsh interface ipv4 add address name={name} address={ip} mask={mask}", timeout=10)
                if rc != 0:
                    raise IPConfigError(f"netsh: {(out or err).strip()}")
        elif IS_MACOS:
            _mac_check(*_run_command(["ifconfig", adapter, "alias", ip, mask], timeout=5), "alias")
        else:
            con = _nm_connection_for(adapter) if shutil.which("nmcli") and _nm_device_managed(adapter) else None
            if con:
                out, err, rc = _run_command(["nmcli", "connection", "modify", con, "+ipv4.addresses", f"{ip}/{prefix}"], timeout=10)
                if rc != 0:
                    raise IPConfigError(f"nmcli: {(err or out).strip()}")
                _run_command(["nmcli", "device", "reapply", adapter], timeout=20)
            else:
                if not is_admin():
                    raise IPConfigError(tr("ipc.need_root"))
                _, err, rc = _run_command(["ip", "addr", "add", f"{ip}/{prefix}", "dev", adapter], timeout=5)
                if rc != 0:
                    raise IPConfigError(f"ip addr add: {err.strip()}")
    except IPConfigError as e:
        return False, str(e)

    ok, detail = _verify_static(adapter, ip, timeout=6)
    if not ok:
        return False, detail
    return True, tr("ipc.secondary_ok", ip=f"{ip}/{prefix}", adapter=adapter) + (f"\n\n{detail}" if detail else "")

def remove_secondary_ip(adapter, ip):
    """Quita una IP concreta del adaptador. Devuelve (ok, mensaje)."""
    if IS_WINDOWS and not is_admin():
        return False, tr("ipc.need_admin")
    ip = str(ip).strip()
    try:
        if IS_WINDOWS:
            idx = _adapter_index(adapter)
            if idx is not None and _win_has_netcmdlets():
                _run_powershell(
                    "foreach ($store in 'ActiveStore', 'PersistentStore') {\n"
                    f"  Get-NetIPAddress -InterfaceIndex {idx} -IPAddress {_ps_quote(ip)} -PolicyStore $store "
                    "-ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue\n}\n",
                    timeout=20)
            if any(a == ip for a, _ in _configured_ipv4(adapter)):
                _run_command(f"netsh interface ipv4 delete address name={_netsh_name(adapter)} address={ip}", timeout=10)
        elif IS_MACOS:
            _run_command(["ifconfig", adapter, "-alias", ip], timeout=5)
        else:
            con = _nm_connection_for(adapter) if shutil.which("nmcli") and _nm_device_managed(adapter) else None
            live = dict(_live_ipv4(adapter))
            prefix = mask_to_cidr(live.get(ip, "24"))
            if con:
                _run_command(["nmcli", "connection", "modify", con, "-ipv4.addresses", f"{ip}/{prefix}"], timeout=10)
                _run_command(["nmcli", "device", "reapply", adapter], timeout=20)
            else:
                _run_command(["ip", "addr", "del", f"{ip}/{prefix}", "dev", adapter], timeout=5)
    except Exception as e:
        return False, str(e)
    time.sleep(1)
    if any(a == ip for a, _ in _configured_ipv4(adapter)):
        return False, tr("ipc.remove_failed", ip=ip, adapter=adapter)
    return True, tr("ipc.remove_ok", ip=ip, adapter=adapter)
