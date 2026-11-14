"""Inventario persistente de equipos y escaneos (SQLite)."""

import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from networktool.common import UNKNOWN, _normalize_mac, _now_str, nettool_data_dir

def device_key(ip: str, mac: Optional[str], shared: bool = False) -> str:
    """Identidad de un equipo: su MAC (sobrevive a cambios de IP) o, si no se conoce, su IP.
    Si la misma MAC responde con varias IPs a la vez (cámara/NVR con dos IPs, router con
    proxy ARP), cada IP es un equipo distinto: 'MAC@IP'."""
    norm = _normalize_mac(mac) if mac and mac not in (UNKNOWN, "", "N/A") else None
    if norm:
        return f"{norm}@{ip}" if shared else norm
    return f"ip:{ip}"

def shared_macs(results: List[Dict]) -> set:
    """MACs que aparecen con más de una IP en el mismo escaneo."""
    seen: Dict[str, set] = {}
    for d in results:
        mac = _normalize_mac(d.get("mac"))
        if mac:
            seen.setdefault(mac, set()).add(d["ip"])
    return {m for m, ips in seen.items() if len(ips) > 1}

class Inventory:
    """Inventario de equipos vistos (por MAC), su historial de IPs, alias/notas y el
    registro de cada escaneo para poder comparar contra el anterior."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS devices (
        key TEXT PRIMARY KEY, mac TEXT, ip TEXT, hostname TEXT, vendor TEXT, dev TEXT, ports TEXT,
        network TEXT, first_seen TEXT, last_seen TEXT, times_seen INTEGER DEFAULT 0,
        alias TEXT DEFAULT '', notes TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS ip_history (
        key TEXT, ip TEXT, first_seen TEXT, last_seen TEXT, PRIMARY KEY (key, ip)
    );
    CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT, finished TEXT,
        adapter TEXT, network TEXT, total INTEGER
    );
    CREATE TABLE IF NOT EXISTS scan_hosts (
        scan_id INTEGER, key TEXT, ip TEXT, mac TEXT, hostname TEXT, vendor TEXT, dev TEXT, ports TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices(ip);
    CREATE INDEX IF NOT EXISTS idx_scan_hosts_scan ON scan_hosts(scan_id);
    CREATE INDEX IF NOT EXISTS idx_scans_network ON scans(network);
    """

    def __init__(self, path: Optional[Path] = None):
        import sqlite3
        self.path = path or (nettool_data_dir() / "inventory.db")
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(self.SCHEMA)
            self.db.commit()

    def close(self):
        with self.lock:
            try: self.db.close()
            except Exception: pass

    # ── equipos ──
    def _existing_key(self, ip: str, mac: Optional[str]) -> Optional[str]:
        """Clave ya guardada para este equipo (llamar con self.lock tomado)."""
        for key in (device_key(ip, mac, True), device_key(ip, mac)):
            if self.db.execute("SELECT 1 FROM devices WHERE key=?", (key,)).fetchone():
                return key
        return None

    def upsert_device(self, data: Dict, network: str = "", shared: bool = False) -> Dict:
        ip, mac = data.get("ip", ""), data.get("mac", UNKNOWN)
        now = _now_str()
        with self.lock:
            key = device_key(ip, mac, True) if shared else (self._existing_key(ip, mac) or device_key(ip, mac))
            cur = self.db.execute("SELECT * FROM devices WHERE key=?", (key,)).fetchone()
            if cur is None and not key.startswith("ip:"):
                # El equipo estaba registrado por IP (sin MAC): se conserva su alias/notas
                old = self.db.execute("SELECT * FROM devices WHERE key=?", (f"ip:{ip}",)).fetchone()
                if old is not None:
                    self.db.execute("UPDATE devices SET key=?, mac=? WHERE key=?", (key, mac, old["key"]))
                    self.db.execute("UPDATE ip_history SET key=? WHERE key=?", (key, old["key"]))
                    cur = self.db.execute("SELECT * FROM devices WHERE key=?", (key,)).fetchone()
            def keep(field, value):
                bad = (None, "", UNKNOWN, "N/A", "Checking...", "Analizando...")
                return value if value not in bad else (cur[field] if cur is not None else value)
            fields = {
                "mac": keep("mac", mac), "ip": ip, "hostname": keep("hostname", data.get("host")),
                "vendor": keep("vendor", data.get("vendor")), "dev": keep("dev", data.get("dev")),
                "ports": data.get("ports", "") if data.get("dev") not in (None, "Analizando...") else (cur["ports"] if cur is not None else ""),
                "network": network or (cur["network"] if cur is not None else ""),
            }
            if cur is None:
                self.db.execute(
                    "INSERT INTO devices (key, mac, ip, hostname, vendor, dev, ports, network, first_seen, last_seen, times_seen) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                    (key, fields["mac"], ip, fields["hostname"], fields["vendor"], fields["dev"], fields["ports"],
                     fields["network"], now, now))
            else:
                self.db.execute(
                    "UPDATE devices SET mac=?, ip=?, hostname=?, vendor=?, dev=?, ports=?, network=?, last_seen=? WHERE key=?",
                    (fields["mac"], ip, fields["hostname"], fields["vendor"], fields["dev"], fields["ports"],
                     fields["network"], now, key))
            self._touch_ip(key, ip, now)
            self.db.commit()
            row = self.db.execute("SELECT * FROM devices WHERE key=?", (key,)).fetchone()
        return dict(row)

    def _touch_ip(self, key, ip, now):
        self.db.execute(
            "INSERT INTO ip_history (key, ip, first_seen, last_seen) VALUES (?,?,?,?) "
            "ON CONFLICT(key, ip) DO UPDATE SET last_seen=excluded.last_seen", (key, ip, now, now))

    def touch(self, ip: str, mac: Optional[str]) -> None:
        """Monitor: el equipo respondió de nuevo."""
        now = _now_str()
        with self.lock:
            key = self._existing_key(ip, mac)
            if key is None:
                return
            self.db.execute("UPDATE devices SET last_seen=?, ip=? WHERE key=?", (now, ip, key))
            self._touch_ip(key, ip, now)
            self.db.commit()

    def get_device(self, ip: str, mac: Optional[str]) -> Optional[Dict]:
        with self.lock:
            key = self._existing_key(ip, mac)
            row = self.db.execute("SELECT * FROM devices WHERE key=?", (key,)).fetchone() if key else None
            if row is None and (not mac or mac == UNKNOWN):
                row = self.db.execute("SELECT * FROM devices WHERE ip=? ORDER BY last_seen DESC", (ip,)).fetchone()
        return dict(row) if row else None

    def set_meta(self, key: str, alias: str, notes: str) -> None:
        with self.lock:
            self.db.execute("UPDATE devices SET alias=?, notes=? WHERE key=?", (alias.strip(), notes.strip(), key))
            self.db.commit()

    def ensure_device(self, data: Dict, network: str = "", shared: bool = False) -> Dict:
        return self.get_device(data["ip"], data.get("mac")) or self.upsert_device(data, network, shared)

    def all_devices(self, search: str = "") -> List[Dict]:
        q = "SELECT * FROM devices"
        args: Tuple = ()
        if search:
            like = f"%{search}%"
            q += " WHERE ip LIKE ? OR mac LIKE ? OR alias LIKE ? OR notes LIKE ? OR vendor LIKE ? OR hostname LIKE ? OR dev LIKE ?"
            args = (like,) * 7
        q += " ORDER BY last_seen DESC"
        with self.lock:
            return [dict(r) for r in self.db.execute(q, args).fetchall()]

    def ip_history(self, key: str) -> List[Dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT * FROM ip_history WHERE key=? ORDER BY last_seen DESC", (key,)).fetchall()]

    def scan_count_for(self, key: str) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(DISTINCT scan_id) FROM scan_hosts WHERE key=?", (key,)).fetchone()[0]

    def delete_device(self, key: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM devices WHERE key=?", (key,))
            self.db.execute("DELETE FROM ip_history WHERE key=?", (key,))
            self.db.commit()

    # ── escaneos ──
    def record_scan(self, adapter: str, network: str, started: str, results: List[Dict]) -> int:
        shared = shared_macs(results)
        with self.lock:
            cur = self.db.execute("INSERT INTO scans (started, finished, adapter, network, total) VALUES (?,?,?,?,?)",
                                  (started, _now_str(), adapter, network, len(results)))
            scan_id = cur.lastrowid
            self.db.executemany(
                "INSERT INTO scan_hosts (scan_id, key, ip, mac, hostname, vendor, dev, ports) VALUES (?,?,?,?,?,?,?,?)",
                [(scan_id, device_key(d["ip"], d.get("mac"), _normalize_mac(d.get("mac")) in shared), d["ip"], d.get("mac", ""), d.get("host", ""),
                  d.get("vendor", ""), d.get("dev", ""), d.get("ports", "")) for d in results])
            # Los escaneos de más de 200 pasadas atrás por red se descartan
            old = [r[0] for r in self.db.execute(
                "SELECT id FROM scans WHERE network=? ORDER BY id DESC LIMIT -1 OFFSET 200", (network,)).fetchall()]
            if old:
                marks = ",".join("?" * len(old))
                self.db.execute(f"DELETE FROM scan_hosts WHERE scan_id IN ({marks})", old)
                self.db.execute(f"DELETE FROM scans WHERE id IN ({marks})", old)
            self.db.commit()
        return scan_id

    def scans(self, limit: int = 200) -> List[Dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def get_scan(self, scan_id: int) -> Optional[Dict]:
        with self.lock:
            row = self.db.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        return dict(row) if row else None

    def scan_hosts(self, scan_id: int) -> List[Dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM scan_hosts WHERE scan_id=?", (scan_id,)).fetchall()]

    def previous_scan(self, network: str, before_id: int) -> Optional[Dict]:
        with self.lock:
            row = self.db.execute("SELECT * FROM scans WHERE network=? AND id<? ORDER BY id DESC LIMIT 1",
                                  (network, before_id)).fetchone()
        return dict(row) if row else None

    def compare_scans(self, old_id: int, new_id: int) -> Dict:
        """Equipos nuevos, desaparecidos y con IP cambiada entre dos escaneos."""
        old = {h["key"]: h for h in self.scan_hosts(old_id)}
        new = {h["key"]: h for h in self.scan_hosts(new_id)}
        return {
            "old_scan": self.get_scan(old_id), "new_scan": self.get_scan(new_id),
            "new": [new[k] for k in new if k not in old],
            "missing": [old[k] for k in old if k not in new],
            "ip_changed": [(old[k], new[k]) for k in new if k in old and old[k]["ip"] != new[k]["ip"]],
        }

    def alias_for_key(self, key: str) -> str:
        with self.lock:
            row = self.db.execute("SELECT alias FROM devices WHERE key=?", (key,)).fetchone()
        return (row["alias"] or "") if row else ""
