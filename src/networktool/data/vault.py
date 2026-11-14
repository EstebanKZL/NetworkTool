"""Bóveda de credenciales (usuario + contraseña) cifrada, para no volver a tipear nada.

Cifrado:
  · Windows: DPAPI (CryptProtectData) atado a la cuenta de Windows del usuario — otra cuenta u
    otra PC no puede descifrar el archivo. Es el mismo mecanismo que usa MobaXterm en
    "User registry" y los navegadores.
  · Linux / macOS: Fernet (cryptography) con una clave aleatoria guardada en la carpeta de datos
    con permisos 600.

Cada credencial recuerda en qué equipos se usó (host:puerto) para ofrecerla sola la próxima vez.
"""

import base64
import ctypes
import os
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from networktool.common import IS_WINDOWS, _read_json, _write_json, logger, nettool_data_dir

POLICIES = ("ask", "always", "never")
_ENTROPY = b"NetworkTool.vault.v1"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  CIFRADO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if IS_WINDOWS:
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data: bytes) -> _BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        b = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        b._buf = buf   # mantener viva la memoria
        return b

    def _dpapi(data: bytes, protect: bool) -> bytes:
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        src, ent, out = _blob(data), _blob(_ENTROPY), _BLOB()
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        args = (ctypes.byref(src), "NetworkTool", ctypes.byref(ent), None, None, 0x01, ctypes.byref(out)) \
            if protect else (ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x01, ctypes.byref(out))
        if not fn(*args):
            raise OSError(f"DPAPI error {ctypes.GetLastError()}")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(out.pbData)

    def encrypt(plain: str) -> str:
        return "dpapi:" + base64.b64encode(_dpapi(plain.encode("utf-8"), True)).decode()

    def decrypt(token: str) -> str:
        if not token.startswith("dpapi:"):
            raise ValueError("formato desconocido")
        return _dpapi(base64.b64decode(token[6:]), False).decode("utf-8")
else:
    def _fernet():
        from cryptography.fernet import Fernet
        key_path = nettool_data_dir() / "vault.key"
        if not key_path.exists():
            key_path.write_bytes(Fernet.generate_key())
            os.chmod(key_path, 0o600)
        return Fernet(key_path.read_bytes())

    def encrypt(plain: str) -> str:
        return "fernet:" + _fernet().encrypt(plain.encode("utf-8")).decode()

    def decrypt(token: str) -> str:
        if not token.startswith("fernet:"):
            raise ValueError("formato desconocido")
        return _fernet().decrypt(token[7:].encode()).decode("utf-8")


def _host_key(host: str, port) -> str:
    return f"{str(host).strip().lower()}:{int(port)}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  BÓVEDA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class CredentialVault:
    """Credenciales en vault.json. La contraseña nunca se escribe en claro."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (nettool_data_dir() / "vault.json")
        data = _read_json(self.path, {})
        data = data if isinstance(data, dict) else {}
        self.policy = data.get("policy") if data.get("policy") in POLICIES else "ask"
        self.items: List[Dict] = [c for c in data.get("credentials", []) if isinstance(c, dict) and c.get("id")]

    def save(self) -> None:
        try:
            _write_json(self.path, {"networktool_vault": 1, "policy": self.policy, "credentials": self.items})
            if not IS_WINDOWS:
                os.chmod(self.path, 0o600)
        except Exception as e:
            logger.error(f"No se pudo guardar la bóveda: {e}")

    # ── Consultas ──────────────────────────────────────────────────────
    def get(self, cid: str) -> Optional[Dict]:
        return next((c for c in self.items if c["id"] == cid), None)

    def password(self, cred: Dict) -> str:
        """Contraseña descifrada ('' si no hay o no se puede descifrar en esta cuenta)."""
        token = cred.get("secret") or ""
        if not token:
            return ""
        try:
            return decrypt(token)
        except Exception as e:
            logger.warning(f"No se pudo descifrar la credencial '{cred.get('name')}': {e}")
            return ""

    def for_host(self, host: str, port, username: str = "") -> List[Dict]:
        """Credenciales ya usadas en ese equipo (las más recientes primero)."""
        key = _host_key(host, port)
        hits = [c for c in self.items if key in c.get("hosts", {})]
        if username:
            hits = [c for c in hits if c.get("username") == username] or hits
        return sorted(hits, key=lambda c: c["hosts"][key], reverse=True)

    def by_username(self, username: str) -> List[Dict]:
        return [c for c in self.items if c.get("username") == username]

    def label(self, cred: Dict) -> str:
        return f"{cred.get('name') or cred.get('username')}  ({cred.get('username')})"

    # ── Altas y cambios ────────────────────────────────────────────────
    def upsert(self, name: str, username: str, password: str, cid: Optional[str] = None,
               keep_password: bool = False) -> Dict:
        cred = self.get(cid) if cid else None
        if cred is None:
            cred = {"id": uuid.uuid4().hex, "hosts": {}, "created": time.strftime("%Y-%m-%d %H:%M:%S")}
            self.items.append(cred)
        cred["name"] = (name or username).strip()
        cred["username"] = username.strip()
        if not keep_password:
            cred["secret"] = encrypt(password) if password else ""
        self.save()
        return cred

    def remember(self, host: str, port, username: str, password: str, name: str = "") -> Dict:
        """Guarda (o actualiza) la credencial usada con éxito y la asocia al equipo."""
        cred = next((c for c in self.by_username(username) if self.password(c) == password), None)
        if cred is None:
            cred = self.upsert(name or username, username, password)
        cred.setdefault("hosts", {})[_host_key(host, port)] = time.time()
        self.save()
        return cred

    def touch(self, cid: str, host: str, port) -> None:
        cred = self.get(cid)
        if cred is not None:
            cred.setdefault("hosts", {})[_host_key(host, port)] = time.time()
            self.save()

    def delete(self, cid: str) -> None:
        self.items = [c for c in self.items if c["id"] != cid]
        self.save()

    def clear(self) -> None:
        self.items = []
        self.save()


_vault = None


def vault() -> CredentialVault:
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
