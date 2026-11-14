"""Explorador de archivos integrado: SFTP, FTP y el sistema de archivos de WSL.

Todas las operaciones de red corren en un único hilo (_OpWorker) con una cola, así la
interfaz nunca se congela y el cliente FTP/SFTP no se usa desde dos hilos a la vez.

Como MobaXterm: carpeta ".." para subir, íconos por tipo, abrir / abrir con / editar (los
cambios guardados se suben solos al servidor), copiar la ruta o pegarla en la terminal (clic
del medio), permisos, propiedades, borrar carpetas completas y subir o bajar carpetas enteras.
"""

import errno
import ftplib
import io
import os
import posixpath
import queue
import stat
import subprocess
import tempfile
from datetime import datetime
from typing import Callable, Dict, List, Optional

from networktool.common import FTP_TIMEOUT, IS_MACOS, IS_WINDOWS, logger
from networktool.i18n import tr
from networktool.qt_compat import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QFileDialog, QFileSystemWatcher, QGridLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QStackedWidget, QTimer, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget, Qt, Signal, _exec, _exec_menu,
)
from networktool.ui.terminal import _Backend, is_auth_error, open_ssh_client
from networktool.ui.theme import (
    SP, attach_menu, field_label, icon, make_badge, make_button, make_empty_state,
    mono_font, remote_file_icon, set_badge, set_help,
)

EDIT_LIMIT = 10 * 1024 * 1024        # editor integrado: hasta 10 MB
COL_NAME, COL_SIZE, COL_MTIME, COL_OWNER, COL_GROUP, COL_PERMS = range(6)


def human_size(n: Optional[int]) -> str:
    if n is None:
        return ""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return str(n)


def friendly_error(exc: Exception) -> str:
    """Mensaje entendible: el servidor SFTP suele responder solo "Failure"."""
    code = getattr(exc, "errno", None)
    if isinstance(exc, PermissionError) or code in (errno.EACCES, errno.EPERM):
        return tr("fb.err_permission")
    if isinstance(exc, FileNotFoundError) or code == errno.ENOENT:
        return tr("fb.err_not_found")
    if isinstance(exc, FileExistsError) or code == errno.EEXIST:
        return tr("fb.err_exists")
    text = str(exc) or exc.__class__.__name__
    if text.strip().lower() == "failure":
        return tr("fb.err_failure")
    return text


def _entry(name, is_dir, size=None, mtime=None, mode=0, owner="", group="", is_link=False, perms="") -> Dict:
    return {"name": name, "is_dir": is_dir, "is_link": is_link, "size": None if is_dir else size,
            "mtime": mtime, "mode": mode or 0, "owner": owner, "group": group,
            "perms": perms or (stat.filemode(mode) if mode else "")}


# ══════════════════════════════════════════════════════════════════════════
#  SISTEMAS DE ARCHIVOS
# ══════════════════════════════════════════════════════════════════════════
class _RemoteFS:
    """Interfaz común SFTP / FTP / local. Rutas siempre con "/"."""
    can_chmod = True

    def connect(self) -> str: ...            # devuelve la carpeta inicial
    def listdir(self, path: str) -> List[Dict]: ...
    def stat(self, path: str) -> Dict: ...
    def download(self, remote: str, local: str, progress: Callable[[int], None]) -> None: ...
    def upload(self, local: str, remote: str, progress: Callable[[int], None]) -> None: ...
    def mkdir(self, path: str) -> None: ...
    def remove(self, path: str, is_dir: bool) -> None: ...
    def rename(self, old: str, new: str) -> None: ...
    def chmod(self, path: str, mode: int) -> None: ...
    def touch(self, path: str) -> None: ...
    def close(self) -> None: ...

    # ── Operaciones recursivas (genéricas) ─────────────────────────────
    def remove_tree(self, path: str) -> None:
        for e in self.listdir(path):
            child = posixpath.join(path, e["name"])
            if e["is_dir"] and not e["is_link"]:
                self.remove_tree(child)
            else:
                self.remove(child, False)
        self.remove(path, True)

    def chmod_tree(self, path: str, mode: int) -> None:
        self.chmod(path, mode)
        for e in self.listdir(path):
            child = posixpath.join(path, e["name"])
            if e["is_dir"] and not e["is_link"]:
                self.chmod_tree(child, mode)
            else:
                self.chmod(child, mode)

    def download_tree(self, remote: str, local: str, progress: Callable[[int], None]) -> int:
        os.makedirs(local, exist_ok=True)
        count = 0
        for e in self.listdir(remote):
            src, dst = posixpath.join(remote, e["name"]), os.path.join(local, e["name"])
            if e["is_dir"]:
                count += self.download_tree(src, dst, progress)
            else:
                self.download(src, dst, progress)
                count += 1
        return count

    def upload_tree(self, local: str, remote: str, progress: Callable[[int], None]) -> int:
        try:
            self.mkdir(remote)
        except Exception:
            pass                                 # ya existe
        count = 0
        for name in sorted(os.listdir(local)):
            src, dst = os.path.join(local, name), posixpath.join(remote, name)
            if os.path.isdir(src):
                count += self.upload_tree(src, dst, progress)
            else:
                self.upload(src, dst, progress)
                count += 1
        return count


def _parse_longname(longname: str):
    """'-rw-r--r--  1 pi  pi  5452 Nov  3 16:14 ownfoil.db' → ('pi', 'pi')."""
    parts = (longname or "").split()
    return (parts[2], parts[3]) if len(parts) >= 4 else ("", "")


class SFTPFS(_RemoteFS):
    def __init__(self, cred: Dict, key_asker: Optional[_Backend]):
        self.cred, self.asker = cred, key_asker
        self.client = None
        self.sftp = None
        self.shared = False
        self.start_path = ""

    @classmethod
    def from_client(cls, client, start_path: str = "") -> "SFTPFS":
        fs = cls({}, None)
        fs.client, fs.shared, fs.start_path = client, True, start_path
        return fs

    def open_on_client(self) -> str:
        self.sftp = self.client.open_sftp()
        return self.sftp.normalize(self.start_path or ".")

    def close_sftp_only(self) -> None:
        try:
            if self.sftp:
                self.sftp.close()
        except Exception:
            pass

    def connect(self) -> str:
        self.client = open_ssh_client(self.asker, self.cred)
        self.sftp = self.client.open_sftp()
        start = self.cred.get("remote_path") or "."
        return self.sftp.normalize(start)

    def listdir(self, path: str) -> List[Dict]:
        out = []
        for a in self.sftp.listdir_attr(path):
            mode = a.st_mode or 0
            is_link = stat.S_ISLNK(mode)
            is_dir = stat.S_ISDIR(mode)
            if is_link:
                try:
                    is_dir = stat.S_ISDIR(self.sftp.stat(posixpath.join(path, a.filename)).st_mode)
                except Exception:
                    pass
            owner, group = _parse_longname(getattr(a, "longname", ""))
            out.append(_entry(a.filename, is_dir, a.st_size, a.st_mtime, mode,
                              owner or str(a.st_uid if a.st_uid is not None else ""),
                              group or str(a.st_gid if a.st_gid is not None else ""), is_link))
        return out

    def stat(self, path: str) -> Dict:
        a = self.sftp.lstat(path)
        mode = a.st_mode or 0
        return _entry(posixpath.basename(path) or path, stat.S_ISDIR(mode), a.st_size, a.st_mtime, mode,
                      str(a.st_uid if a.st_uid is not None else ""), str(a.st_gid if a.st_gid is not None else ""),
                      stat.S_ISLNK(mode))

    def download(self, remote, local, progress):
        self.sftp.get(remote, local, callback=lambda done, total: progress(int(done * 100 / total) if total else 100))

    def upload(self, local, remote, progress):
        self.sftp.put(local, remote, callback=lambda done, total: progress(int(done * 100 / total) if total else 100))

    def mkdir(self, path):
        self.sftp.mkdir(path)

    def remove(self, path, is_dir):
        if is_dir:
            self.sftp.rmdir(path)
        else:
            self.sftp.remove(path)

    def rename(self, old, new):
        self.sftp.rename(old, new)

    def chmod(self, path, mode):
        self.sftp.chmod(path, mode)

    def touch(self, path):
        with self.sftp.open(path, "w"):
            pass

    def close(self):
        if self.shared:                      # la conexión es de la terminal: solo el canal SFTP
            self.close_sftp_only()
            return
        for obj in (self.sftp, self.client):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass


class FTPFS(_RemoteFS):
    def __init__(self, cred: Dict):
        self.cred = cred
        self.ftp: Optional[ftplib.FTP] = None

    def connect(self) -> str:
        self.ftp = ftplib.FTP(timeout=FTP_TIMEOUT)
        self.ftp.encoding = self.cred.get("encoding") or "utf-8"   # Python 3.8: sin parámetro encoding=
        self.ftp.connect(self.cred["host"], int(self.cred["port"]))
        self.ftp.login(self.cred.get("username") or "anonymous", self.cred.get("password") or "")
        self.ftp.set_pasv(self.cred.get("ftp_passive", True))
        if self.cred.get("remote_path"):
            self.ftp.cwd(self.cred["remote_path"])
        return self.ftp.pwd()

    def listdir(self, path: str) -> List[Dict]:
        try:
            out = []
            for name, facts in self.ftp.mlsd(path, facts=["type", "size", "modify", "unix.mode",
                                                          "unix.owner", "unix.group"]):
                if name in (".", "..") or facts.get("type") in ("cdir", "pdir"):
                    continue
                is_dir = facts.get("type") == "dir"
                mtime = None
                if facts.get("modify"):
                    try:
                        mtime = datetime.strptime(facts["modify"][:14], "%Y%m%d%H%M%S").timestamp()
                    except ValueError:
                        pass
                mode = facts.get("unix.mode")
                mode = (int(mode, 8) | (stat.S_IFDIR if is_dir else stat.S_IFREG)) if mode else 0
                out.append(_entry(name, is_dir, int(facts.get("size") or 0), mtime, mode,
                                  facts.get("unix.owner", ""), facts.get("unix.group", "")))
            return out
        except ftplib.error_perm:
            return self._list_fallback(path)

    def _list_fallback(self, path: str) -> List[Dict]:
        """Servidores sin MLSD: interpreta LIST en formato Unix (drwxr-xr-x ... nombre)."""
        lines: List[str] = []
        self.ftp.retrlines(f"LIST {path}", lines.append)
        out = []
        for line in lines:
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            perms, name = parts[0], parts[8]
            is_link = perms.startswith("l")
            if " -> " in name:
                name = name.split(" -> ")[0]
            if name in (".", ".."):
                continue
            is_dir = perms.startswith("d") or is_link
            size = int(parts[4]) if parts[4].isdigit() and not is_dir else None
            out.append(_entry(name, is_dir, size, None, 0, parts[2], parts[3], is_link, perms))
        return out

    def stat(self, path: str) -> Dict:
        parent, name = posixpath.split(path.rstrip("/"))
        for e in self.listdir(parent or "/"):
            if e["name"] == name:
                return e
        raise FileNotFoundError(path)

    def download(self, remote, local, progress):
        total = 0
        try:
            total = self.ftp.size(remote) or 0
        except Exception:
            pass
        done = [0]
        with open(local, "wb") as f:
            def write(chunk):
                f.write(chunk)
                done[0] += len(chunk)
                if total:
                    progress(int(done[0] * 100 / total))
            self.ftp.retrbinary(f"RETR {remote}", write, blocksize=65536)
        progress(100)

    def upload(self, local, remote, progress):
        total = os.path.getsize(local) or 1
        done = [0]
        with open(local, "rb") as f:
            def sent(chunk):
                done[0] += len(chunk)
                progress(int(done[0] * 100 / total))
            self.ftp.storbinary(f"STOR {remote}", f, blocksize=65536, callback=sent)
        progress(100)

    def mkdir(self, path):
        self.ftp.mkd(path)

    def remove(self, path, is_dir):
        if is_dir:
            self.ftp.rmd(path)
        else:
            self.ftp.delete(path)

    def rename(self, old, new):
        self.ftp.rename(old, new)

    def chmod(self, path, mode):
        self.ftp.sendcmd(f"SITE CHMOD {mode & 0o7777:o} {path}")

    def touch(self, path):
        self.ftp.storbinary(f"STOR {path}", io.BytesIO(b""))

    def close(self):
        try:
            if self.ftp:
                self.ftp.quit()
        except Exception:
            try:
                self.ftp.close()
            except Exception:
                pass


class LocalFS(_RemoteFS):
    """Carpeta local con rutas estilo Linux: se usa para el sistema de archivos de WSL
    (\\\\wsl.localhost\\Distro) junto a la terminal de la distro."""
    can_chmod = not IS_WINDOWS

    def __init__(self, root: str, start: str = "/"):
        self.root = root.rstrip("\\/")
        self.start = start

    def _real(self, path: str) -> str:
        rel = path.lstrip("/").replace("/", os.sep)
        return os.path.join(self.root + os.sep, rel) if rel else self.root + os.sep

    def connect(self) -> str:
        if not os.path.isdir(self._real("/")):
            raise FileNotFoundError(self.root)
        if self.start == "~":
            homes = [d for d in self._safe_list("/home") if os.path.isdir(self._real(f"/home/{d}"))]
            return f"/home/{homes[0]}" if len(homes) == 1 else "/"
        return self.start or "/"

    def _safe_list(self, path):
        try:
            return os.listdir(self._real(path))
        except OSError:
            return []

    def listdir(self, path: str) -> List[Dict]:
        out = []
        with os.scandir(self._real(path)) as it:
            for d in it:
                try:
                    st = d.stat(follow_symlinks=False)
                    is_link = d.is_symlink()
                    is_dir = d.is_dir()
                except OSError:
                    continue
                out.append(_entry(d.name, is_dir, st.st_size, st.st_mtime, st.st_mode, "", "", is_link))
        return out

    def stat(self, path: str) -> Dict:
        st = os.lstat(self._real(path))
        return _entry(posixpath.basename(path) or path, stat.S_ISDIR(st.st_mode), st.st_size, st.st_mtime,
                      st.st_mode, "", "", stat.S_ISLNK(st.st_mode))

    @staticmethod
    def _copy(src: str, dst: str, progress: Callable[[int], None]) -> None:
        total = os.path.getsize(src) or 1
        done = 0
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            while True:
                chunk = fi.read(1024 * 1024)
                if not chunk:
                    break
                fo.write(chunk)
                done += len(chunk)
                progress(int(done * 100 / total))
        progress(100)

    def download(self, remote, local, progress):
        self._copy(self._real(remote), local, progress)

    def upload(self, local, remote, progress):
        self._copy(local, self._real(remote), progress)

    def mkdir(self, path):
        os.mkdir(self._real(path))

    def remove(self, path, is_dir):
        (os.rmdir if is_dir else os.remove)(self._real(path))

    def rename(self, old, new):
        os.rename(self._real(old), self._real(new))

    def chmod(self, path, mode):
        os.chmod(self._real(path), mode)

    def touch(self, path):
        open(self._real(path), "ab").close()

    def close(self):
        pass


# ══════════════════════════════════════════════════════════════════════════
#  HILO DE OPERACIONES
# ══════════════════════════════════════════════════════════════════════════
class _OpWorker(_Backend):
    """Ejecuta las operaciones de a una. done(op, ok, resultado)."""
    done = Signal(str, bool, object)
    progress = Signal(int)

    def __init__(self):
        super().__init__()
        self.jobs: "queue.Queue" = queue.Queue()
        self.last_exc: Optional[Exception] = None

    def submit(self, op: str, fn: Callable) -> None:
        self.jobs.put((op, fn))

    def run(self):
        while not self._stop:
            try:
                op, fn = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            if op == "__quit__":
                break
            try:
                self.done.emit(op, True, fn())
            except Exception as e:
                logger.debug(f"{op}: {e}")
                self.last_exc = e
                self.done.emit(op, False, friendly_error(e))

    def close(self) -> None:
        super().close()
        self.jobs.put(("__quit__", None))


# ══════════════════════════════════════════════════════════════════════════
#  LISTA: ARRASTRAR Y SOLTAR, CLIC DEL MEDIO, TECLAS
# ══════════════════════════════════════════════════════════════════════════
class _DropTree(QTreeWidget):
    files_dropped = Signal(list)      # archivos y carpetas locales
    middle_clicked = Signal(object)   # ítem bajo el clic del medio
    key_action = Signal(str)          # open | up | delete | rename | refresh | copy_path

    _KEYS = {Qt.Key_Return: "open", Qt.Key_Enter: "open", Qt.Key_Backspace: "up", Qt.Key_Delete: "delete",
             Qt.Key_F2: "rename", Qt.Key_F5: "refresh"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if os.path.exists(p)]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            item = self.itemAt(event.pos())
            if item is not None:
                self.middle_clicked.emit(item)
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier) if not isinstance(mods, int) else bool(mods & int(Qt.ControlModifier))
        if ctrl and event.key() == Qt.Key_C:
            self.key_action.emit("copy_path")
            return
        action = self._KEYS.get(event.key())
        if action:
            self.key_action.emit(action)
            return
        super().keyPressEvent(event)


class _SortItem(QTreeWidgetItem):
    """".." siempre arriba, después las carpetas; tamaño y fecha ordenan por valor."""
    def __lt__(self, other):
        tree = self.treeWidget()
        col = tree.sortColumn() if tree else 0
        asc = tree.header().sortIndicatorOrder() == Qt.AscendingOrder if tree else True
        a, b = self.data(0, Qt.UserRole) or {}, other.data(0, Qt.UserRole) or {}
        if a.get("up") or b.get("up"):
            return bool(a.get("up")) == asc
        if a.get("is_dir") != b.get("is_dir"):
            return a.get("is_dir", False) if asc else b.get("is_dir", False)
        if col == COL_SIZE:
            return (a.get("size") or 0) < (b.get("size") or 0)
        if col == COL_MTIME:
            return (a.get("mtime") or 0) < (b.get("mtime") or 0)
        return self.text(col).lower() < other.text(col).lower()


# ══════════════════════════════════════════════════════════════════════════
#  DIÁLOGOS: PERMISOS, PROPIEDADES, EDITOR
# ══════════════════════════════════════════════════════════════════════════
class _PermissionsDialog(QDialog):
    """chmod con casillas (propietario / grupo / otros × leer / escribir / ejecutar) y octal."""
    WHO = ("owner", "group", "others")
    WHAT = ((4, "read"), (2, "write"), (1, "exec"))

    def __init__(self, entry: Dict, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("fb.permissions"))
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        root.setSpacing(SP["md"])
        title = QLabel(entry["name"])
        title.setObjectName("lblTitle")
        root.addWidget(title)
        sub = QLabel(path)
        sub.setObjectName("lblSubtitle")
        sub.setWordWrap(True)
        root.addWidget(sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(SP["lg"])
        grid.setVerticalSpacing(SP["sm"])
        for c, (_, what) in enumerate(self.WHAT, start=1):
            grid.addWidget(field_label(tr(f"fb.perm_{what}")), 0, c, Qt.AlignCenter)
        self.checks = {}
        mode = entry.get("mode") or 0
        for r, who in enumerate(self.WHO, start=1):
            grid.addWidget(field_label(tr(f"fb.perm_{who}")), r, 0, Qt.AlignRight | Qt.AlignVCenter)
            shift = (2 - (r - 1)) * 3
            for c, (bit, what) in enumerate(self.WHAT, start=1):
                cb = QCheckBox()
                cb.setChecked(bool(mode & (bit << shift)))
                cb.setToolTip(f"{tr(f'fb.perm_{who}')} · {tr(f'fb.perm_{what}')}")
                cb.toggled.connect(self._sync_octal)
                grid.addWidget(cb, r, c, Qt.AlignCenter)
                self.checks[(shift, bit)] = cb
        root.addLayout(grid)

        row = QHBoxLayout()
        row.addWidget(field_label(tr("fb.octal")))
        self.octal = QLineEdit()
        self.octal.setMaxLength(4)
        self.octal.setFixedWidth(80)
        set_help(self.octal, "perm_octal")
        self.octal.textEdited.connect(self._from_octal)
        row.addWidget(self.octal)
        row.addStretch(1)
        root.addLayout(row)
        self.recursive = QCheckBox(tr("fb.perm_recursive"))
        set_help(self.recursive, "perm_recursive")
        self.recursive.setVisible(entry.get("is_dir", False))
        root.addWidget(self.recursive)
        self._special = mode & 0o7000
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(make_button(tr("common.cancel"), None, None, self.reject))
        btns.addWidget(make_button(tr("btn.apply"), "btnPrimary", "perm_apply", self.accept))
        root.addLayout(btns)
        self._sync_octal()

    def mode(self) -> int:
        m = self._special
        for (shift, bit), cb in self.checks.items():
            if cb.isChecked():
                m |= bit << shift
        return m

    def _sync_octal(self, *_):
        self.octal.setText(f"{self.mode():o}".rjust(3, "0"))

    def _from_octal(self, text: str):
        try:
            m = int(text, 8)
        except ValueError:
            return
        self._special = m & 0o7000
        for (shift, bit), cb in self.checks.items():
            cb.blockSignals(True)
            cb.setChecked(bool(m & (bit << shift)))
            cb.blockSignals(False)


class _PropertiesDialog(QDialog):
    def __init__(self, entry: Dict, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("fb.properties"))
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        root.setSpacing(SP["md"])
        title = QLabel(entry["name"])
        title.setObjectName("lblTitle")
        root.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(SP["md"])
        grid.setVerticalSpacing(SP["sm"])
        kind = tr("fb.type_link") if entry.get("is_link") else (tr("fb.type_dir") if entry["is_dir"] else tr("fb.type_file"))
        size = "" if entry["is_dir"] else f"{human_size(entry.get('size'))}  ({entry.get('size') or 0:,} B)".replace(",", ".")
        mtime = datetime.fromtimestamp(entry["mtime"]).strftime(tr("fmt.datetime")) if entry.get("mtime") else ""
        mode = entry.get("mode") or 0
        rows = [(tr("fb.path"), path), (tr("col.type"), kind), (tr("col.size"), size), (tr("col.modified"), mtime),
                (tr("col.owner"), entry.get("owner", "")), (tr("col.group"), entry.get("group", "")),
                (tr("col.perms"), f"{entry.get('perms', '')}   ({mode & 0o7777:o})" if mode else entry.get("perms", ""))]
        for r, (label, value) in enumerate(rows):
            grid.addWidget(field_label(label), r, 0, Qt.AlignRight | Qt.AlignVCenter)
            val = QLineEdit(str(value))
            val.setReadOnly(True)
            grid.addWidget(val, r, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(make_button(tr("common.close"), "btnPrimary", None, self.accept))
        root.addLayout(btns)


class TextEditorWindow(QWidget):
    """Editor integrado (como MobaTextEditor): guarda con Ctrl+S y el explorador sube el archivo."""
    save_requested = Signal(str, bytes)      # ruta remota, contenido

    def __init__(self, remote: str, data: bytes, host: str, parent=None):
        super().__init__(None)
        self.remote = remote
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setObjectName("page")
        self.setWindowTitle(f"{posixpath.basename(remote)} — {host}")
        self.resize(980, 680)
        if parent is not None and parent.window() is not None:
            self.setWindowIcon(parent.window().windowIcon())
        try:
            text, self.encoding = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, self.encoding = data.decode("latin-1"), "latin-1"
        self.crlf = "\r\n" in text
        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["md"], SP["lg"], SP["md"])
        root.setSpacing(SP["sm"])
        head = QHBoxLayout()
        lbl = QLabel(f"{host}:{remote}")
        lbl.setObjectName("lblHint")
        head.addWidget(lbl, 1)
        self.wrap = QCheckBox(tr("fb.word_wrap"))
        set_help(self.wrap, "word_wrap")
        self.wrap.toggled.connect(lambda on: self.edit.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if on else QPlainTextEdit.NoWrap))
        head.addWidget(self.wrap)
        self.btn_save = make_button(tr("btn.save"), "btnPrimary", "editor_save", self.save, shortcut="Ctrl+S")
        head.addWidget(self.btn_save)
        root.addLayout(head)
        self.edit = QPlainTextEdit()
        self.edit.setObjectName("logView")
        self.edit.setFont(mono_font(13))
        self.edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.edit.setPlainText(text.replace("\r\n", "\n"))
        self.edit.document().setModified(False)
        self.edit.document().modificationChanged.connect(self._update_title)
        self.edit.cursorPositionChanged.connect(self._update_pos)
        root.addWidget(self.edit, 1)
        self.pos_lbl = QLabel()
        self.pos_lbl.setObjectName("lblHint")
        root.addWidget(self.pos_lbl)
        self._update_pos()

    def _update_title(self, modified: bool) -> None:
        base = self.windowTitle().lstrip("* ")
        self.setWindowTitle(("* " if modified else "") + base)

    def _update_pos(self) -> None:
        c = self.edit.textCursor()
        self.pos_lbl.setText(tr("fb.editor_pos", line=c.blockNumber() + 1, col=c.positionInBlock() + 1,
                                enc=self.encoding.upper(), eol="CRLF" if self.crlf else "LF"))

    def keyPressEvent(self, event):
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier) if not isinstance(mods, int) else bool(mods & int(Qt.ControlModifier))
        if ctrl and event.key() == Qt.Key_S:
            self.save()
            return
        super().keyPressEvent(event)

    def save(self) -> None:
        text = self.edit.toPlainText()
        if self.crlf:
            text = text.replace("\n", "\r\n")
        try:
            data = text.encode(self.encoding)
        except UnicodeEncodeError:
            data, self.encoding = text.encode("utf-8"), "utf-8"
        self.save_requested.emit(self.remote, data)

    def mark_saved(self) -> None:
        self.edit.document().setModified(False)

    def closeEvent(self, event):
        if self.edit.document().isModified():
            answer = QMessageBox.question(self, tr("fb.editor_unsaved_title"),
                                          tr("fb.editor_unsaved", name=posixpath.basename(self.remote)),
                                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.Save:
                self.save()
        event.accept()


def _open_local(path: str, choose: bool = False) -> None:
    """Abre un archivo con el programa predeterminado o con el selector "Abrir con" del sistema."""
    if IS_WINDOWS:
        if choose:
            subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", path])
        else:
            os.startfile(path)  # noqa: S606 (archivo descargado por el usuario)
    elif IS_MACOS:
        subprocess.Popen(["open"] + (["-a", "TextEdit"] if choose else []) + [path])
    else:
        subprocess.Popen(["xdg-open", path])


# ══════════════════════════════════════════════════════════════════════════
#  PESTAÑA / PANEL DEL EXPLORADOR
# ══════════════════════════════════════════════════════════════════════════
class FileBrowserTab(QWidget):
    """Explorador SFTP / FTP / WSL. Como pestaña propia (con su conexión) o como panel lateral
    de una sesión SSH o WSL (embedded=True), compartiendo la conexión de la terminal."""
    state_changed = Signal(bool)
    auth_failed = Signal()            # usuario/contraseña rechazados: la ventana vuelve a pedirlos
    cd_requested = Signal(str)        # "Abrir en la terminal": cd a esta carpeta
    path_to_terminal = Signal(str)    # "Copiar ruta a la terminal" / clic del medio
    follow_toggled = Signal(bool)

    def __init__(self, session: Dict, cred: Dict, parent=None, embedded: bool = False):
        super().__init__(parent)
        self.session, self.cred = session, cred
        self.embedded = embedded
        self.fs: Optional[_RemoteFS] = None
        self.worker: Optional[_OpWorker] = None
        self.cwd = "/"
        self.home = "/"
        self.is_connected = False
        self.show_hidden = True
        self._busy = 0
        self._entries: List[Dict] = []
        self._opened: Dict[str, Dict] = {}       # archivo local abierto → {remote, auto}
        self._editors: Dict[str, TextEditorWindow] = {}
        self._pending_changes: set = set()
        self.setObjectName("page")
        self.host_label = cred.get("host") or session.get("name", "")

        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_local_changed)
        self._change_timer = QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.timeout.connect(self._ask_upload_changes)

        root = QVBoxLayout(self)
        root.setContentsMargins(SP["md"], SP["sm"], SP["md"] if not embedded else SP["sm"], SP["md"])
        root.setSpacing(SP["sm"])

        # Barra superior: estado + destino + reconectar/desconectar (solo como pestaña propia)
        top = QHBoxLayout()
        top.setSpacing(SP["sm"])
        self.badge = make_badge(tr("status.connecting"), "info")
        set_help(self.badge, "badge_session")
        if session.get("protocol") in ("wsl", "shell"):
            target = session.get("name", "")
        else:
            target = f"{cred.get('username') + '@' if cred.get('username') else ''}{cred.get('host', '')}:{cred.get('port', '')}"
        panel_title = tr("section.wsl_files") if session.get("protocol") == "wsl" else tr("section.sftp_panel")
        title = QLabel(panel_title.upper() if embedded else f"{session['protocol'].upper()}  ·  {target}")
        title.setObjectName("lblSection" if embedded else "lblHint")
        self.btn_reconnect = make_button(tr("btn.reconnect"), "btnConnect", "reconnect", self.connect_session)
        self.btn_disconnect = make_button(tr("btn.disconnect"), "btnDisconnect", "disconnect_session",
                                          self.disconnect_session)
        if embedded:
            top.addWidget(title)
            top.addStretch(1)
            top.addWidget(self.badge)
            self.btn_reconnect.hide()
            self.btn_disconnect.hide()
        else:
            top.addWidget(self.badge)
            top.addWidget(title)
            top.addStretch(1)
            top.addWidget(self.btn_reconnect)
            top.addWidget(self.btn_disconnect)
        root.addLayout(top)

        # Barra de ruta
        nav = QHBoxLayout()
        nav.setSpacing(SP["sm"])
        self.btn_up = make_button(tr("fb.up"), None, "fb_up", self.go_up, shortcut="Backspace")
        self.btn_home = make_button(tr("fb.home"), None, "fb_home", self.go_home)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("/")
        set_help(self.path_edit, "fb_path")
        self.path_edit.returnPressed.connect(lambda: self.list_dir(self.path_edit.text().strip() or "/"))
        self.btn_refresh = make_button(tr("fb.refresh"), None, "fb_refresh", lambda: self.list_dir(self.cwd),
                                       shortcut="F5")
        nav.addWidget(self.btn_up)
        nav.addWidget(self.btn_home)
        if embedded:
            nav.addStretch(1)
            nav.addWidget(self.btn_refresh)
            root.addLayout(nav)
            root.addWidget(self.path_edit)
        else:
            nav.addWidget(self.path_edit, 1)
            nav.addWidget(self.btn_refresh)
            root.addLayout(nav)

        # Lista
        self.tree = _DropTree()
        self.tree.setHeaderLabels([tr("col.name"), tr("col.size"), tr("col.modified"), tr("col.owner"),
                                   tr("col.group"), tr("col.perms")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(COL_NAME, Qt.AscendingOrder)
        self.tree.setUniformRowHeights(True)
        hh = self.tree.header()
        # El nombre nunca se achica hasta desaparecer: columnas a su contenido y la última estira;
        # si no entran, aparece la barra horizontal.
        hh.setStretchLastSection(True)
        hh.setMinimumSectionSize(48)
        for c in range(6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        hh.setContextMenuPolicy(Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._header_menu)
        hh.setToolTip(tr("tip.fb_columns"))
        for c in ((COL_OWNER, COL_GROUP, COL_PERMS) if embedded else ()):
            self.tree.setColumnHidden(c, True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.files_dropped.connect(self.upload_paths)
        self.tree.middle_clicked.connect(self._on_middle_click)
        self.tree.key_action.connect(self._on_key)
        self.tree.setStatusTip(tr("tip.fb_tree"))
        self.stack = QStackedWidget()
        self.empty = make_empty_state(tr("empty.folder"), "folder")
        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.empty)
        root.addWidget(self.stack, 1)

        # Acciones
        self.btn_mkdir = make_button(tr("fb.mkdir"), None, "fb_mkdir", self.make_dir)
        self.btn_rename = make_button(tr("fb.rename"), None, "fb_rename", self.rename_selected, shortcut="F2")
        self.btn_delete = make_button(tr("fb.delete"), "btnDanger", "fb_delete", self.delete_selected,
                                      shortcut="Supr")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("lblHint")
        self.status_lbl.setWordWrap(True)
        self.btn_download = make_button(tr("fb.download"), None, "fb_download", self.download_selected)
        self.btn_upload = make_button(tr("fb.upload"), "btnPrimary", "fb_upload", self.upload_dialog)
        self.chk_follow = QCheckBox(tr("lbl.follow_cwd"))
        set_help(self.chk_follow, "follow_cwd")
        self.chk_follow.toggled.connect(self.follow_toggled.emit)
        more = QPushButton(tr("btn.more"))
        more.setObjectName("btnSecondary")
        set_help(more, "fb_more")
        self.more_menu = QMenu(more)
        self.more_menu.aboutToShow.connect(self._fill_more_menu)
        attach_menu(more, self.more_menu)
        self.btn_more = more
        if embedded:
            for b in (self.btn_mkdir, self.btn_rename, self.btn_delete):
                b.hide()
            row = QHBoxLayout()
            row.setSpacing(SP["sm"])
            row.addWidget(more)
            row.addWidget(self.btn_download)
            row.addStretch(1)
            row.addWidget(self.btn_upload)
            root.addLayout(row)
            root.addWidget(self.progress)
            root.addWidget(self.status_lbl)
            root.addWidget(self.chk_follow)
            self.chk_follow.setVisible(session.get("protocol") != "wsl" or True)
        else:
            self.chk_follow.hide()
            actions = QHBoxLayout()
            actions.setSpacing(SP["sm"])
            for b in (more, self.btn_mkdir, self.btn_rename, self.btn_delete):
                actions.addWidget(b)
            actions.addWidget(self.status_lbl, 1)
            actions.addWidget(self.progress)
            actions.addWidget(self.btn_download)
            actions.addWidget(self.btn_upload)
            root.addLayout(actions)
        self._set_state(False, connecting=not embedded)

    # ── Conexión ───────────────────────────────────────────────────────
    def _new_worker(self) -> None:
        self._stop_worker()
        self.worker = _OpWorker()
        self.worker.done.connect(self._on_done)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.host_key.connect(self._ask_host_key)

    def connect_session(self) -> None:
        self._new_worker()
        self.fs = SFTPFS(self.cred, self.worker) if self.session["protocol"] == "sftp" else FTPFS(self.cred)
        self.worker.start()
        self._set_state(False, connecting=True)
        self._run("connect", self.fs.connect)

    def attach_client(self, client) -> None:
        """Panel de una sesión SSH: abre SFTP sobre la conexión ya autenticada de la terminal."""
        fs = SFTPFS.from_client(client, self.cred.get("remote_path") or "")
        self.attach_fs(fs, fs.open_on_client)

    def attach_fs(self, fs: _RemoteFS, opener: Optional[Callable] = None) -> None:
        self._new_worker()
        self.fs = fs
        self.worker.start()
        self._set_state(False, connecting=True)
        self._run("connect", opener or fs.connect)

    def detach(self) -> None:
        """La terminal se desconectó: el panel queda deshabilitado (la conexión es de la terminal)."""
        self._stop_worker(close_fs=False)
        self._set_state(False)

    def disconnect_session(self) -> None:
        self._stop_worker()
        self._set_state(False)

    def _stop_worker(self, close_fs: bool = True) -> None:
        if self.worker is not None:
            worker, fs = self.worker, self.fs
            self.worker = None
            self.fs = None
            try:
                worker.done.disconnect()
            except Exception:
                pass
            worker.close()
            worker.wait(1500)
            if fs is not None and close_fs:
                fs.close()
            elif fs is not None and hasattr(fs, "close_sftp_only"):
                fs.close_sftp_only()
        self._busy = 0

    def shutdown(self) -> None:
        for ed in list(self._editors.values()):
            try:
                ed.close()
            except RuntimeError:
                pass
        self._stop_worker()

    def _ask_host_key(self, host: str, fingerprint: str) -> None:
        answer = QMessageBox.question(self, tr("msg.hostkey_title"), tr("msg.hostkey", host=host, fp=fingerprint),
                                      QMessageBox.Yes | QMessageBox.No)
        if self.sender() is not None:
            self.sender().answer_host_key(answer == QMessageBox.Yes)

    def _set_state(self, connected: bool, connecting: bool = False) -> None:
        self.is_connected = connected
        if connecting:
            set_badge(self.badge, tr("status.connecting"), "info")
        elif connected:
            set_badge(self.badge, tr("status.connected"), "ok")
        else:
            set_badge(self.badge, tr("status.disconnected"), "neutral")
        for w in (self.btn_up, self.btn_home, self.path_edit, self.btn_refresh, self.tree, self.btn_mkdir,
                  self.btn_rename, self.btn_delete, self.btn_download, self.btn_upload, self.chk_follow,
                  self.btn_more):
            w.setEnabled(connected)
        self.btn_reconnect.setEnabled(not connected and not connecting)
        self.btn_disconnect.setEnabled(connected or connecting)
        self.state_changed.emit(connected)

    def go_to(self, path: str) -> None:
        """Lista una carpeta si cambió (lo usa "Seguir carpeta de la terminal")."""
        if self.is_connected and path and path != self.cwd:
            self.list_dir(path)

    # ── Cola de operaciones ────────────────────────────────────────────
    def _run(self, op: str, fn: Callable, status: str = "") -> None:
        if self.worker is None:
            return
        self._busy += 1
        if status:
            self.status_lbl.setText(status)
        self.worker.submit(op, fn)

    def _progress_cb(self) -> Callable[[int], None]:
        worker = self.worker
        return lambda pct: worker.progress.emit(max(0, min(100, pct))) if worker else None

    def _on_done(self, op: str, ok: bool, result) -> None:
        self._busy = max(0, self._busy - 1)
        kind, _, arg = op.partition(":")
        if kind == "connect":
            if ok:
                self._set_state(True)
                self.home = result or "/"
                self.list_dir(self.home)
            else:
                self._set_state(False)
                self.status_lbl.setText(tr("fb.error", detail=result))
                if self.worker is not None and is_auth_error(self.worker.last_exc):
                    self.auth_failed.emit()
                else:
                    QMessageBox.warning(self, tr("msg.connection_title"), tr("msg.connection_failed", detail=result))
            return
        if kind == "list":
            if ok:
                self._fill(arg, result)
            else:
                self.status_lbl.setText(tr("fb.error", detail=result))
                QMessageBox.warning(self, tr("msg.error_title"), tr("fb.list_failed", path=arg, detail=result))
            return
        if kind in ("download", "upload", "open"):
            self.progress.setVisible(self._busy > 0)
        if kind == "open":
            self._after_open(ok, result)
            return
        if kind == "batch":                      # varias operaciones: un único mensaje con los errores
            done, errors = result if ok else (0, [("", result)])
            what = arg
            if errors:
                lines = "\n".join(f"• {n}: {e}" if n else f"• {e}" for n, e in errors[:12])
                more = f"\n… (+{len(errors) - 12})" if len(errors) > 12 else ""
                self.status_lbl.setText(tr("fb.batch_partial", ok=done, failed=len(errors)))
                QMessageBox.warning(self, tr("msg.error_title"), tr(f"fb.batch_failed_{what}") + "\n\n" + lines + more)
            else:
                self.status_lbl.setText(tr(f"fb.batch_ok_{what}", n=done))
            if self._busy == 0 and what != "download":
                self.list_dir(self.cwd)
            return
        if kind == "save":
            ed = self._editors.get(arg)
            if ok:
                self.status_lbl.setText(tr("fb.uploaded", name=posixpath.basename(arg)))
                if ed is not None:
                    try:
                        ed.mark_saved()
                    except RuntimeError:
                        pass
                if posixpath.dirname(arg) == self.cwd and self._busy == 0:
                    self.list_dir(self.cwd)
            else:
                QMessageBox.warning(self, tr("msg.error_title"), tr("fb.save_failed", detail=result))
            return
        if ok:
            key = {"mkdir": "fb.created", "touch": "fb.created_file", "rename": "fb.renamed",
                   "chmod": "fb.chmod_ok", "upload": "fb.uploaded", "download": "fb.downloaded"}.get(kind, "")
            if key:
                self.status_lbl.setText(tr(key, name=arg))
            if kind == "props":
                _exec(_PropertiesDialog(result, arg, self))
            if kind in ("mkdir", "touch", "rename", "chmod", "upload") and self._busy == 0:
                self.list_dir(self.cwd)
        else:
            self.status_lbl.setText(tr("fb.error", detail=result))
            QMessageBox.warning(self, tr("msg.error_title"), tr("fb.op_failed", detail=result))

    # ── Navegación ─────────────────────────────────────────────────────
    def list_dir(self, path: str) -> None:
        if self.fs is None:
            return
        fs = self.fs
        path = posixpath.normpath(path) if path not in ("", "/") else "/"
        if not path.startswith("/") and not path.startswith("~"):
            path = posixpath.normpath(posixpath.join(self.cwd, path))
        self._run(f"list:{path}", lambda: fs.listdir(path), tr("fb.loading"))

    def _fill(self, path: str, entries: List[Dict]) -> None:
        self.cwd = path
        self._entries = entries
        self.path_edit.setText(path)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        if path != "/":
            up = _SortItem(["..", "", "", "", "", ""])
            up.setData(0, Qt.UserRole, {"name": "..", "is_dir": True, "up": True})
            up.setIcon(0, icon("arrow_up", "ft_folder"))
            up.setToolTip(0, tr("tip.fb_up_item"))
            self.tree.addTopLevelItem(up)
        shown = 0
        for e in entries:
            if not self.show_hidden and e["name"].startswith("."):
                continue
            mtime = datetime.fromtimestamp(e["mtime"]).strftime(tr("fmt.datetime_short")) if e.get("mtime") else ""
            item = _SortItem([e["name"], human_size(e.get("size")), mtime, e.get("owner", ""), e.get("group", ""),
                              e.get("perms", "")])
            item.setData(0, Qt.UserRole, e)
            item.setIcon(0, remote_file_icon(e["name"], e["is_dir"], e.get("is_link", False), e.get("mode", 0) or 0))
            if e["name"].startswith("."):
                item.setForeground(0, self.palette().placeholderText() if hasattr(self.palette(), "placeholderText")
                                   else self.palette().mid())
            self.tree.addTopLevelItem(item)
            shown += 1
        self.tree.setSortingEnabled(True)
        self.stack.setCurrentWidget(self.tree if (shown or path != "/") else self.empty)
        n_dirs = sum(1 for e in entries if e["is_dir"])
        hidden = len(entries) - shown
        text = tr("fb.summary", dirs=n_dirs, files=len(entries) - n_dirs)
        if hidden:
            text += "  ·  " + tr("fb.hidden_count", n=hidden)
        self.status_lbl.setText(text)

    def _join(self, name: str) -> str:
        return posixpath.join(self.cwd, name)

    def go_up(self) -> None:
        if self.cwd != "/":
            self.list_dir(posixpath.dirname(self.cwd.rstrip("/")) or "/")

    def go_home(self) -> None:
        self.list_dir(self.home or "/")

    def _selected(self) -> List[Dict]:
        return [d for d in (it.data(0, Qt.UserRole) for it in self.tree.selectedItems())
                if d and not d.get("up")]

    def _on_double_click(self, item, _col) -> None:
        e = item.data(0, Qt.UserRole) or {}
        if e.get("up"):
            self.go_up()
        elif e.get("is_dir"):
            self.list_dir(self._join(e["name"]))
        else:
            self.open_entry(e, "default")

    def _on_middle_click(self, item) -> None:
        e = item.data(0, Qt.UserRole) or {}
        if not e.get("up"):
            self.path_to_terminal.emit(self._join(e["name"]))

    def _on_key(self, action: str) -> None:
        sel = self._selected()
        if action == "open":
            items = self.tree.selectedItems()
            if items:
                self._on_double_click(items[0], 0)
        elif action == "up":
            self.go_up()
        elif action == "delete":
            self.delete_selected()
        elif action == "rename":
            self.rename_selected()
        elif action == "refresh":
            self.list_dir(self.cwd)
        elif action == "copy_path":
            self._copy_paths([self._join(e["name"]) for e in sel] or [self.cwd])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F5:
            self.list_dir(self.cwd)
        elif event.key() == Qt.Key_Backspace:
            self.go_up()
        else:
            super().keyPressEvent(event)

    def _header_menu(self, pos) -> None:
        menu = QMenu(self)
        for col, key in ((COL_SIZE, "col.size"), (COL_MTIME, "col.modified"), (COL_OWNER, "col.owner"),
                         (COL_GROUP, "col.group"), (COL_PERMS, "col.perms")):
            a = menu.addAction(tr(key))
            a.setCheckable(True)
            a.setChecked(not self.tree.isColumnHidden(col))
            a.toggled.connect(lambda on, c=col: self.tree.setColumnHidden(c, not on))
        _exec_menu(menu, self.tree.header().mapToGlobal(pos))

    # ── Menús ──────────────────────────────────────────────────────────
    def _common_actions(self, menu: QMenu) -> None:
        menu.addAction(tr("fb.mkdir")).triggered.connect(self.make_dir)
        menu.addAction(tr("fb.new_file")).triggered.connect(self.make_file)
        menu.addAction(tr("fb.upload")).triggered.connect(self.upload_dialog)
        menu.addAction(tr("fb.upload_folder")).triggered.connect(self.upload_folder_dialog)
        menu.addSeparator()
        menu.addAction(tr("fb.copy_cwd")).triggered.connect(lambda: self._copy_paths([self.cwd]))
        if self.embedded:
            menu.addAction(tr("fb.cd_terminal")).triggered.connect(lambda: self.cd_requested.emit(self.cwd))
        menu.addSeparator()
        hidden = menu.addAction(tr("fb.show_hidden"))
        hidden.setCheckable(True)
        hidden.setChecked(self.show_hidden)
        hidden.toggled.connect(self._toggle_hidden)
        menu.addAction(tr("fb.refresh")).triggered.connect(lambda: self.list_dir(self.cwd))

    def _fill_more_menu(self) -> None:
        self.more_menu.clear()
        if self.embedded:
            sel = self._selected()
            if sel:
                self.more_menu.addAction(tr("fb.rename")).triggered.connect(self.rename_selected)
                self.more_menu.addAction(tr("fb.delete")).triggered.connect(self.delete_selected)
                self.more_menu.addSeparator()
        self._common_actions(self.more_menu)

    def _toggle_hidden(self, on: bool) -> None:
        self.show_hidden = on
        self._fill(self.cwd, self._entries)

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        data = item.data(0, Qt.UserRole) if item else None
        if item is not None and not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        sel = self._selected()
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        if data and not data.get("up") and sel:
            one = sel[0] if len(sel) == 1 else None
            paths = [self._join(e["name"]) for e in sel]
            if one and not one["is_dir"]:
                act = menu.addAction(tr("fb.open"))
                f = act.font()
                f.setBold(True)
                act.setFont(f)
                act.triggered.connect(lambda: self.open_entry(one, "default"))
                menu.addAction(tr("fb.edit")).triggered.connect(lambda: self.open_entry(one, "edit"))
                menu.addAction(tr("fb.open_with")).triggered.connect(lambda: self.open_entry(one, "with"))
            elif one:
                act = menu.addAction(tr("fb.open_folder"))
                f = act.font()
                f.setBold(True)
                act.setFont(f)
                act.triggered.connect(lambda: self.list_dir(paths[0]))
                if self.embedded:
                    menu.addAction(tr("fb.cd_terminal")).triggered.connect(lambda: self.cd_requested.emit(paths[0]))
            menu.addAction(tr("fb.download")).triggered.connect(self.download_selected)
            menu.addSeparator()
            menu.addAction(tr("fb.copy_path")).triggered.connect(lambda: self._copy_paths(paths))
            if self.embedded:
                a = menu.addAction(tr("fb.path_to_terminal"))
                a.setToolTip(tr("tip.fb_path_to_terminal"))
                a.triggered.connect(lambda: self.path_to_terminal.emit(" ".join(paths)))
            menu.addSeparator()
            if one:
                menu.addAction(tr("fb.rename")).triggered.connect(self.rename_selected)
            menu.addAction(tr("fb.delete")).triggered.connect(self.delete_selected)
            menu.addSeparator()
            if one:
                menu.addAction(tr("fb.properties")).triggered.connect(lambda: self.show_properties(one))
            if self.fs is not None and self.fs.can_chmod:
                menu.addAction(tr("fb.permissions")).triggered.connect(lambda: self.change_permissions(sel))
        else:
            self._common_actions(menu)
        _exec_menu(menu, self.tree.viewport().mapToGlobal(pos))

    def _copy_paths(self, paths: List[str]) -> None:
        QApplication.clipboard().setText("\n".join(paths))
        self.status_lbl.setText(tr("fb.path_copied", path=paths[0] if len(paths) == 1 else f"{len(paths)}"))

    # ── Abrir / abrir con / editar ─────────────────────────────────────
    def _local_copy_path(self, remote: str) -> str:
        safe_host = "".join(c if c.isalnum() or c in "._-" else "_" for c in f"{self.host_label}")
        base = os.path.join(tempfile.gettempdir(), "NetworkTool", "remote", safe_host)
        local = os.path.join(base, *[p for p in remote.split("/") if p and p != ".."])
        os.makedirs(os.path.dirname(local), exist_ok=True)
        return local

    def open_entry(self, e: Dict, mode: str) -> None:
        """mode: default (programa predeterminado) | with (elegir programa) | edit (editor integrado)."""
        if self.fs is None or e.get("is_dir"):
            return
        remote = self._join(e["name"])
        if mode == "edit" and (e.get("size") or 0) > EDIT_LIMIT:
            QMessageBox.information(self, tr("fb.edit"), tr("fb.too_big_to_edit", size=human_size(e.get("size"))))
            mode = "default"
        if mode == "edit" and remote in self._editors:
            try:
                self._editors[remote].raise_()
                self._editors[remote].activateWindow()
                return
            except RuntimeError:
                self._editors.pop(remote, None)
        fs, cb = self.fs, self._progress_cb()
        local = self._local_copy_path(remote)
        self.progress.setValue(0)
        self.progress.setVisible(True)

        def job():
            fs.download(remote, local, cb)
            data = open(local, "rb").read() if mode == "edit" else b""
            return {"mode": mode, "remote": remote, "local": local, "data": data}
        self._run(f"open:{e['name']}", job, tr("fb.downloading", name=e["name"]))

    def _after_open(self, ok: bool, result) -> None:
        if not ok:
            QMessageBox.warning(self, tr("msg.error_title"), tr("fb.op_failed", detail=result))
            return
        mode, remote, local = result["mode"], result["remote"], result["local"]
        self.status_lbl.setText(tr("fb.opened", name=posixpath.basename(remote)))
        if mode == "edit":
            ed = TextEditorWindow(remote, result["data"], self.host_label, self)
            ed.save_requested.connect(self._save_from_editor)
            ed.destroyed.connect(lambda *_, r=remote: self._editors.pop(r, None))
            self._editors[remote] = ed
            ed.show()
            ed.raise_()
            return
        self._opened[os.path.normcase(local)] = {"remote": remote, "auto": False, "local": local}
        if local not in self.watcher.files():
            self.watcher.addPath(local)
        try:
            _open_local(local, choose=(mode == "with"))
        except Exception as ex:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.launch_failed", detail=ex))

    def _save_from_editor(self, remote: str, data: bytes) -> None:
        if self.fs is None:
            QMessageBox.warning(self, tr("msg.error_title"), tr("fb.save_failed", detail=tr("status.disconnected")))
            return
        fs, local = self.fs, self._local_copy_path(remote)

        def job():
            with open(local, "wb") as f:
                f.write(data)
            fs.upload(local, remote, lambda p: None)
        self._run(f"save:{remote}", job, tr("fb.uploading", name=posixpath.basename(remote)))

    def _on_local_changed(self, path: str) -> None:
        key = os.path.normcase(path)
        if key in self._opened:
            self._pending_changes.add(key)
            self._change_timer.start(800)          # los editores escriben en varias tandas
        # algunos editores reemplazan el archivo: se vuelve a vigilar
        if os.path.exists(path) and path not in self.watcher.files():
            self.watcher.addPath(path)

    def _ask_upload_changes(self) -> None:
        pending, self._pending_changes = self._pending_changes, set()
        for key in pending:
            info = self._opened.get(key)
            if not info or not os.path.exists(info["local"]) or self.fs is None:
                continue
            if not info["auto"]:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Question)
                box.setWindowTitle(tr("fb.changed_title"))
                box.setText(tr("fb.changed_text", name=posixpath.basename(info["remote"]), host=self.host_label))
                yes = box.addButton(tr("fb.upload_changes"), QMessageBox.AcceptRole)
                always = box.addButton(tr("fb.upload_always"), QMessageBox.AcceptRole)
                box.addButton(tr("common.cancel"), QMessageBox.RejectRole)
                _exec(box)
                clicked = box.clickedButton()
                if clicked is always:
                    info["auto"] = True
                elif clicked is not yes:
                    continue
            fs, local, remote = self.fs, info["local"], info["remote"]
            self._run(f"save:{remote}", lambda f=fs, l=local, r=remote: f.upload(l, r, lambda p: None),
                      tr("fb.uploading", name=posixpath.basename(remote)))

    # ── Propiedades y permisos ─────────────────────────────────────────
    def show_properties(self, e: Dict) -> None:
        fs, path = self.fs, self._join(e["name"])
        if fs is None:
            return
        self._run(f"props:{path}", lambda: dict(fs.stat(path), owner=e.get("owner", ""), group=e.get("group", ""),
                                                 perms=e.get("perms", "")))

    def change_permissions(self, entries: List[Dict]) -> None:
        if not entries or self.fs is None:
            return
        first = entries[0]
        shown = dict(first, name=first["name"] if len(entries) == 1 else tr("fb.n_items", n=len(entries)),
                     is_dir=any(e["is_dir"] for e in entries))
        dlg = _PermissionsDialog(shown, self.cwd if len(entries) > 1 else self._join(first["name"]), self)
        if _exec(dlg) != QDialog.Accepted:
            return
        mode, recursive, fs = dlg.mode(), dlg.recursive.isChecked(), self.fs
        targets = [(self._join(e["name"]), e["is_dir"] and not e.get("is_link")) for e in entries]

        def job():
            done, errors = 0, []
            for path, is_dir in targets:
                try:
                    (fs.chmod_tree if (recursive and is_dir) else fs.chmod)(path, mode)
                    done += 1
                except Exception as ex:
                    errors.append((posixpath.basename(path), friendly_error(ex)))
            return done, errors
        self._run("batch:chmod", job, tr("fb.applying_perms"))

    # ── Transferencias ─────────────────────────────────────────────────
    def download_selected(self) -> None:
        sel = self._selected()
        if not sel:
            QMessageBox.information(self, tr("fb.download"), tr("fb.select_files"))
            return
        if len(sel) == 1 and not sel[0]["is_dir"]:
            local, _ = QFileDialog.getSaveFileName(self, tr("fb.save_as"), sel[0]["name"])
            if not local:
                return
            targets = [(sel[0], local)]
        else:
            folder = QFileDialog.getExistingDirectory(self, tr("fb.choose_folder"))
            if not folder:
                return
            targets = [(e, os.path.join(folder, e["name"])) for e in sel]
        fs, cb = self.fs, self._progress_cb()
        self.progress.setValue(0)
        self.progress.setVisible(True)

        def job():
            done, errors = 0, []
            for e, local in targets:
                remote = self._join(e["name"])
                try:
                    if e["is_dir"]:
                        done += fs.download_tree(remote, local, cb)
                    else:
                        fs.download(remote, local, cb)
                        done += 1
                except Exception as ex:
                    errors.append((e["name"], friendly_error(ex)))
            return done, errors
        self._run("batch:download", job, tr("fb.downloading", name=", ".join(e["name"] for e in sel[:3])))

    def upload_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("fb.upload"))
        if files:
            self.upload_paths(files)

    def upload_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("fb.upload_folder"))
        if folder:
            self.upload_paths([folder])

    def upload_files(self, files: List[str]) -> None:     # compatibilidad
        self.upload_paths(files)

    def upload_paths(self, paths: List[str]) -> None:
        if not self.is_connected or not paths:
            return
        fs, cb, cwd = self.fs, self._progress_cb(), self.cwd
        self.progress.setValue(0)
        self.progress.setVisible(True)

        def job():
            done, errors = 0, []
            for local in paths:
                name = os.path.basename(local.rstrip("\\/"))
                remote = posixpath.join(cwd, name)
                try:
                    if os.path.isdir(local):
                        done += fs.upload_tree(local, remote, cb)
                    else:
                        fs.upload(local, remote, cb)
                        done += 1
                except Exception as ex:
                    errors.append((name, friendly_error(ex)))
            return done, errors
        names = ", ".join(os.path.basename(p.rstrip("\\/")) for p in paths[:3])
        self._run("batch:upload", job, tr("fb.uploading", name=names))

    # ── Crear, renombrar, eliminar ─────────────────────────────────────
    def make_dir(self) -> None:
        name, ok = QInputDialog.getText(self, tr("fb.mkdir"), tr("fb.folder_name"))
        name = (name or "").strip()
        if ok and name:
            fs, path = self.fs, self._join(name)
            self._run(f"mkdir:{name}", lambda: fs.mkdir(path))

    def make_file(self) -> None:
        name, ok = QInputDialog.getText(self, tr("fb.new_file"), tr("fb.file_name"))
        name = (name or "").strip()
        if ok and name:
            fs, path = self.fs, self._join(name)
            self._run(f"touch:{name}", lambda: fs.touch(path))

    def rename_selected(self) -> None:
        sel = self._selected()
        if len(sel) != 1:
            return
        old = sel[0]["name"]
        new, ok = QInputDialog.getText(self, tr("fb.rename"), tr("fb.new_name"), QLineEdit.Normal, old)
        new = (new or "").strip()
        if ok and new and new != old:
            fs, a, b = self.fs, self._join(old), self._join(new)
            self._run(f"rename:{new}", lambda: fs.rename(a, b))

    def delete_selected(self) -> None:
        sel = self._selected()
        if not sel:
            return
        names = ", ".join(e["name"] for e in sel[:5]) + (" …" if len(sel) > 5 else "")
        has_dirs = any(e["is_dir"] and not e.get("is_link") for e in sel)
        text = tr("fb.confirm_delete_dirs" if has_dirs else "fb.confirm_delete", names=names)
        if QMessageBox.question(self, tr("fb.delete"), text, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        fs = self.fs
        targets = [(self._join(e["name"]), e["is_dir"] and not e.get("is_link")) for e in sel]

        def job():
            done, errors = 0, []
            for path, is_dir in targets:
                try:
                    (fs.remove_tree(path) if is_dir else fs.remove(path, False))
                    done += 1
                except Exception as ex:
                    errors.append((posixpath.basename(path), friendly_error(ex)))
            return done, errors
        self._run("batch:delete", job, tr("fb.deleting", n=len(targets)))


# Compatibilidad: nombre público del diálogo de permisos
PermissionsDialog = _PermissionsDialog
