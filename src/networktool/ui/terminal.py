"""Terminal integrada para sesiones SSH y Telnet.

Emulación VT100/xterm con pyte; transporte con paramiko (SSH) o un socket (Telnet).
Cada pestaña es una TerminalTab: barra con estado + vista de terminal + scrollback.
"""

import codecs
import os
import re
import socket
import threading
from collections import deque
from typing import Dict, List, Optional

try:                          # sin pyte la app abre igual; solo la terminal queda deshabilitada
    import pyte
    from pyte.screens import Margins
except ImportError:
    pyte = None

from networktool.common import logger, nettool_data_dir
from networktool.i18n import tr
from networktool.qt_compat import (
    QApplication, QColor, QEvent, QFont, QFontMetrics, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QPainter, QRectF, QScrollBar, QSplitter, QThread, QTimer, QVBoxLayout, QWidget, Qt, Signal,
    _exec_menu,
)
from networktool.ui.theme import SP, THEME, make_badge, make_button, mono_font, set_badge, set_help

try:
    import paramiko
except ImportError:          # la app funciona igual; solo SSH/SFTP quedan deshabilitados
    paramiko = None

SCROLLBACK = 5000
_OSC7_RE = re.compile(r"\x1b\]7;([^\x07\x1b]*)(?:\x07|\x1b\\)")
# Shell bash/zsh: publica la carpeta actual en cada prompt (lo usa "Seguir carpeta de la terminal")
FOLLOW_CWD_CMD = (" export PROMPT_COMMAND='printf \"\\033]7;%s\\007\" \"$PWD\"'\"${PROMPT_COMMAND:+;$PROMPT_COMMAND}\""
                  " 2>/dev/null; precmd() { printf '\\033]7;%s\\007' \"$PWD\"; } 2>/dev/null\r")

_ANSI_NAMES = ["black", "red", "green", "brown", "blue", "magenta", "cyan", "white"]
_ANSI_INDEX = {name: i for i, name in enumerate(_ANSI_NAMES)}
_ANSI_INDEX.update({"bright" + name: i + 8 for i, name in enumerate(_ANSI_NAMES)})
_ANSI_INDEX.update({"yellow": 3, "brightyellow": 11})


# ══════════════════════════════════════════════════════════════════════════
#  PANTALLA CON HISTORIAL
# ══════════════════════════════════════════════════════════════════════════
class _Screen(pyte.Screen if pyte is not None else object):
    """pyte.Screen que guarda en el historial las líneas que salen por arriba."""

    def __init__(self, columns, lines):
        super().__init__(columns, lines)
        self.history: deque = deque(maxlen=SCROLLBACK)
        self.reply = None   # callback para respuestas al host (DA, DSR...)

    def index(self):
        top, bottom = self.margins or Margins(0, self.lines - 1)
        if top == 0 and self.cursor.y == bottom:
            line = self.buffer[0]
            self.history.append([line[x] for x in range(self.columns)])
        super().index()

    def write_process_input(self, data):
        if self.reply:
            self.reply(data)


# ══════════════════════════════════════════════════════════════════════════
#  TRANSPORTES
# ══════════════════════════════════════════════════════════════════════════
class _Backend(QThread):
    data = Signal(bytes)
    connected = Signal()
    closed = Signal(str)            # motivo ('' = cierre normal)
    host_key = Signal(str, str)     # host, huella → la UI responde con answer_host_key()

    def __init__(self):
        super().__init__()
        self._stop = False
        self._host_key_event = threading.Event()
        self._host_key_ok = False

    def answer_host_key(self, accept: bool) -> None:
        self._host_key_ok = accept
        self._host_key_event.set()

    def ask_host_key(self, host: str, fingerprint: str) -> bool:
        self._host_key_event.clear()
        self.host_key.emit(host, fingerprint)
        self._host_key_event.wait()
        return self._host_key_ok

    def send(self, payload: bytes) -> None: ...
    def resize(self, cols: int, rows: int) -> None: ...

    def close(self) -> None:
        self._stop = True
        self._host_key_event.set()


def terminal_missing_libs(protocol: str) -> str:
    """Librerías que faltan para abrir una sesión de ese protocolo ('' si están todas)."""
    need = []
    if protocol in ("wsl", "shell"):
        try:
            import winpty  # noqa: F401
        except Exception:
            need.append("pywinpty")
    if protocol in ("ssh", "sftp") and paramiko is None:
        need.append("paramiko")
    if protocol in ("ssh", "telnet", "wsl", "shell") and pyte is None:
        need.append("pyte")
    return ", ".join(need)


def known_hosts_path() -> str:
    path = nettool_data_dir() / "known_hosts"
    path.touch(exist_ok=True)
    return str(path)


if paramiko is not None:
    class _AskPolicy(paramiko.MissingHostKeyPolicy):
        """Clave de host desconocida: se pregunta al usuario y, si acepta, se guarda."""

        def __init__(self, backend: _Backend):
            self.backend = backend

        def missing_host_key(self, client, hostname, key):
            fp = ":".join(f"{b:02x}" for b in key.get_fingerprint())
            if not self.backend.ask_host_key(hostname, f"{key.get_name()}  {fp}"):
                raise paramiko.SSHException(tr("term.hostkey_rejected"))
            client.get_host_keys().add(hostname, key.get_name(), key)
            try:
                client.save_host_keys(known_hosts_path())
            except Exception as e:
                logger.warning(f"known_hosts: {e}")


def open_ssh_client(backend: _Backend, cred: Dict) -> "paramiko.SSHClient":
    """Conecta y autentica un SSHClient (lo usan la terminal y el explorador SFTP)."""
    if paramiko is None:
        raise RuntimeError(tr("term.no_paramiko"))
    client = paramiko.SSHClient()
    try:
        client.load_host_keys(known_hosts_path())
    except Exception:
        pass
    client.set_missing_host_key_policy(_AskPolicy(backend))
    key_file = cred.get("key_file") or None
    password = cred.get("password") or None
    try:
        client.connect(
            cred["host"], port=int(cred["port"]), username=cred.get("username") or None,
            password=None if key_file else password, passphrase=password if key_file else None,
            key_filename=key_file, timeout=10, banner_timeout=15, auth_timeout=20,
            look_for_keys=not password and not key_file, allow_agent=not password,
        )
    except paramiko.AuthenticationException:
        # Equipos que solo aceptan "keyboard-interactive" (routers, algunos Linux): se responde
        # a cada pregunta con la contraseña, igual que MobaXterm.
        transport = client.get_transport()
        if not (password and not key_file and transport and transport.is_active()):
            client.close()
            raise
        try:
            transport.auth_interactive(cred.get("username") or "",
                                       lambda title, instructions, prompts: [password] * len(prompts))
        except Exception:
            client.close()
            raise
    return client


def is_auth_error(exc: Exception) -> bool:
    return paramiko is not None and isinstance(exc, paramiko.AuthenticationException)


class SSHBackend(_Backend):
    def __init__(self, cred: Dict, cols: int, rows: int):
        super().__init__()
        self.cred, self.cols, self.rows = cred, cols, rows
        self.client = None
        self.chan = None
        self.auth_failed = False
        self._lock = threading.Lock()

    def run(self):
        reason = ""
        try:
            self.client = open_ssh_client(self, self.cred)
            self.client.get_transport().set_keepalive(30)
            self.chan = self.client.invoke_shell(term="xterm-256color", width=self.cols, height=self.rows)
            self.chan.settimeout(0.2)
            self.connected.emit()
            while not self._stop:
                try:
                    chunk = self.chan.recv(65536)
                except socket.timeout:
                    if self.chan.closed or self.chan.exit_status_ready():
                        break
                    continue
                if not chunk:
                    break
                self.data.emit(chunk)
        except Exception as e:
            reason = str(e) or e.__class__.__name__
            self.auth_failed = is_auth_error(e)
        finally:
            try:
                if self.client:
                    self.client.close()
            except Exception:
                pass
        self.closed.emit(reason)

    def send(self, payload: bytes) -> None:
        with self._lock:
            try:
                if self.chan and not self.chan.closed:
                    self.chan.sendall(payload)
            except Exception as e:
                logger.debug(f"ssh send: {e}")

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        try:
            if self.chan and not self.chan.closed:
                self.chan.resize_pty(width=cols, height=rows)
        except Exception:
            pass

    def close(self) -> None:
        super().close()
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass


# Telnet: constantes del protocolo (RFC 854)
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
OPT_ECHO, OPT_SGA, OPT_TTYPE, OPT_NAWS = 1, 3, 24, 31


class TelnetBackend(_Backend):
    def __init__(self, cred: Dict, cols: int, rows: int):
        super().__init__()
        self.cred, self.cols, self.rows = cred, cols, rows
        self.sock: Optional[socket.socket] = None
        self._naws = False
        self._lock = threading.Lock()

    def _raw(self, payload: bytes) -> None:
        with self._lock:
            if self.sock:
                self.sock.sendall(payload)

    def _send_naws(self) -> None:
        w, h = self.cols, self.rows
        body = bytes([w >> 8 & 0xFF, w & 0xFF, h >> 8 & 0xFF, h & 0xFF]).replace(b"\xff", b"\xff\xff")
        self._raw(bytes([IAC, SB, OPT_NAWS]) + body + bytes([IAC, SE]))

    def _negotiate(self, buf: bytearray) -> bytes:
        """Separa los comandos IAC del texto y responde las negociaciones."""
        out = bytearray()
        i = 0
        while i < len(buf):
            b = buf[i]
            if b != IAC:
                out.append(b); i += 1; continue
            if i + 1 >= len(buf):
                break
            cmd = buf[i + 1]
            if cmd == IAC:
                out.append(IAC); i += 2; continue
            if cmd in (DO, DONT, WILL, WONT):
                if i + 2 >= len(buf):
                    break
                opt = buf[i + 2]
                if cmd == DO:
                    if opt == OPT_NAWS:
                        self._raw(bytes([IAC, WILL, OPT_NAWS])); self._naws = True; self._send_naws()
                    elif opt == OPT_TTYPE:
                        self._raw(bytes([IAC, WILL, OPT_TTYPE]))
                    else:
                        self._raw(bytes([IAC, WONT, opt]))
                elif cmd == WILL:
                    self._raw(bytes([IAC, DO if opt in (OPT_ECHO, OPT_SGA) else DONT, opt]))
                i += 3; continue
            if cmd == SB:
                end = buf.find(bytes([IAC, SE]), i)
                if end < 0:
                    break
                sub = buf[i + 2:end]
                if sub[:2] == bytes([OPT_TTYPE, 1]):   # SEND
                    self._raw(bytes([IAC, SB, OPT_TTYPE, 0]) + b"XTERM" + bytes([IAC, SE]))
                i = end + 2; continue
            i += 2
        del buf[:i]
        return bytes(out)

    def run(self):
        reason = ""
        try:
            self.sock = socket.create_connection((self.cred["host"], int(self.cred["port"])), timeout=10)
            self.sock.settimeout(0.2)
            self.connected.emit()
            pending = bytearray()
            while not self._stop:
                try:
                    chunk = self.sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                pending += chunk
                text = self._negotiate(pending)
                if text:
                    self.data.emit(text)
        except Exception as e:
            reason = str(e) or e.__class__.__name__
        finally:
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass
        self.closed.emit(reason)

    def send(self, payload: bytes) -> None:
        try:
            self._raw(payload.replace(b"\xff", b"\xff\xff"))
        except Exception as e:
            logger.debug(f"telnet send: {e}")

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        if self._naws:
            try:
                self._send_naws()
            except Exception:
                pass

    def close(self) -> None:
        super().close()
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass


class LocalPtyBackend(_Backend):
    """Proceso local en una pseudo-terminal de Windows (ConPTY): WSL, PowerShell, CMD, Git Bash."""

    def __init__(self, cred: Dict, cols: int, rows: int):
        super().__init__()
        self.cred, self.cols, self.rows = cred, cols, rows
        self.proc = None
        self._lock = threading.Lock()

    def run(self):
        reason = ""
        try:
            from winpty import PtyProcess
            self.proc = PtyProcess.spawn(self.cred["command"], dimensions=(self.rows, self.cols),
                                         cwd=os.path.expanduser("~"))
            self.connected.emit()
            while not self._stop:
                try:
                    text = self.proc.read(65536)
                except EOFError:
                    break
                if text:
                    self.data.emit(text.encode("utf-8", "replace"))
                elif not self.proc.isalive():
                    break
        except Exception as e:
            reason = str(e) or e.__class__.__name__
        finally:
            self._kill()
        self.closed.emit(reason)

    def _kill(self):
        try:
            if self.proc is not None and self.proc.isalive():
                self.proc.terminate(force=True)
        except Exception:
            pass

    def send(self, payload: bytes) -> None:
        with self._lock:
            try:
                if self.proc is not None and self.proc.isalive():
                    self.proc.write(payload.decode("utf-8", "replace"))
            except Exception as e:
                logger.debug(f"pty send: {e}")

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        try:
            if self.proc is not None and self.proc.isalive():
                self.proc.setwinsize(rows, cols)
        except Exception:
            pass

    def close(self) -> None:
        super().close()
        self._kill()


# ══════════════════════════════════════════════════════════════════════════
#  VISTA DE TERMINAL
# ══════════════════════════════════════════════════════════════════════════
_KEYS = {
    Qt.Key_Up: ("\x1b[A", "\x1bOA"), Qt.Key_Down: ("\x1b[B", "\x1bOB"),
    Qt.Key_Right: ("\x1b[C", "\x1bOC"), Qt.Key_Left: ("\x1b[D", "\x1bOD"),
    Qt.Key_Home: ("\x1b[H", "\x1bOH"), Qt.Key_End: ("\x1b[F", "\x1bOF"),
}
_FKEYS = {
    Qt.Key_PageUp: "\x1b[5~", Qt.Key_PageDown: "\x1b[6~", Qt.Key_Insert: "\x1b[2~",
    Qt.Key_Delete: "\x1b[3~", Qt.Key_F1: "\x1bOP", Qt.Key_F2: "\x1bOQ", Qt.Key_F3: "\x1bOR",
    Qt.Key_F4: "\x1bOS", Qt.Key_F5: "\x1b[15~", Qt.Key_F6: "\x1b[17~", Qt.Key_F7: "\x1b[18~",
    Qt.Key_F8: "\x1b[19~", Qt.Key_F9: "\x1b[20~", Qt.Key_F10: "\x1b[21~", Qt.Key_F11: "\x1b[23~",
    Qt.Key_F12: "\x1b[24~", Qt.Key_Escape: "\x1b", Qt.Key_Tab: "\t", Qt.Key_Backspace: "\x7f",
    Qt.Key_Return: "\r", Qt.Key_Enter: "\r",
}


def _modifiers_int(mods) -> int:
    try:
        return int(mods)
    except TypeError:
        return mods.value


class TerminalView(QWidget):
    """Dibuja la pantalla de pyte y traduce el teclado a secuencias xterm."""
    send_bytes = Signal(bytes)
    resized = Signal(int, int)        # columnas, filas
    cwd_changed = Signal(str)         # carpeta actual del shell (secuencia OSC 7)
    text_received = Signal(str)       # texto decodificado (para el auto-login de Telnet)

    def __init__(self, encoding: str = "utf-8", parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setCursor(Qt.IBeamCursor)
        self.setMinimumSize(200, 120)
        self.font_ = mono_font(13)
        self.font_bold = QFont(self.font_)
        self.font_bold.setBold(True)
        fm = QFontMetrics(self.font_)
        self.cw = max(1, fm.horizontalAdvance("M") if hasattr(fm, "horizontalAdvance") else fm.width("M"))
        self.ch = max(1, fm.height())
        self.ascent = fm.ascent()
        self.screen = _Screen(80, 24)
        self.screen.reply = lambda text: self.send_bytes.emit(text.encode(self.encoding, "replace"))
        self.stream = pyte.Stream(self.screen)
        self.set_encoding(encoding)
        self.scroll_offset = 0            # líneas de historial visibles por encima
        self._osc_tail = ""
        self.scrollbar: Optional[QScrollBar] = None
        self._sel_start = self._sel_end = None   # (línea absoluta, columna)
        self._colors = [QColor(c) for c in THEME["ansi"]]
        self._fg = QColor(THEME["term_fg"])
        self._bg = QColor(THEME["term_bg"])
        self._cursor_color = QColor(THEME["term_cursor"])
        self._sel_color = QColor(THEME["selection"])
        self._repaint_pending = False

    def set_encoding(self, encoding: str) -> None:
        try:
            codecs.lookup(encoding)
        except LookupError:
            encoding = "utf-8"
        self.encoding = encoding
        self._decoder = codecs.getincrementaldecoder(encoding)(errors="replace")

    # ── Datos ──────────────────────────────────────────────────────────
    def feed(self, payload: bytes) -> None:
        text = self._decoder.decode(payload)
        if "\x1b]7;" in text or self._osc_tail:
            self._scan_osc7(text)
        self.stream.feed(text)
        self.text_received.emit(text)
        if self.scroll_offset:
            self.scroll_offset = min(len(self.screen.history), self.scroll_offset)
        self._sync_scrollbar()
        if not self._repaint_pending:      # agrupa ráfagas de datos en un solo repintado
            self._repaint_pending = True
            QTimer.singleShot(15, self._do_repaint)

    def _scan_osc7(self, text: str) -> None:
        """OSC 7 (ESC ] 7 ; ruta BEL): el shell avisa en qué carpeta está."""
        buf = self._osc_tail + text
        self._osc_tail = ""
        for m in _OSC7_RE.finditer(buf):
            path = m.group(1)
            if path.startswith("file://"):
                path = "/" + path[7:].split("/", 1)[-1] if "/" in path[7:] else "/"
            self.cwd_changed.emit(path)
        cut = buf.rfind("\x1b]7;")
        if cut >= 0 and not _OSC7_RE.match(buf, cut):
            self._osc_tail = buf[cut:][-512:]        # secuencia partida entre dos paquetes

    def feed_text(self, text: str) -> None:
        self.stream.feed(text)
        self._sync_scrollbar()
        self.update()

    def _do_repaint(self):
        self._repaint_pending = False
        self.update()

    def grid_size(self):
        return max(10, self.width() // self.cw), max(3, self.height() // self.ch)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cols, rows = self.grid_size()
        if (cols, rows) != (self.screen.columns, self.screen.lines):
            self.screen.resize(rows, cols)
            self.resized.emit(cols, rows)
            self._sync_scrollbar()

    # ── Scrollback ─────────────────────────────────────────────────────
    def attach_scrollbar(self, bar: QScrollBar) -> None:
        self.scrollbar = bar
        bar.valueChanged.connect(self._on_scrollbar)
        self._sync_scrollbar()

    def _sync_scrollbar(self) -> None:
        if not self.scrollbar:
            return
        n = len(self.screen.history)
        self.scrollbar.blockSignals(True)
        self.scrollbar.setRange(0, n)
        self.scrollbar.setPageStep(self.screen.lines)
        self.scrollbar.setValue(n - self.scroll_offset)
        self.scrollbar.blockSignals(False)

    def _on_scrollbar(self, value: int) -> None:
        self.scroll_offset = len(self.screen.history) - value
        self.update()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() // 40
        self.scroll_offset = max(0, min(len(self.screen.history), self.scroll_offset + steps))
        self._sync_scrollbar()
        self.update()

    # ── Líneas visibles (historial + pantalla) ─────────────────────────
    def _line_at(self, abs_row: int) -> List:
        hist = self.screen.history
        if abs_row < len(hist):
            return hist[abs_row]
        line = self.screen.buffer[abs_row - len(hist)]
        return [line[x] for x in range(self.screen.columns)]

    def _first_visible(self) -> int:
        return len(self.screen.history) - self.scroll_offset

    # ── Pintado ────────────────────────────────────────────────────────
    def _color(self, value: str, default: QColor) -> QColor:
        if value == "default":
            return default
        idx = _ANSI_INDEX.get(value)
        if idx is not None:
            return self._colors[idx]
        if len(value) == 6:
            try:
                return QColor("#" + value)
            except Exception:
                pass
        return default

    def _selected(self, row: int, col: int) -> bool:
        if self._sel_start is None or self._sel_end is None:
            return False
        a, b = sorted((self._sel_start, self._sel_end))
        return a <= (row, col) < b

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg)
        first = self._first_visible()
        cols = self.screen.columns
        for y in range(self.screen.lines):
            abs_row = first + y
            line = self._line_at(abs_row)
            x = 0
            while x < cols:
                c = line[x] if x < len(line) else self.screen.default_char
                fg = self._color(c.fg, self._fg)
                bg = self._color(c.bg, self._bg)
                if c.bold and c.fg in _ANSI_NAMES:
                    fg = self._colors[_ANSI_INDEX[c.fg] + 8]
                if c.reverse:
                    fg, bg = bg, fg
                sel = self._selected(abs_row, x)
                # agrupa caracteres con el mismo formato en una sola llamada drawText
                run = [c.data or " "]
                x2 = x + 1
                while x2 < cols:
                    d = line[x2] if x2 < len(line) else self.screen.default_char
                    if (d.fg, d.bg, d.bold, d.reverse, d.underscore) != (c.fg, c.bg, c.bold, c.reverse, c.underscore) \
                            or self._selected(abs_row, x2) != sel:
                        break
                    run.append(d.data or " ")
                    x2 += 1
                rect = QRectF(x * self.cw, y * self.ch, (x2 - x) * self.cw, self.ch)
                if sel:
                    bg, fg = self._sel_color, QColor(THEME["selection_text"])
                if bg != self._bg:
                    p.fillRect(rect, bg)
                text = "".join(run)
                if text.strip():
                    p.setFont(self.font_bold if c.bold else self.font_)
                    p.setPen(fg)
                    for i, ch in enumerate(text):   # celda fija: evita desalinear con anchos variables
                        if ch != " ":
                            p.drawText(int((x + i) * self.cw), int(y * self.ch + self.ascent), ch)
                if c.underscore:
                    p.setPen(fg)
                    p.drawLine(int(rect.left()), int(rect.bottom()) - 1, int(rect.right()), int(rect.bottom()) - 1)
                x = x2
        # cursor
        if not self.scroll_offset and not self.screen.cursor.hidden:
            cx, cy = self.screen.cursor.x, self.screen.cursor.y
            rect = QRectF(cx * self.cw, cy * self.ch, self.cw, self.ch)
            if self.hasFocus():
                color = QColor(self._cursor_color)
                color.setAlpha(170)
                p.fillRect(rect, color)
            else:
                p.setPen(self._cursor_color)
                p.drawRect(rect.adjusted(0, 0, -1, -1))
        p.end()

    # ── Teclado ────────────────────────────────────────────────────────
    def event(self, ev):
        # Tab / Shift+Tab van a la terminal, no al cambio de foco
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(ev)
            return True
        return super().event(ev)

    def keyPressEvent(self, event):
        key = event.key()
        mods = _modifiers_int(event.modifiers())
        ctrl = bool(mods & _modifiers_int(Qt.ControlModifier))
        shift = bool(mods & _modifiers_int(Qt.ShiftModifier))
        alt = bool(mods & _modifiers_int(Qt.AltModifier))
        if ctrl and shift and key == Qt.Key_C:
            self.copy_selection(); return
        if ctrl and shift and key == Qt.Key_V:
            self.paste(); return
        if shift and key in (Qt.Key_PageUp, Qt.Key_PageDown):
            delta = self.screen.lines if key == Qt.Key_PageUp else -self.screen.lines
            self.scroll_offset = max(0, min(len(self.screen.history), self.scroll_offset + delta))
            self._sync_scrollbar(); self.update(); return
        seq = None
        if key in _KEYS:
            app_mode = (1 << 5) in self.screen.mode        # DECCKM
            seq = _KEYS[key][1 if app_mode else 0]
        elif key == Qt.Key_Backtab:
            seq = "\x1b[Z"
        elif key in _FKEYS:
            seq = _FKEYS[key]
        elif ctrl and Qt.Key_A <= key <= Qt.Key_Z:
            seq = chr(key - Qt.Key_A + 1)
        elif ctrl and key in (Qt.Key_BracketLeft, Qt.Key_Backslash, Qt.Key_BracketRight):
            seq = {Qt.Key_BracketLeft: "\x1b", Qt.Key_Backslash: "\x1c", Qt.Key_BracketRight: "\x1d"}[key]
        elif ctrl and key == Qt.Key_Space:
            seq = "\x00"
        else:
            seq = event.text()
        if not seq:
            return
        if alt and len(seq) == 1:
            seq = "\x1b" + seq
        self._reset_view()
        self.send_bytes.emit(seq.encode(self.encoding, "replace"))

    def inputMethodEvent(self, event):
        text = event.commitString()
        if text:
            self._reset_view()
            self.send_bytes.emit(text.encode(self.encoding, "replace"))

    def _reset_view(self):
        if self.scroll_offset:
            self.scroll_offset = 0
            self._sync_scrollbar()
        self._sel_start = self._sel_end = None
        self.update()

    # ── Selección, copiar y pegar ──────────────────────────────────────
    def _cell_at(self, pos):
        col = max(0, min(self.screen.columns, int(pos.x() // self.cw)))
        row = max(0, min(self.screen.lines - 1, int(pos.y() // self.ch)))
        return self._first_visible() + row, col

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.LeftButton:
            self._sel_start = self._sel_end = self._cell_at(event.pos())
            self.update()
        elif event.button() == Qt.MiddleButton:
            self.paste()

    def mouseMoveEvent(self, event):
        if self._sel_start is not None and event.buttons() & Qt.LeftButton:
            self._sel_end = self._cell_at(event.pos())
            self.update()

    def mouseDoubleClickEvent(self, event):
        row, col = self._cell_at(event.pos())
        line = "".join(c.data for c in self._line_at(row))
        a = b = min(col, len(line) - 1)
        while a > 0 and not line[a - 1].isspace():
            a -= 1
        while b < len(line) and not line[b].isspace():
            b += 1
        self._sel_start, self._sel_end = (row, a), (row, b)
        self.update()

    def selected_text(self) -> str:
        if self._sel_start is None or self._sel_end is None or self._sel_start == self._sel_end:
            return ""
        (r1, c1), (r2, c2) = sorted((self._sel_start, self._sel_end))
        out = []
        for r in range(r1, r2 + 1):
            chars = "".join(c.data for c in self._line_at(r))
            seg = chars[c1 if r == r1 else 0: c2 if r == r2 else len(chars)]
            out.append(seg.rstrip())
        return "\n".join(out)

    def copy_selection(self) -> None:
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def paste(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self._reset_view()
            self.send_bytes.emit(text.replace("\r\n", "\r").replace("\n", "\r").encode(self.encoding, "replace"))

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act_copy = menu.addAction(tr("term.copy"))
        act_copy.setEnabled(bool(self.selected_text()))
        act_copy.triggered.connect(self.copy_selection)
        menu.addAction(tr("term.paste")).triggered.connect(self.paste)
        menu.addSeparator()
        menu.addAction(tr("term.clear_scrollback")).triggered.connect(self.clear_scrollback)
        _exec_menu(menu, event.globalPos())

    def clear_scrollback(self) -> None:
        self.screen.history.clear()
        self.scroll_offset = 0
        self._sync_scrollbar()
        self.update()


# ══════════════════════════════════════════════════════════════════════════
#  PESTAÑA DE SESIÓN DE TERMINAL
# ══════════════════════════════════════════════════════════════════════════
class TerminalTab(QWidget):
    """Sesión SSH / Telnet en una pestaña.

    SSH: a la izquierda un explorador SFTP que usa la MISMA conexión que la terminal (se trabaja en
    los dos a la vez, como en MobaXterm); se oculta y muestra con "Archivos (SFTP)".
    Telnet: si hay credencial guardada, responde solo a "login:" y "password:".
    """
    title_changed = Signal(str)
    state_changed = Signal(bool)    # conectado / desconectado
    auth_failed = Signal()          # usuario/contraseña rechazados: la ventana los vuelve a pedir
    connected_ok = Signal()         # conexión autenticada (para guardar la credencial si corresponde)
    broadcast = Signal(bytes)       # MultiExec: teclas para todas las terminales marcadas

    def __init__(self, session: Dict, cred: Dict, parent=None):
        super().__init__(parent)
        self.session, self.cred = session, cred
        self.backend: Optional[_Backend] = None
        self.is_connected = False
        self.protocol = session["protocol"]
        self.is_ssh = self.protocol == "ssh"
        self.is_local = self.protocol in ("wsl", "shell")
        self.has_files = self.protocol in ("ssh", "wsl")
        self._autologin = {"user": False, "pass": False}
        self._autologin_buf = ""
        self._follow_sent = False
        self.setObjectName("page")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(SP["md"], SP["sm"], SP["md"], SP["sm"])
        bar_lay.setSpacing(SP["sm"])
        self.badge = make_badge(tr("status.connecting"), "info")
        set_help(self.badge, "badge_session")
        bar_lay.addWidget(self.badge)
        if self.is_local:
            target = session.get("name") or self.protocol
        else:
            target = f"{cred.get('username') + '@' if cred.get('username') else ''}{cred['host']}:{cred['port']}"
        lbl = QLabel(f"{session['protocol'].upper()}  ·  {target}")
        lbl.setObjectName("lblHint")
        bar_lay.addWidget(lbl)
        bar_lay.addStretch(1)
        self.btn_sftp = make_button(tr("btn.open_files") if self.protocol == "wsl" else tr("btn.open_sftp"),
                                    "btnSecondary", "toggle_sftp", self._toggle_sftp)
        self.btn_sftp.setCheckable(True)
        self.btn_sftp.setVisible(self.has_files)
        self.btn_multi = make_button(tr("btn.multiexec"), "btnSecondary", "multiexec", None)
        self.btn_multi.setCheckable(True)
        self.btn_copy = make_button(tr("term.copy"), None, "term_copy", lambda: self.view.copy_selection(),
                                    shortcut="Ctrl+Shift+C")
        self.btn_paste = make_button(tr("term.paste"), None, "term_paste", lambda: self.view.paste(),
                                     shortcut="Ctrl+Shift+V")
        self.btn_reconnect = make_button(tr("btn.reconnect") if not self.is_local else tr("btn.restart"),
                                         "btnConnect", "reconnect", self.connect_session)
        self.btn_disconnect = make_button(tr("btn.disconnect"), "btnDisconnect", "disconnect_session",
                                          self.disconnect_session)
        for b in (self.btn_sftp, self.btn_multi, self.btn_copy, self.btn_paste, self.btn_reconnect,
                  self.btn_disconnect):
            bar_lay.addWidget(b)
        root.addWidget(bar)

        term = QWidget()
        term_lay = QHBoxLayout(term)
        term_lay.setContentsMargins(SP["sm"], 0, 0, SP["sm"])
        term_lay.setSpacing(0)
        self.view = TerminalView(session.get("encoding") or "utf-8")
        self.view.send_bytes.connect(self._on_keys)
        self.view.resized.connect(self._on_resized)
        self.view.text_received.connect(self._on_text)
        self.scroll = QScrollBar(Qt.Vertical)
        self.view.attach_scrollbar(self.scroll)
        term_lay.addWidget(self.view, 1)
        term_lay.addWidget(self.scroll)

        self.sftp = None
        if self.has_files:
            from networktool.ui.filebrowser import FileBrowserTab
            self.split = QSplitter(Qt.Horizontal)
            self.split.setObjectName("mainSplitter")
            self.split.setHandleWidth(1)
            self.split.setChildrenCollapsible(False)
            self.sftp = FileBrowserTab(session, cred, embedded=True)
            self.sftp.setMinimumWidth(280)
            self.sftp.cd_requested.connect(self._cd_in_terminal)
            self.sftp.follow_toggled.connect(self._on_follow_toggled)
            self.sftp.path_to_terminal.connect(self._paste_path)
            self.view.cwd_changed.connect(self.sftp.go_to)
            self.split.addWidget(self.sftp)
            self.split.addWidget(term)
            self.split.setStretchFactor(0, 0)
            self.split.setStretchFactor(1, 1)
            self.split.setSizes([340, 900])
            root.addWidget(self.split, 1)
            self.btn_sftp.setChecked(True)
        else:
            root.addWidget(term, 1)
        self._set_state(False, connecting=True)

    # ── Conexión ───────────────────────────────────────────────────────
    def connect_session(self) -> None:
        self._stop_backend()
        self._autologin = {"user": False, "pass": False}
        self._autologin_buf = ""
        self._follow_sent = False
        cols, rows = self.view.screen.columns, self.view.screen.lines
        cls = SSHBackend if self.is_ssh else (LocalPtyBackend if self.is_local else TelnetBackend)
        if not self.is_local:
            self.view.feed_text("\r\n\x1b[90m" + tr("term.connecting", host=self.cred["host"],
                                                   port=self.cred["port"]) + "\x1b[0m\r\n")
        self.backend = cls(self.cred, cols, rows)
        self.backend.data.connect(self.view.feed)
        self.backend.connected.connect(self._on_connected)
        self.backend.closed.connect(self._on_closed)
        self.backend.host_key.connect(self._ask_host_key)
        self._set_state(False, connecting=True)
        self.backend.start()
        self.view.setFocus()

    def reconnect_with(self, cred: Dict) -> None:
        """Reintenta con otras credenciales (tras "contraseña incorrecta")."""
        self.cred.update(cred)
        self.connect_session()

    def disconnect_session(self) -> None:
        self._stop_backend()

    def _stop_backend(self) -> None:
        if self.backend is not None:
            backend, self.backend = self.backend, None
            try:
                backend.data.disconnect()
            except Exception:
                pass
            backend.close()
            backend.wait(1500)
            if self.is_connected:
                self._on_closed("")

    def _on_keys(self, payload: bytes) -> None:
        self.send(payload)
        if self.btn_multi.isChecked():
            self.broadcast.emit(payload)

    def send(self, payload: bytes) -> None:
        if self.backend is not None and self.is_connected:
            self.backend.send(payload)

    def _on_resized(self, cols: int, rows: int) -> None:
        if self.backend is not None:
            self.backend.resize(cols, rows)

    def _on_connected(self) -> None:
        self._set_state(True)
        cols, rows = self.view.grid_size()
        self.backend.resize(cols, rows)
        self.view.setFocus()
        if self.sftp is not None and getattr(self.backend, "client", None) is not None:
            self.sftp.attach_client(self.backend.client)
        elif self.sftp is not None and self.protocol == "wsl":
            from networktool.ui.filebrowser import LocalFS
            from networktool.net.wsl import wsl_unc_root
            self.sftp.attach_fs(LocalFS(wsl_unc_root(self.session.get("distro") or ""), start="~"))
        self.connected_ok.emit()

    def _on_closed(self, reason: str) -> None:
        backend = self.sender()
        if backend is not None and backend is not self.backend and self.backend is not None:
            return    # aviso de un transporte viejo (reconexión)
        msg = tr("term.closed_reason", reason=reason) if reason else tr("term.closed")
        self.view.feed_text(f"\r\n\x1b[31m{msg}\x1b[0m\r\n")
        self._set_state(False)
        if self.sftp is not None:
            self.sftp.detach()
        if getattr(backend, "auth_failed", False):
            self.auth_failed.emit()

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
        self.btn_reconnect.setEnabled(not connected and not connecting)
        self.btn_disconnect.setEnabled(connected or connecting)
        self.state_changed.emit(connected)

    # ── SFTP lateral y carpeta de la terminal ──────────────────────────
    def _toggle_sftp(self) -> None:
        if self.sftp is not None:
            self.sftp.setVisible(self.btn_sftp.isChecked())

    def _cd_in_terminal(self, path: str) -> None:
        quoted = "'" + path.replace("'", "'\\''") + "'"
        self.send(f"cd {quoted}\r".encode(self.view.encoding, "replace"))
        self.view.setFocus()

    def _paste_path(self, path: str) -> None:
        """"Copiar ruta a la terminal": la escribe en la línea de comandos (sin Enter)."""
        quoted = path if all(c.isalnum() or c in "/._-~+" for c in path) else "'" + path.replace("'", "'\\''") + "'"
        self.send(quoted.encode(self.view.encoding, "replace"))
        self.view.setFocus()

    def _on_follow_toggled(self, on: bool) -> None:
        if on and not self._follow_sent and self.is_connected:
            self._follow_sent = True      # una vez por conexión: el shell publica su carpeta (OSC 7)
            self.send(FOLLOW_CWD_CMD.encode(self.view.encoding, "replace"))

    # ── Auto-login de Telnet ───────────────────────────────────────────
    def _on_text(self, text: str) -> None:
        if self.protocol != "telnet" or not self.cred.get("password") or all(self._autologin.values()):
            return
        self._autologin_buf = (self._autologin_buf + _ANSI_RE.sub("", text))[-200:]
        tail = self._autologin_buf.rstrip().lower()
        if not self._autologin["user"] and self.cred.get("username") and _LOGIN_RE.search(tail):
            self._autologin["user"] = True
            self._autologin_buf = ""
            self.send((self.cred["username"] + "\r").encode(self.view.encoding, "replace"))
        elif not self._autologin["pass"] and _PASS_RE.search(tail):
            self._autologin["pass"] = True
            self._autologin["user"] = True
            self._autologin_buf = ""
            self.send((self.cred["password"] + "\r").encode(self.view.encoding, "replace"))
            self.connected_ok.emit()

    def shutdown(self) -> None:
        self._stop_backend()
        if self.sftp is not None:
            self.sftp.shutdown()


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
_LOGIN_RE = re.compile(r"(login|username|user name|usuario)\s*:\s*$")
_PASS_RE = re.compile(r"(password|passwd|contraseña|clave)\s*:\s*$")
