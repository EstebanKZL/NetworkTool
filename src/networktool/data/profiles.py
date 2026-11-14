"""Perfiles de IP editables e historial de configuraciones."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from networktool.common import _read_json, _write_json, logger, nettool_data_dir

# -----------------------------
# PERFILES DE IP E HISTORIAL
# -----------------------------
# Sin perfiles de fábrica: cada usuario crea los suyos desde "Perfiles".
DEFAULT_IP_PROFILES: List[Dict] = []
HISTORY_LIMIT = 20

def _clean_profile(p: Dict) -> Dict:
    extra = p.get("extra_ips") or []
    if isinstance(extra, str):
        extra = [x for x in re.split(r"[\s,;]+", extra) if x]
    return {
        "name": str(p.get("name", "")).strip() or str(p.get("ip", "")).strip(),
        "group": str(p.get("group", "") or "").strip(),
        "ip": str(p.get("ip", "")).strip(),
        "mask": str(p.get("mask", "") or "255.255.255.0").strip(),
        "gateway": str(p.get("gateway", "") or "").strip(),
        "dns": str(p.get("dns", "") or "").strip(),
        "extra_ips": [str(x).strip() for x in extra if str(x).strip()],
    }

class ProfileStore:
    """Perfiles de IP editables y el historial de configuraciones aplicadas
    (para volver a la anterior con un clic). Se guardan en profiles.json."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (nettool_data_dir() / "profiles.json")
        data = _read_json(self.path, {})
        profiles = data.get("profiles") if isinstance(data, dict) else None
        self.profiles: List[Dict] = ([_clean_profile(p) for p in profiles if isinstance(p, dict)]
                                     if isinstance(profiles, list) else [dict(p) for p in DEFAULT_IP_PROFILES])
        history = data.get("history") if isinstance(data, dict) else None
        self.history: List[Dict] = history if isinstance(history, list) else []

    def save(self) -> None:
        try:
            _write_json(self.path, {"profiles": self.profiles, "history": self.history[-HISTORY_LIMIT:]})
        except Exception as e:
            logger.error(f"No se pudieron guardar los perfiles: {e}")

    def push_history(self, adapter: str, snapshot: Dict) -> None:
        if not snapshot or (not snapshot.get("dhcp") and not snapshot.get("ip")):
            return
        entry = dict(snapshot, adapter=adapter, time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.history.append(entry)
        self.history = self.history[-HISTORY_LIMIT:]
        self.save()

    def last_for(self, adapter: str) -> Optional[Dict]:
        return next((h for h in reversed(self.history) if h.get("adapter") == adapter), None)

    def pop_last_for(self, adapter: str) -> Optional[Dict]:
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i].get("adapter") == adapter:
                entry = self.history.pop(i)
                self.save()
                return entry
        return None

    def export_to(self, path: str) -> None:
        _write_json(Path(path), {"networktool_profiles": 1, "profiles": self.profiles})

    def import_from(self, path: str, replace: bool = False) -> int:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = data.get("profiles", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("El archivo no contiene una lista de perfiles")
        new = [_clean_profile(p) for p in items if isinstance(p, dict) and p.get("ip")]
        if replace:
            self.profiles = new
        else:
            names = {(p["group"], p["name"]) for p in self.profiles}
            self.profiles += [p for p in new if (p["group"], p["name"]) not in names]
        self.save()
        return len(new)
