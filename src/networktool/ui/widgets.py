"""Widgets auxiliares: celdas, avisos, registro en pantalla, grip de redimensión."""

import ipaddress
import logging

from networktool.qt_compat import (
    QColor, QLabel, QPainter, QPen, QTableWidgetItem, QTimer, QWidget, Qt, _global_pos,
)
from networktool.ui.theme import SP, THEME, _repolish


class IPTableItem(QTableWidgetItem):
    """Celda de IP que ordena numéricamente (192.168.0.9 antes que 192.168.0.10)."""
    def __lt__(self, other):
        try:
            return int(ipaddress.IPv4Address(self.text())) < int(ipaddress.IPv4Address(other.text()))
        except Exception:
            return self.text() < other.text()


class QtLogHandler(logging.Handler):
    """Envía los registros al panel de actividad (vía señal Qt, seguro entre hilos)."""
    def __init__(self, emit_fn):
        super().__init__(level=logging.INFO)
        self.emit_fn = emit_fn

    def emit(self, record):
        try:
            level = "error" if record.levelno >= logging.ERROR else ("warn" if record.levelno >= logging.WARNING
                                                                      else "info")
            self.emit_fn(record.getMessage(), level)
        except Exception:
            pass


class Toast(QLabel):
    """Aviso breve no bloqueante en la esquina inferior derecha. kind: ok | info | warn | error."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setMaximumWidth(440)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, kind: str = "ok", ms: int = 4500):
        self.setObjectName(f"toast{kind.capitalize()}")
        _repolish(self)
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        self.move(parent.width() - self.width() - SP["xl"], parent.height() - self.height() - 56)
        self.raise_()
        self.show()
        self._timer.start(ms)

    def mousePressEvent(self, event):
        self.hide()


class DotGripWidget(QWidget):
    """
    Grip de redimensión con puntos en la esquina inferior derecha.
    bg_color : None = transparente | THEME["status_bg"] = sobre la status bar.
    dot_color: None → THEME["status_text"] si hay bg_color, THEME["text_muted"] si es transparente.
    """
    def __init__(self, parent=None, bg_color=None, dot_color=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._bg_color = bg_color
        if dot_color is None:
            dot_color = THEME["status_text"] if bg_color else THEME["text_muted"]
        self._dot_color = QColor(dot_color)
        self._hovered = self._dragging = False
        self._drag_pos = self._drag_size = None
        self.setMouseTracking(True)

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = _global_pos(e)
            self._drag_size = self.window().size()

    def mouseMoveEvent(self, e):
        if self._dragging:
            d = _global_pos(e) - self._drag_pos
            win = self.window()
            win.resize(
                max(win.minimumWidth(), self._drag_size.width() + d.x()),
                max(win.minimumHeight(), self._drag_size.height() + d.y()),
            )

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._bg_color:
            p.fillRect(self.rect(), QColor(self._bg_color))
        dot_r, spacing, cols, rows = 2, 5, 3, 3
        ox = self.width() - cols * spacing + 1
        oy = self.height() - rows * spacing + 1
        color = QColor(self._dot_color)
        color.setAlpha(220 if self._hovered else 130)
        if self._hovered:
            halo = QColor(self._dot_color)
            halo.setAlpha(30)
            p.setPen(QPen(halo, 0))
            p.setBrush(halo)
            p.drawEllipse(0, 0, self.width(), self.height())
        p.setPen(QPen(color, 0))
        p.setBrush(color)
        for row in range(rows):
            for col in range(cols):
                if row + col < 2:
                    continue
                p.drawEllipse(ox + col * spacing - dot_r, oy + row * spacing - dot_r, dot_r * 2, dot_r * 2)
