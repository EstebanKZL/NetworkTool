"""Preferencias del usuario (settings.json en la carpeta de datos).

Todo lo que antes estaba fijo en el código y conviene ajustar sin recompilar:
puertos analizados por equipo, puertos del re-escaneo, hilos y tiempos de espera.
"""

from typing import Dict, List

from networktool.common import ALL_PORTS, _read_json, _write_json, logger, nettool_data_dir

MAX_PORTS = 65535

DEFAULTS: Dict = {
    # Puertos que se prueban en cada equipo durante el escaneo de red
    "scan_ports": "",                # vacío = lista recomendada (ALL_PORTS)
    # Puertos que propone "Re-escanear" en la ventana de detalle de un equipo
    "detail_ports": "1-1024",
    "scan_workers": 40,              # equipos analizados en paralelo
    "port_timeout_ms": 300,          # espera por puerto (TCP connect)
    "detail_workers": 200,           # puertos en paralelo en el re-escaneo
    "monitor_interval": 30,
}


def format_port_spec(ports: List[int]) -> str:
    """[21, 22, 23, 80] → '21-23,80'."""
    ports = sorted(set(ports))
    parts, i = [], 0
    while i < len(ports):
        j = i
        while j + 1 < len(ports) and ports[j + 1] == ports[j] + 1:
            j += 1
        parts.append(str(ports[i]) if i == j else f"{ports[i]}-{ports[j]}")
        i = j + 1
    return ",".join(parts)


DEFAULT_SCAN_PORTS = format_port_spec(ALL_PORTS)


def parse_port_spec(spec: str) -> List[int]:
    """'22, 80-90 443' → [22, 80, ..., 90, 443]. Lanza ValueError si algo no es válido."""
    ports = set()
    for token in str(spec or "").replace(";", ",").replace(" ", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a, _, b = token.partition("-")
            if not (a.strip().isdigit() and b.strip().isdigit()):
                raise ValueError(token)
            lo, hi = sorted((int(a), int(b)))
        elif token.isdigit():
            lo = hi = int(token)
        else:
            raise ValueError(token)
        if lo < 1 or hi > MAX_PORTS:
            raise ValueError(token)
        ports.update(range(lo, hi + 1))
    if not ports:
        raise ValueError(spec)
    return sorted(ports)


class Settings:
    def __init__(self, path=None):
        self.path = path or (nettool_data_dir() / "settings.json")
        data = _read_json(self.path, {})
        self.data = dict(DEFAULTS)
        if isinstance(data, dict):
            self.data.update({k: v for k, v in data.items() if k in DEFAULTS})

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value) -> None:
        self.data[key] = value

    def save(self) -> None:
        try:
            _write_json(self.path, self.data)
        except Exception as e:
            logger.error(f"No se pudieron guardar las preferencias: {e}")

    # ── Atajos con validación ───────────────────────────────────────────
    def scan_ports(self) -> List[int]:
        try:
            return parse_port_spec(self.get("scan_ports") or DEFAULT_SCAN_PORTS)
        except ValueError:
            return list(ALL_PORTS)

    def detail_ports(self) -> List[int]:
        try:
            return parse_port_spec(self.get("detail_ports"))
        except ValueError:
            return list(range(1, 1025))

    def int_value(self, key: str, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(self.get(key))))
        except (TypeError, ValueError):
            return DEFAULTS[key]


_settings = None


def settings() -> Settings:
    """Instancia compartida (se crea al primer uso)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
