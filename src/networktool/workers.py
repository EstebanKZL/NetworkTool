"""Hilos de trabajo (QThread): configuración IP, escaneos y herramientas."""

import re
import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Dict, List, Optional

from networktool.common import ALL_PORTS, IS_WINDOWS, UNKNOWN, logger
from networktool.i18n import tr
from networktool.net.discovery import (
    _ping_once, _tcp_probe, _win_send_arp,
    get_hostname_enhanced, get_mac, read_arp_table,
)
from networktool.net.ipconfig import (
    _snapshot_config, add_secondary_ip, remove_secondary_ip, set_dhcp_ip, set_static_ip,
)
from networktool.net.services import (
    check_ntp, classify_device, detect_service, mac_vendor, scan_ports_advanced,
)
from networktool.qt_compat import QThread, Signal
from networktool.system import _CONSOLE_ENCODING, _hidden_startupinfo
from networktool.tools import ping_latency

# Fabricante todavía no resuelto (se muestra en la tabla hasta que llega la respuesta)
VENDOR_PENDING = tr("vendor.pending")

# -----------------------------
# HILOS DE ESCANEO Y CONFIG
# -----------------------------
class IPConfigThread(QThread):
    finished = Signal(bool, str, str)

    def __init__(self, mode, adapter, ip=None, mask=None, gateway=None, dns=None, extra_ips=None):
        super().__init__()
        self.mode = mode
        self.adapter = adapter
        self.ip = ip
        self.mask = mask
        self.gateway = gateway
        self.dns = dns
        self.extra_ips = extra_ips
        self.before = None   # configuración previa, para el historial "volver a la anterior"

    def run(self):
        try:
            self.before = _snapshot_config(self.adapter)
        except Exception:
            self.before = None
        if self.mode == "static":
            success, msg = set_static_ip(self.adapter, self.ip, self.mask, self.gateway, self.dns, self.extra_ips)
        elif self.mode == "add_ip":
            success, msg = add_secondary_ip(self.adapter, self.ip, self.mask)
        elif self.mode == "remove_ip":
            success, msg = remove_secondary_ip(self.adapter, self.ip)
        else:
            success, msg = set_dhcp_ip(self.adapter)
        self.finished.emit(success, msg, self.mode)

class SingleIPScannerThread(QThread):
    progress = Signal(int)
    port_found = Signal(int)
    finished_scan = Signal(dict)

    def __init__(self, ip, ports: List[int], workers: int = 200, timeout: float = 0.3):
        super().__init__()
        self.ip = ip
        self.ports = list(ports)
        self.workers = max(1, workers)
        self.timeout = timeout
        self.canceled_flag = False
        self.lock = threading.Lock()
        self.open_ports = []
        self.completed = 0
        self.total = len(self.ports)
        self.executor = None

    def cancel(self):
        with self.lock: self.canceled_flag = True
        if self.executor:
            try: self.executor.shutdown(wait=False, cancel_futures=True)
            except: self.executor.shutdown(wait=False)

    def run(self):
        def check_port(p):
            if self.canceled_flag: return
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(self.timeout)
                    if s.connect_ex((self.ip, p)) == 0:
                        with self.lock: self.open_ports.append(p)
                        self.port_found.emit(p)
            except Exception: pass
            finally:
                with self.lock:
                    self.completed += 1
                    if self.completed % 15 == 0 or self.completed == self.total:
                        self.progress.emit(self.completed)

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            self.executor = executor
            for p in self.ports:
                if self.canceled_flag: break
                executor.submit(check_port, p)

        self.open_ports.sort()
        services = {}
        for p in self.open_ports: services[p] = detect_service(self.ip, p)

        if check_ntp(self.ip):
            if 123 not in self.open_ports:
                self.open_ports.append(123); self.open_ports.sort()
                services[123] = {"name": "NTP", "details": "NTP Server (UDP)"}

        mac = get_mac(self.ip)
        hostname, method = get_hostname_enhanced(self.ip)

        device, special_services = classify_device(self.ip, self.open_ports, services)

        self.finished_scan.emit({
            "ip": self.ip, "host": hostname, "host_method": method, "mac": mac,
            "vendor": mac_vendor(mac), "ports": ",".join(map(str, self.open_ports)),
            "services": services, "dev": device, "status": "Online",
            "special_services": special_services
        })

class ScannerThread(QThread):
    """Escaneo en 3 fases:
    1. Descubrimiento: ARP (SendARP de Windows) + ping/TCP y
       lectura de la tabla ARP del sistema. Cada equipo aparece apenas responde.
    2. Análisis: puertos, servicios y tipo de dispositivo, en una cola aparte para no
       frenar el descubrimiento.
    3. Confirmación: nuevo barrido ARP de los que no respondieron (equipos lentos),
       para no tener que escanear dos veces."""
    found = Signal(dict)
    updated = Signal(dict)
    seen = Signal(str, str)        # monitor: un equipo ya conocido respondió (ip, mac)
    sweep_done = Signal(list)      # IPs que respondieron en esta pasada
    progress = Signal(int, int)
    phase = Signal(str)
    completed = Signal()
    canceled = Signal()

    def __init__(self, hosts: List[str], on_link: bool = True, max_workers: int = 40, known_ips=None,
                 ports: Optional[List[int]] = None, port_timeout: float = 0.3):
        super().__init__()
        self.ports = list(ports or ALL_PORTS)
        self.port_timeout = port_timeout
        self.hosts = list(hosts)
        self.known_ips = set(known_ips or ())
        self._host_set = set(self.hosts)
        self.on_link = on_link
        self.max_workers = max_workers
        self.canceled_flag = False
        self.lock = threading.Lock()
        self._discovered: Dict[str, str] = {}
        self._done = 0
        self._total = len(self.hosts)
        self._executors = []
        self._enrich_pool = None

    def cancel(self):
        with self.lock: self.canceled_flag = True
        for ex in list(self._executors):
            try: ex.shutdown(wait=False, cancel_futures=True)
            except TypeError: ex.shutdown(wait=False)
            except Exception: pass

    def _is_canceled(self) -> bool:
        return self.canceled_flag

    def _tick(self):
        with self.lock:
            self._done += 1
            done, total = self._done, self._total
        if not self.canceled_flag:
            self.progress.emit(done, total)

    def _register(self, ip: str, mac: Optional[str], via: str) -> None:
        if ip not in self._host_set:
            return
        with self.lock:
            if self.canceled_flag or ip in self._discovered:
                return
            self._discovered[ip] = mac or UNKNOWN
            if ip in self.known_ips:
                known = True
            else:
                known = False
                self._total += 1   # su análisis cuenta como una tarea más
        if known:
            # Monitor: equipo ya listado, no se vuelve a analizar
            self.seen.emit(ip, mac or "")
            return
        self.found.emit({
            "ip": ip, "host": "N/A", "host_method": "", "mac": mac or UNKNOWN,
            "vendor": VENDOR_PENDING, "ports": "", "services": {}, "dev": tr("dev.analyzing"),
            "status": "Online", "special_services": [], "found_by": via,
            "is_new": bool(self.known_ips),
        })
        try:
            self._enrich_pool.submit(self._enrich, ip, mac or UNKNOWN, via)
        except RuntimeError:
            pass   # pool cerrado por cancelación

    def _enrich(self, ip: str, mac: str, via: str) -> None:
        try:
            if self.canceled_flag: return
            ports, services = scan_ports_advanced(ip, self.ports, self.port_timeout)
            if self.canceled_flag: return
            if 123 not in ports and check_ntp(ip):
                ports.append(123); ports.sort()
                services[123] = {"name": "NTP", "details": "NTP Server (UDP)"}
            if mac == UNKNOWN:
                mac = get_mac(ip)
            hostname, method = get_hostname_enhanced(ip)
            device, special_services = classify_device(ip, ports, services)
            if self.canceled_flag: return
            self.updated.emit({
                "ip": ip, "host": hostname, "host_method": method, "mac": mac,
                "vendor": VENDOR_PENDING, "ports": ",".join(map(str, ports)),
                "services": services, "dev": device, "status": "Online",
                "special_services": special_services, "found_by": via,
            })
        except Exception as e:
            logger.error(f"Error analizando {ip}: {e}")
        finally:
            self._tick()

    def _probe(self, ip: str, use_sendarp: bool) -> None:
        try:
            if self.canceled_flag or ip in self._discovered:
                return
            if use_sendarp:
                # SendARP ya reintenta 3 veces (~4 s); si no responde a ARP en la red
                # local, tampoco respondería a ping ni TCP.
                mac = _win_send_arp(ip)
                if mac:
                    self._register(ip, mac, "ARP")
                return
            if not self.on_link and _tcp_probe(ip):
                self._register(ip, None, "TCP"); return
            # En la red local el ping también obliga al SO a resolver ARP: aunque el
            # equipo bloquee ICMP, su MAC queda en la tabla ARP que se lee después.
            if _ping_once(ip, 1000):
                self._register(ip, None, "Ping"); return
            if self.on_link and not use_sendarp and _tcp_probe(ip, timeout=0.8):
                self._register(ip, None, "TCP")
        except Exception as e:
            logger.debug(f"probe {ip}: {e}")
        finally:
            self._tick()

    def _collect_arp_table(self) -> None:
        for ip, mac in read_arp_table().items():
            if ip in self._host_set and ip not in self._discovered:
                self._register(ip, mac, tr("found.arp_table"))
            elif ip in self._discovered and self._discovered[ip] == UNKNOWN:
                self._discovered[ip] = mac

    def run(self):
        use_sendarp = self.on_link and IS_WINDOWS
        # SendARP solo espera (no consume CPU): un hilo por dirección resuelve una /24 en ~4 s.
        # Ping lanza un proceso por sondeo, así que ahí se limita a 128.
        discover_workers = min(256, max(64, len(self.hosts))) if use_sendarp else 128
        self._enrich_pool = ThreadPoolExecutor(max_workers=self.max_workers)
        discover_pool = ThreadPoolExecutor(max_workers=discover_workers)
        self._executors = [discover_pool, self._enrich_pool]
        try:
            # Fase 1: SendARP / ping / TCP
            if not self.canceled_flag:
                self.phase.emit(tr("phase.probe"))
                futures =[discover_pool.submit(self._probe, ip, use_sendarp) for ip in self.hosts]
                wait(futures)

            if self.on_link and not self.canceled_flag:
                self._collect_arp_table()

            # Fase 3: confirmación de los que no respondieron
            missing = [ip for ip in self.hosts if ip not in self._discovered]
            if self.on_link and missing and not self.canceled_flag:
                self.phase.emit(tr("phase.confirm", n=len(missing)))
                time.sleep(1.0)
                if IS_WINDOWS:
                    def confirm(ip):
                        mac = None if self.canceled_flag else _win_send_arp(ip)
                        if mac: self._register(ip, mac, tr("found.arp_confirm"))
                    wait([discover_pool.submit(confirm, ip) for ip in missing])
                if not self.canceled_flag:
                    self._collect_arp_table()

            if not self.canceled_flag:
                self.phase.emit(tr("phase.analyze", n=len(self._discovered)))
            self._enrich_pool.shutdown(wait=True)
        except Exception as e:
            logger.error(f"Error en escaneo: {e}")
        finally:
            for ex in self._executors:
                try: ex.shutdown(wait=False)
                except Exception: pass

        if not self.canceled_flag:
            self.sweep_done.emit(list(self._discovered))
        if self.canceled_flag: self.canceled.emit()
        else: self.completed.emit()

class FuncWorker(QThread):
    """Ejecuta una función en segundo plano y devuelve (ok, resultado)."""
    done = Signal(bool, object)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.done.emit(True, self.fn(*self.args))
        except Exception as e:
            self.done.emit(False, str(e))

class PingWorker(QThread):
    sample = Signal(float)   # ms, o -1 si se perdió

    def __init__(self, target: str, interval_ms: int, count: int = 0):
        super().__init__()
        self.target, self.interval_ms, self.count = target, interval_ms, count
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        sent = 0
        while not self._stop and (self.count <= 0 or sent < self.count):
            t0 = time.time()
            ms = ping_latency(self.target, timeout_ms=max(500, min(self.interval_ms, 2000)))
            sent += 1
            if self._stop:
                break
            self.sample.emit(-1.0 if ms is None else ms)
            wait_s = self.interval_ms / 1000 - (time.time() - t0)
            while wait_s > 0 and not self._stop:
                time.sleep(min(0.1, wait_s)); wait_s -= 0.1

class TraceWorker(QThread):
    hop = Signal(int, str, str)   # salto, IP ('*' si no respondió), tiempos
    done = Signal(str)

    def __init__(self, target: str, resolve: bool = False, max_hops: int = 30):
        super().__init__()
        self.target, self.resolve, self.max_hops = target, resolve, max_hops
        self.proc = None

    def stop(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass

    def run(self):
        if IS_WINDOWS:
            cmd = ["tracert", "-w", "800", "-h", str(self.max_hops)] + ([] if self.resolve else ["-d"]) + [self.target]
        else:
            tool = "traceroute" if shutil.which("traceroute") else "tracepath"
            cmd = [tool, "-m", str(self.max_hops)] + ([] if self.resolve or tool == "tracepath" else ["-n"]) + [self.target]
        kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True,
                  "encoding": _CONSOLE_ENCODING, "errors": "replace"}
        if IS_WINDOWS:
            kwargs.update(startupinfo=_hidden_startupinfo(), creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.proc = subprocess.Popen(cmd, **kwargs)
        except Exception as e:
            self.done.emit(tr("trace.exec_failed", cmd=cmd[0], detail=e))
            return
        for line in self.proc.stdout:
            m = re.match(r"^\s*(\d+)\s+(.*)$", line.rstrip())
            if not m:
                continue
            rest = m.group(2)
            ips = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", rest)
            times = re.findall(r"(<?\d+(?:[.,]\d+)?)\s*ms", rest)
            name = ""
            if self.resolve:
                nm = re.search(r"([A-Za-z0-9][\w.-]*\.[A-Za-z]{2,})\s*\[?\(?\d", rest)
                name = f"  ({nm.group(1)})" if nm else ""
            self.hop.emit(int(m.group(1)), (ips[-1] + name) if ips else "*",
                          "  ".join(f"{t} ms" for t in times) if times else tr("trace.no_reply"))
        self.proc.wait()
        self.done.emit(tr("trace.done"))
