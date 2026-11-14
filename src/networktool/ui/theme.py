"""Sistema de diseño v6.3: escalas, temas Grafito / Papel, stylesheet global y
helpers de componentes (tarjetas, badges, KPI, log, estado vacío, ayuda contextual).

Todo color sale de THEME["clave"]; todo espaciado de SP. El stylesheet se aplica una
sola vez sobre la QApplication desde setup_appearance(app).
"""

import logging
import os
import subprocess
import sys
import tempfile
import traceback

from networktool.common import APP_NAME, APP_ORG, APP_VERSION, IS_MACOS, IS_WINDOWS
from networktool.i18n import install_qt_translations, tr, tr_opt
from networktool.qt_compat import (
    QAction, QApplication, QByteArray, QCheckBox, QColor, QComboBox, QDesktopServices, QEvent, QFont,
    QFontDatabase, QFrame, QGraphicsOpacityEffect, QGuiApplication, QHBoxLayout, QIcon, QImage, QLabel,
    QMainWindow, QMessageBox, QMimeDatabase, QObject, QPainter, QPalette, QPen, QPixmap, QPlainTextEdit,
    QPointF, QPropertyAnimation, QPushButton, QRadioButton, QRectF, QSettings, QSize, QSizePolicy,
    QSvgRenderer, QTabBar, QThread, QTimer, QToolButton, QUrl, QVBoxLayout, QWidget, Qt, Signal, _exec,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  ESCALAS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SP = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}          # espaciado

ICON_SIZE = {"sm": 16, "md": 20, "lg": 24, "xl": 40}            # íconos

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  TEMAS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THEMES = {
    # ── GRAFITO (oscuro) ────────────────────────────────────────────────
    "dark": {
        # Superficies
        "bg": "#1e1f22", "bg_panel": "#26282c", "bg_input": "#2c2e33",
        "bg_alt": "#232528", "bg_hover": "#33363b",
        # Bordes
        "border": "#3a3d43", "border_strong": "#4b4f56",
        "control_border": "#7b808a",      # checkbox/radio/zona de soltar: ≥ 3:1
        # Acento
        "accent": "#2b7bd0", "accent_hover": "#3a8ae0", "accent_pressed": "#2366b0",
        "accent_soft": "#1e3550", "accent_soft_hover": "#25426a",
        "accent_border": "#3a6ea6", "accent_text": "#e8f1fb",
        "selection": "#1f4a73", "selection_text": "#ffffff",
        # Botones neutros
        "btn_bg": "#303237", "btn_bg_hover": "#3a3d43",
        # Texto
        "text": "#dfe1e5", "text_secondary": "#a4a9b1", "text_muted": "#7a808a",
        "text_on_accent": "#ffffff", "field_label": "#f2f3f5",
        # Barra de estado
        "status_bg": "#2b7bd0", "status_text": "#ffffff",
        # Botones semánticos
        "start_bg": "#1f3d2a", "start_border": "#3fa968", "start_hover": "#275034", "start_text": "#dff2e5",
        "stop_bg":  "#4a2224", "stop_border":  "#e0625a", "stop_hover":  "#5a2a2c", "stop_text":  "#fbe6e4",
        # Datos / estados
        "ip": "#6cb0f0", "ok": "#5cc99a", "error": "#f0857a", "counter": "#e2bd72",
        # Fondos suaves (badges, avisos)
        "ok_soft": "#1d3a2c", "error_soft": "#452426", "warn_soft": "#3e3420", "info_soft": "#1f3550",
        # Deshabilitado
        "disabled_bg": "#2a2c30", "disabled_text": "#70757d",
        # Tipos de archivo — SOLO para íconos de archivos (sección 8)
        "ft_folder": "#e0b04f", "ft_blue": "#6aa7e8", "ft_green": "#5cbf7f", "ft_red": "#ec7468",
        "ft_orange": "#ee9a55", "ft_brown": "#c9a074", "ft_purple": "#b293e6", "ft_teal": "#4fc1c0",
        "ft_pink": "#e57fb0", "ft_gray": "#9aa0a8",
        # Terminal (sesiones SSH / Telnet / WSL) — propio de NetworkTool
        "term_bg": "#18191b", "term_fg": "#dfe1e5", "term_cursor": "#6cb0f0",
        "ansi": ["#2c2e33", "#f0857a", "#5cc99a", "#e2bd72", "#6cb0f0", "#c792ea", "#5fc4d0", "#dfe1e5",
                 "#62666e", "#ff9e94", "#7fe0b3", "#f2d08e", "#8cc4ff", "#ddb0f5", "#86dde6", "#f2f3f5"],
    },
    # ── PAPEL (claro: blanco grisáceo neutro, apagado para descansar la vista) ──
    "light": {
        # Superficies: gris perla neutro (sin tinte marrón/amarillo). Inputs casi blancos.
        "bg": "#e4e5e3", "bg_panel": "#f0f0ee", "bg_input": "#f9f9f8",
        "bg_alt": "#eaebe9", "bg_hover": "#dddedb",
        # Bordes
        "border": "#c6c7c3", "border_strong": "#a6a8a3",
        "control_border": "#7e807b",      # checkbox/radio/zona de soltar: ≥ 3:1
        # Acento
        "accent": "#1d62a3", "accent_hover": "#2771b5", "accent_pressed": "#174f85",
        "accent_soft": "#e1ebf5", "accent_soft_hover": "#d2e1f1",
        "accent_border": "#7ea3cb", "accent_text": "#232528",
        "selection": "#c9dbef", "selection_text": "#1b1c1e",
        # Botones neutros
        "btn_bg": "#e2e3e0", "btn_bg_hover": "#d6d7d3",
        # Texto: gris grafito, nunca negro puro
        "text": "#232528", "text_secondary": "#45484d", "text_muted": "#5e6167",
        "text_on_accent": "#ffffff", "field_label": "#232528",
        # Barra de estado
        "status_bg": "#1d62a3", "status_text": "#ffffff",
        # Botones semánticos
        "start_bg": "#d7eadc", "start_border": "#3a8d55", "start_hover": "#c8e1ce", "start_text": "#1a4427",
        "stop_bg":  "#f3dbd7", "stop_border":  "#c4554a", "stop_hover":  "#ecccc6", "stop_text":  "#62201a",
        # Datos / estados
        "ip": "#1b5794", "ok": "#1b6b43", "error": "#a52e24", "counter": "#7d5200",
        # Fondos suaves (badges, avisos)
        "ok_soft": "#d4e8db", "error_soft": "#f2d9d5", "warn_soft": "#f0e4c8", "info_soft": "#d5e3f2",
        # Deshabilitado (legible, pero claramente inactivo)
        "disabled_bg": "#dddedb", "disabled_text": "#76787a",
        # Tipos de archivo — SOLO para íconos de archivos (sección 8)
        "ft_folder": "#9a6a0c", "ft_blue": "#2465a8", "ft_green": "#2a7d47", "ft_red": "#b8352b",
        "ft_orange": "#b25a12", "ft_brown": "#86602f", "ft_purple": "#7a4fb8", "ft_teal": "#1c7a79",
        "ft_pink": "#ad3e78", "ft_gray": "#686b70",
        # Terminal (sesiones SSH / Telnet / WSL) — propio de NetworkTool
        "term_bg": "#f9f9f8", "term_fg": "#232528", "term_cursor": "#1d62a3",
        "ansi": ["#232528", "#a52e24", "#1b6b43", "#7d5200", "#1b5794", "#7a3e9d", "#1f6f78", "#c6c7c3",
                 "#5e6167", "#c4554a", "#3a8d55", "#9a6a00", "#1d62a3", "#9450c0", "#2a8a95", "#eaebe9"],
    },
}


def get_theme_name() -> str:
    """Lee el tema guardado. Default: 'dark'. Ignora valores inválidos."""
    name = QSettings(APP_ORG, APP_NAME).value("theme", "dark")
    return name if name in THEMES else "dark"


def set_theme_name(name: str) -> None:
    """Guarda el tema elegido. No se aplica hasta el próximo inicio."""
    QSettings(APP_ORG, APP_NAME).setValue("theme", name)


THEME_NAME = get_theme_name()
THEME = THEMES[THEME_NAME]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  FUENTES, ÍCONOS, PALETA, CURSOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UI_FONT_CANDIDATES = ["Segoe UI", "Inter", "Noto Sans", "Ubuntu", "Cantarell", "DejaVu Sans", "Arial"]
MONO_FONT_CANDIDATES = ["Cascadia Mono", "Consolas", "JetBrains Mono", "Noto Sans Mono",
                        "Ubuntu Mono", "DejaVu Sans Mono", "Courier New"]
FONTS = {"ui": "Arial", "mono": "Courier New"}


def _font_families() -> set:
    try:
        return set(QFontDatabase.families())       # PySide6 (estático)
    except TypeError:
        return set(QFontDatabase().families())     # PySide2 (instancia)


def pick_font(candidates) -> str:
    """Devuelve la primera fuente instalada de la lista."""
    available = _font_families()
    for name in candidates:
        if name in available:
            return name
    return candidates[-1]


def mono_font(px: int = 12) -> QFont:
    f = QFont(FONTS["mono"])
    f.setPixelSize(px)
    f.setStyleHint(QFont.Monospace)
    return f


def _draw_icon(path: str, size: int, kind: str, color: str) -> None:
    s = size / 16.0
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 1.8 * s)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    segments = {
        "check": [[(3.5, 8.5), (6.5, 11.5), (12.5, 5.0)]],
        "down":  [[(4.5, 6.5), (8.0, 10.0), (11.5, 6.5)]],
        "up":    [[(4.5, 9.5), (8.0, 6.0), (11.5, 9.5)]],
        "right": [[(6.5, 4.5), (10.0, 8.0), (6.5, 11.5)]],
        "close": [[(5.0, 5.0), (11.0, 11.0)], [(11.0, 5.0), (5.0, 11.0)]],
    }[kind]
    for pts in segments:
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            p.drawLine(QPointF(x1 * s, y1 * s), QPointF(x2 * s, y2 * s))
    p.end()
    img.save(path, "PNG")


def build_theme_icons(t: dict, theme_name: str) -> dict:
    folder = os.path.join(tempfile.gettempdir(), "estebankzl_ui", f"{APP_NAME}_{theme_name}")
    os.makedirs(folder, exist_ok=True)
    spec = {
        "check":          ("check", t["text_on_accent"]),
        "arrow_down":     ("down",  t["text_secondary"]),
        "arrow_up":       ("up",    t["text_secondary"]),
        "arrow_right":    ("right", t["text_secondary"]),
        "arrow_down_dis": ("down",  t["disabled_text"]),
        "arrow_up_dis":   ("up",    t["disabled_text"]),
        "close":          ("close", t["text_muted"]),
        "close_hover":    ("close", t["text"]),
    }
    paths = {}
    for name, (kind, color) in spec.items():
        base = os.path.join(folder, f"{name}.png")
        _draw_icon(base, 16, kind, color)
        _draw_icon(os.path.join(folder, f"{name}@2x.png"), 32, kind, color)  # HiDPI
        paths[name] = base.replace("\\", "/")   # QSS requiere barras normales
    return paths


def apply_palette(app, t: dict) -> None:
    pal = QPalette()
    roles = {
        QPalette.Window: t["bg"],            QPalette.WindowText: t["text"],
        QPalette.Base: t["bg_input"],        QPalette.AlternateBase: t["bg_alt"],
        QPalette.Text: t["text"],            QPalette.Button: t["btn_bg"],
        QPalette.ButtonText: t["text"],      QPalette.Highlight: t["selection"],
        QPalette.HighlightedText: t["selection_text"],
        QPalette.ToolTipBase: t["bg_panel"], QPalette.ToolTipText: t["text"],
        QPalette.Link: t["accent"],
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    if hasattr(QPalette, "PlaceholderText"):
        pal.setColor(QPalette.PlaceholderText, QColor(t["text_muted"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(t["disabled_text"]))
    app.setPalette(pal)


class _HandCursorFilter(QObject):
    """Pone cursor de mano en todo control clickeable, una vez, al pulirse."""
    _CLICKABLE = (QPushButton, QToolButton, QCheckBox, QRadioButton, QComboBox, QTabBar)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Polish and isinstance(obj, self._CLICKABLE):
            if not obj.testAttribute(Qt.WA_SetCursor):   # respeta cursores puestos a mano
                obj.setCursor(Qt.PointingHandCursor)
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  STYLESHEET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_stylesheet(t: dict, icons: dict, fonts: dict) -> str:
    return f"""
/* ═══════════════ BASE ═══════════════ */
QWidget {{
    color: {t['text']};
    font-family: "{fonts['ui']}";
    font-size: 13px;
    outline: none;
}}
QMainWindow, QDialog {{ background-color: {t['bg']}; }}
QWidget#central      {{ background-color: {t['bg']}; }}

/* ═══════════════ ENCABEZADO ═══════════════ */
QFrame#headerBar {{
    background-color: {t['bg_panel']};
    border: none;
    border-bottom: 1px solid {t['border_strong']};
}}
QLabel#lblAppTitle    {{ font-size: 17px; font-weight: 600; color: {t['text']}; }}
QLabel#lblAppSubtitle {{ font-size: 12px; color: {t['text_secondary']}; }}

/* ═══════════════ TIPOGRAFÍA ═══════════════ */
QLabel {{ color: {t['text']}; background-color: transparent; }}
QLabel:disabled {{ color: {t['disabled_text']}; }}
QLabel#lblTitle    {{ font-size: 18px; font-weight: 600; }}
QLabel#lblSubtitle, QLabel#lblHint {{ font-size: 12px; color: {t['text_secondary']}; }}
QLabel#lblSection  {{ font-size: 12px; font-weight: 600; color: {t['text_secondary']}; }}
QLabel#lblKpi      {{ font-size: 24px; font-weight: 600; color: {t['text']}; }}
QLabel#lblKpiCaption {{ font-size: 12px; color: {t['text_secondary']}; }}
QLabel#emptyState  {{ font-size: 13px; color: {t['text_secondary']}; }}
QLabel#fieldError  {{ font-size: 12px; color: {t['error']}; }}

/* ═══════════════ TARJETAS Y SEPARADORES ═══════════════ */
QFrame#card {{
    background-color: {t['bg_panel']};
    border: 1px solid {t['border']};
    border-radius: 8px;
}}
QFrame#divider {{
    background-color: {t['border']};
    border: none;
    min-height: 1px; max-height: 1px;
}}

/* ═══════════════ BADGES ═══════════════ */
QLabel#badgeOk, QLabel#badgeError, QLabel#badgeWarn, QLabel#badgeInfo, QLabel#badgeNeutral {{
    border-radius: 10px; padding: 2px 10px; font-size: 12px; font-weight: 600;
}}
QLabel#badgeOk      {{ background-color: {t['ok_soft']};    color: {t['ok']}; }}
QLabel#badgeError   {{ background-color: {t['error_soft']}; color: {t['error']}; }}
QLabel#badgeWarn    {{ background-color: {t['warn_soft']};  color: {t['counter']}; }}
QLabel#badgeInfo    {{ background-color: {t['info_soft']};  color: {t['ip']}; }}
QLabel#badgeNeutral {{ background-color: {t['bg_hover']};   color: {t['text_secondary']}; border: 1px solid {t['border']}; }}

/* ═══════════════ GROUPBOX ═══════════════ */
/* El título vive en el margen superior, ENCIMA del borde: no necesita "cortar" la línea. */
QGroupBox {{
    background-color: {t['bg_panel']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    margin-top: 24px;
    padding: 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 4px; top: 2px; padding: 0 2px;
    color: {t['accent']};
    background-color: transparent;
}}

/* ═══════════════ BOTONES ═══════════════ */
QPushButton {{
    background-color: {t['btn_bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 7px 14px;
    color: {t['text']};
    font-weight: 600;
}}
QPushButton:hover    {{ background-color: {t['btn_bg_hover']}; border-color: {t['border_strong']}; }}
QPushButton:pressed  {{ background-color: {t['bg_hover']}; }}
QPushButton:focus    {{ border-color: {t['accent']}; }}
QPushButton:disabled {{ background-color: {t['disabled_bg']}; color: {t['disabled_text']}; border-color: {t['border']}; }}

QPushButton#btnPrimary {{
    background-color: {t['accent']}; border: 1px solid {t['accent']}; color: {t['text_on_accent']};
    padding: 7px 18px;
}}
QPushButton#btnPrimary:hover    {{ background-color: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
QPushButton#btnPrimary:pressed  {{ background-color: {t['accent_pressed']}; border-color: {t['accent_pressed']}; }}
QPushButton#btnPrimary:disabled {{ background-color: {t['disabled_bg']}; color: {t['disabled_text']}; border-color: {t['border']}; }}

QPushButton#btnStart, QPushButton#btnConnect {{
    background-color: {t['start_bg']}; border: 1px solid {t['start_border']}; color: {t['start_text']};
}}
QPushButton#btnStart:hover,    QPushButton#btnConnect:hover    {{ background-color: {t['start_hover']}; }}
QPushButton#btnStart:pressed,  QPushButton#btnConnect:pressed  {{ background-color: {t['start_border']}; color: {t['text_on_accent']}; }}
QPushButton#btnStart:disabled, QPushButton#btnConnect:disabled {{
    background-color: {t['disabled_bg']}; color: {t['disabled_text']}; border-color: {t['border']};
}}

QPushButton#btnStop, QPushButton#btnDisconnect, QPushButton#btnDanger {{
    background-color: {t['stop_bg']}; border: 1px solid {t['stop_border']}; color: {t['stop_text']};
}}
QPushButton#btnStop:hover,    QPushButton#btnDisconnect:hover, QPushButton#btnDanger:hover {{ background-color: {t['stop_hover']}; }}
QPushButton#btnStop:pressed,  QPushButton#btnDisconnect:pressed, QPushButton#btnDanger:pressed {{ background-color: {t['stop_border']}; color: {t['text_on_accent']}; }}
QPushButton#btnStop:disabled, QPushButton#btnDisconnect:disabled, QPushButton#btnDanger:disabled {{
    background-color: {t['disabled_bg']}; color: {t['disabled_text']}; border-color: {t['border']};
}}

/* Secundario: acciones de apoyo ("Actualizar", "Perfiles", "Limpiar", "Más"). SIEMPRE con forma de botón:
   fondo azul suave + borde + texto azul. btnGhost (v5.0–5.3) queda como alias con el mismo aspecto,
   así las apps que ya lo usan se corrigen solo con actualizar el stylesheet. */
QPushButton#btnSecondary, QPushButton#btnGhost {{
    background-color: {t['accent_soft']};
    border: 1px solid {t['accent_border']};
    color: {t['accent_text']};
}}
QPushButton#btnSecondary:hover, QPushButton#btnGhost:hover {{
    background-color: {t['accent_soft_hover']}; border-color: {t['accent']};
}}
QPushButton#btnSecondary:pressed, QPushButton#btnGhost:pressed {{
    background-color: {t['accent']}; border-color: {t['accent']}; color: {t['text_on_accent']};
}}
QPushButton#btnSecondary:disabled, QPushButton#btnGhost:disabled {{
    background-color: {t['disabled_bg']}; border-color: {t['border']}; color: {t['disabled_text']};
}}

/* Botones con menú desplegable ("Exportar ▾", "Más ▾"): flecha del tema, con aire a la derecha */
QPushButton[hasMenu="true"] {{ padding-right: 28px; }}
QPushButton::menu-indicator {{
    image: url("{icons['arrow_down']}");
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 12px; height: 12px; right: 8px;
}}
QPushButton::menu-indicator:disabled {{ image: url("{icons['arrow_down_dis']}"); }}

/* Botón compacto dentro de celdas de tabla */
QPushButton#btnTable {{
    background-color: {t['accent']}; border: none; border-radius: 4px;
    padding: 3px 10px; color: {t['text_on_accent']}; font-size: 12px;
}}
QPushButton#btnTable:hover   {{ background-color: {t['accent_hover']}; }}
QPushButton#btnTable:pressed {{ background-color: {t['accent_pressed']}; }}

/* Botones con ícono: el ícono va a la izquierda con 8 px de aire */
QPushButton[hasIcon="true"] {{ padding-left: 10px; }}

/* QToolButton: barras de herramientas y botones solo-ícono */
QToolButton {{
    background-color: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 5px 8px; color: {t['text']};
}}
QToolButton:hover    {{ background-color: {t['bg_hover']}; border-color: {t['border']}; }}
QToolButton:pressed, QToolButton:checked {{ background-color: {t['accent_soft']}; border-color: {t['accent_border']}; }}
QToolButton:disabled {{ color: {t['disabled_text']}; }}
QToolButton#btnIcon  {{ padding: 5px; }}
QToolButton[popupMode="2"] {{ padding-right: 22px; }}
QToolButton::menu-indicator {{
    image: url("{icons['arrow_down']}");
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 10px; height: 10px; right: 6px;
}}

/* ═══════════════ BARRA DE HERRAMIENTAS ═══════════════ */
QToolBar {{
    background-color: {t['bg_panel']};
    border: none;
    border-bottom: 1px solid {t['border']};
    padding: 4px 12px;
    spacing: 4px;
}}
QToolBar::separator {{ background-color: {t['border']}; width: 1px; margin: 6px 6px; }}

/* ═══════════════ INPUTS ═══════════════ */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 6px 8px;
    color: {t['text']};
    selection-background-color: {t['selection']};
    selection-color: {t['selection_text']};
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{ border-color: {t['border_strong']}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {t['accent']}; }}
QLineEdit:read-only {{ background-color: {t['bg_alt']}; color: {t['text_secondary']}; }}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
    background-color: {t['disabled_bg']}; color: {t['disabled_text']};
}}
/* Validación: set_field_error(widget, mensaje) pone invalid=true */
QLineEdit[invalid="true"], QComboBox[invalid="true"], QSpinBox[invalid="true"],
QDoubleSpinBox[invalid="true"], QPlainTextEdit[invalid="true"] {{ border: 1px solid {t['error']}; }}

QPlainTextEdit#logView, QTextEdit#logView {{
    font-family: "{fonts['mono']}";
    font-size: 12px;
    background-color: {t['bg_alt']};
    padding: 8px 10px;
}}

QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 5px 8px;
    color: {t['text']};
    min-height: 20px;
}}
QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {t['border_strong']}; }}
QComboBox:focus, QComboBox:on, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {t['accent']}; }}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {t['disabled_bg']}; color: {t['disabled_text']};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 26px; border: none;
}}
QComboBox::down-arrow          {{ image: url("{icons['arrow_down']}");     width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url("{icons['arrow_down_dis']}"); }}
QComboBox QAbstractItemView {{
    background-color: {t['bg_panel']};
    border: 1px solid {t['border']};
    padding: 4px;
    outline: none;
    selection-background-color: {t['selection']};
    selection-color: {t['selection_text']};
}}

QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border: none; background: transparent; margin: 2px 2px 0 0;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border: none; background: transparent; margin: 0 2px 2px 0;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {t['bg_hover']}; border-radius: 4px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow       {{ image: url("{icons['arrow_up']}");   width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow   {{ image: url("{icons['arrow_down']}"); width: 10px; height: 10px; }}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled     {{ image: url("{icons['arrow_up_dis']}"); }}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{ image: url("{icons['arrow_down_dis']}"); }}

/* ═══════════════ CHECKBOX / RADIO ═══════════════ */
QCheckBox, QRadioButton {{
    color: {t['text']}; spacing: 8px; background-color: transparent;
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t['disabled_text']}; }}
/* Mismo indicador para QCheckBox y para las casillas dentro de listas, árboles y tablas */
QCheckBox::indicator, QAbstractItemView::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    background-color: {t['bg_input']}; border: 1px solid {t['control_border']};
}}
QCheckBox::indicator:hover, QAbstractItemView::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{
    background-color: {t['accent']}; border-color: {t['accent']};
    image: url("{icons['check']}");
}}
QCheckBox::indicator:checked:hover, QAbstractItemView::indicator:checked:hover {{ background-color: {t['accent_hover']}; }}
QCheckBox::indicator:disabled, QAbstractItemView::indicator:disabled {{
    background-color: {t['disabled_bg']}; border-color: {t['border_strong']};
}}

QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 8px;
    background-color: {t['bg_input']}; border: 1px solid {t['control_border']};
}}
QRadioButton::indicator:hover   {{ border-color: {t['accent']}; }}
QRadioButton::indicator:checked {{
    background-color: {t['text_on_accent']}; border: 5px solid {t['accent']};
    width: 8px; height: 8px;
}}
QRadioButton::indicator:disabled {{ background-color: {t['disabled_bg']}; border-color: {t['border_strong']}; }}

/* ═══════════════ PROGRESS BAR ═══════════════ */
QProgressBar {{
    background-color: {t['bg_alt']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    min-height: 16px;
    text-align: center;
    color: {t['text']};
    font-size: 12px;
}}
QProgressBar::chunk {{ background-color: {t['accent']}; border-radius: 5px; }}

/* ═══════════════ TABLAS / LISTAS / ÁRBOLES ═══════════════ */
QTableView, QListView, QTreeView {{
    background-color: {t['bg_panel']};
    alternate-background-color: {t['bg_alt']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    gridline-color: {t['border']};
    selection-background-color: {t['selection']};
    selection-color: {t['selection_text']};
    outline: none;
}}
QTableView::item, QListView::item, QTreeView::item {{ padding: 4px 8px; border: none; }}
QTableView::item:hover, QListView::item:hover, QTreeView::item:hover {{ background-color: {t['bg_hover']}; }}
QTableView::item:selected, QListView::item:selected, QTreeView::item:selected {{
    background-color: {t['selection']}; color: {t['selection_text']};
}}
QHeaderView {{ background-color: transparent; border: none; }}
QHeaderView::section {{
    background-color: {t['bg_panel']};
    color: {t['text_secondary']};
    border: none;
    border-bottom: 1px solid {t['border_strong']};
    border-right: 1px solid {t['border']};
    padding: 7px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QHeaderView::section:last {{ border-right: none; }}
QHeaderView::down-arrow, QHeaderView::up-arrow {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 10px; height: 10px; right: 6px;
}}
QHeaderView::down-arrow {{ image: url("{icons['arrow_down']}"); }}
QHeaderView::up-arrow   {{ image: url("{icons['arrow_up']}"); }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:has-children:closed {{ image: url("{icons['arrow_right']}"); }}
QTreeView::branch:has-children:open   {{ image: url("{icons['arrow_down']}"); }}
QTableCornerButton::section {{ background-color: {t['bg_panel']}; border: none; }}

/* ═══════════════ TABS — cuadrados, acento arriba ═══════════════ */
QTabWidget::pane {{
    border: 1px solid {t['border']};
    background-color: {t['bg_panel']};
    top: -1px;
}}
QTabBar::tab {{
    background-color: {t['bg_alt']};
    color: {t['text_secondary']};
    border: 1px solid {t['border']};
    border-bottom: none;
    border-radius: 0;
    padding: 7px 16px;
    margin-right: -1px;
}}
QTabBar::tab:hover    {{ background-color: {t['bg_hover']}; color: {t['text']}; }}
QTabBar::tab:selected {{
    background-color: {t['bg_panel']};
    color: {t['text']};
    border-top: 2px solid {t['accent']};
    font-weight: 600;
}}
QTabBar::tab:disabled {{ color: {t['disabled_text']}; }}
QTabBar::close-button       {{ image: url("{icons['close']}"); subcontrol-position: right; margin: 2px; }}
QTabBar::close-button:hover {{ image: url("{icons['close_hover']}"); background-color: {t['bg_hover']}; border-radius: 3px; }}

/* ═══════════════ SCROLLBARS (finas, discretas) ═══════════════ */
QScrollBar:vertical   {{ background: transparent; width: 10px;  margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical   {{ background: {t['border_strong']}; min-height: 28px; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border_strong']}; min-width: 28px;  border-radius: 4px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {t['text_secondary']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ═══════════════ SPLITTER ═══════════════ */
QSplitter::handle            {{ background-color: {t['border_strong']}; }}
QSplitter::handle:hover      {{ background-color: {t['accent']}; }}
QSplitter::handle:horizontal {{ width: 4px; margin: 0 4px; border-radius: 2px; }}
QSplitter::handle:vertical   {{ height: 4px; margin: 4px 0; border-radius: 2px; }}

/* ═══════════════ STATUS BAR ═══════════════ */
QStatusBar {{
    background-color: {t['status_bg']};
    color: {t['status_text']};
    font-size: 12px;
    font-weight: 600;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {t['status_text']}; background-color: transparent; }}

/* ═══════════════ MENÚS ═══════════════ */
QMenuBar {{
    background-color: {t['bg_panel']};
    color: {t['text']};
    border-bottom: 1px solid {t['border']};
}}
QMenuBar::item          {{ padding: 5px 10px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background-color: {t['bg_hover']}; }}
QMenu {{
    background-color: {t['bg_panel']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item          {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
QMenu::icon          {{ padding-left: 8px; }}
QMenu::item:selected {{ background-color: {t['selection']}; color: {t['selection_text']}; }}
QMenu::item:disabled {{ color: {t['disabled_text']}; }}
QMenu::separator     {{ height: 1px; background-color: {t['border']}; margin: 4px 8px; }}

/* ═══════════════ DIÁLOGOS Y TOOLTIPS ═══════════════ */
QMessageBox {{ background-color: {t['bg']}; }}
QMessageBox QLabel {{ color: {t['text']}; background-color: transparent; }}
/* ═══════════════ NAVEGACIÓN LATERAL ═══════════════ */
QFrame#sidebar {{
    background-color: {t['bg_panel']};
    border: none;
    border-right: 1px solid {t['border']};
}}
QListWidget#sideNav {{
    background-color: transparent; border: none; outline: none; padding: 0;
}}
QListWidget#sideNav::item {{
    padding: 7px 10px; margin: 1px 0; border-radius: 6px; color: {t['text_secondary']};
}}
QListWidget#sideNav::item:hover    {{ background-color: {t['bg_hover']}; color: {t['text']}; }}
QListWidget#sideNav::item:selected {{
    background-color: {t['accent_soft']}; color: {t['text']}; font-weight: 600;
}}

/* ═══════════════ EXPLORADOR: barra de ruta ═══════════════ */
QFrame#pathBar {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    border-radius: 6px;
}}
QFrame#pathBar:hover {{ border-color: {t['border_strong']}; }}
QToolButton#crumb {{ padding: 3px 6px; color: {t['text_secondary']}; border-radius: 4px; }}
QToolButton#crumb:hover {{ color: {t['text']}; }}
QToolButton#crumbCurrent {{ padding: 3px 6px; color: {t['text']}; font-weight: 600; border-radius: 4px; }}
QLineEdit#pathEdit {{ border: none; background: transparent; padding: 4px 6px; }}

/* ═══════════════ ZONA PARA SOLTAR ARCHIVOS ═══════════════ */
QFrame#dropZone {{
    background-color: {t['bg_alt']};
    border: 2px dashed {t['control_border']};
    border-radius: 8px;
}}
QLabel#dropTitle {{ font-weight: 600; }}
QFrame#dropZone:hover, QFrame#dropZone[dragOver="true"] {{
    background-color: {t['accent_soft']};
    border-color: {t['accent']};
}}

/* ═══════════════ AVISOS (banner dentro de la ventana) ═══════════════ */
QFrame#banner {{ border-radius: 6px; border: 1px solid {t['border']}; }}
QFrame#banner[kind="info"]    {{ background-color: {t['info_soft']};  border-color: {t['accent_border']}; }}
QFrame#banner[kind="success"] {{ background-color: {t['ok_soft']};    border-color: {t['ok']}; }}
QFrame#banner[kind="warning"] {{ background-color: {t['warn_soft']};  border-color: {t['counter']}; }}
QFrame#banner[kind="error"]   {{ background-color: {t['error_soft']}; border-color: {t['error']}; }}
QFrame#banner QLabel {{ color: {t['text']}; }}

/* ═══════════════ NOTIFICACIÓN TEMPORAL (toast) ═══════════════ */
QFrame#toast {{
    background-color: {t['bg_panel']};
    border: 1px solid {t['border_strong']};
    border-radius: 8px;
}}

QToolTip {{
    background-color: {t['bg_panel']};
    color: {t['text']};
    border: 1px solid {t['border_strong']};
    border-radius: 4px;
    padding: 5px 8px;
}}

/* ═══════════════ PROPIO DE NETWORKTOOL ═══════════════ */
QWidget#page {{ background-color: {t['bg']}; }}
QLabel#lblField {{ color: {t['text_secondary']}; }}
QFrame#vdivider {{ background-color: {t['border']}; border: none; min-width: 1px; max-width: 1px; }}
QLineEdit#fieldOk    {{ color: {t['ok']};    border-color: {t['ok']};    background-color: {t['ok_soft']}; }}
QLineEdit#fieldError {{ color: {t['error']}; border-color: {t['error']}; background-color: {t['error_soft']}; }}
QTextEdit#reportView {{ background-color: {t['bg_panel']}; }}
QPushButton:checked {{ background-color: {t['selection']}; color: {t['selection_text']}; border-color: {t['accent']}; }}
QPushButton#btnSecondary:checked, QPushButton#btnGhost:checked {{
    background-color: {t['accent']}; border-color: {t['accent']}; color: {t['text_on_accent']};
}}
QPushButton#btnDanger {{ background-color: {t['stop_bg']}; border: 1px solid {t['stop_border']}; color: {t['stop_text']}; }}
QPushButton#btnDanger:hover {{ background-color: {t['stop_hover']}; }}
QPushButton#btnDanger:pressed {{ background-color: {t['stop_border']}; color: {t['text_on_accent']}; }}
QPushButton#btnDanger:disabled {{ background-color: {t['disabled_bg']}; color: {t['disabled_text']}; border-color: {t['border']}; }}
/* Botones de servicio en la tabla del escáner (Conectar) */
QPushButton#btnChip {{
    background-color: {t['accent_soft']}; border: 1px solid {t['accent_border']}; border-radius: 4px;
    padding: 2px 6px; color: {t['accent_text']}; font-size: 12px; font-weight: 600;
}}
QPushButton#btnChip:hover   {{ background-color: {t['accent_soft_hover']}; border-color: {t['accent']}; }}
QPushButton#btnChip:pressed {{ background-color: {t['accent']}; color: {t['text_on_accent']}; }}
QPushButton#btnTableMore {{
    background-color: {t['btn_bg']}; border: 1px solid {t['border']}; border-radius: 4px;
    padding: 2px 6px; color: {t['text']}; font-size: 12px;
}}
QPushButton#btnTableMore:hover {{ background-color: {t['btn_bg_hover']}; }}
/* Panel de sesiones y pestañas de trabajo */
QTreeView#sessionTree {{ border: none; background-color: transparent; }}
QTabWidget#workTabs::pane {{ background-color: {t['bg']}; border: none; border-top: 1px solid {t['border']}; }}
QSplitter#mainSplitter::handle:horizontal {{ background-color: {t['border']}; width: 1px; margin: 0; border-radius: 0; }}
QSplitter#mainSplitter::handle:horizontal:hover {{ background-color: {t['accent']}; }}
QMenu::indicator:checked {{ image: url("{icons['check']}"); background-color: {t['accent']}; border-radius: 3px; width: 14px; height: 14px; }}
QMenu::right-arrow {{ image: url("{icons['arrow_right']}"); width: 10px; height: 10px; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:has-children:closed {{ image: url("{icons['arrow_right']}"); }}
QTreeView::branch:has-children:open   {{ image: url("{icons['arrow_down']}"); }}
QTabBar::close-button {{ image: url("{icons['close']}"); subcontrol-position: right; margin: 2px; }}
QTabBar::close-button:hover {{ image: url("{icons['close_hover']}"); background-color: {t['bg_hover']}; border-radius: 4px; }}
"""


_SVG_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
             'fill="none" stroke="{c}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">')

_FILE_BASE = ('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" '
              'fill="{c}" fill-opacity="0.12"/><path d="M14 3v5h5"/>')

_FOLDER_PATH = ("M3 7a1.5 1.5 0 0 1 1.5-1.5h4.6l2 2.2h8.4A1.5 1.5 0 0 1 21 9.2v8.3"
                "a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z")

_MONITOR = '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M9 20h6M12 16v4"/>'

_WINDOW = '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M6.5 6.5v.01M9 6.5v.01"/>'

_CLOUD = '<path d="M7 18.5a4.5 4.5 0 0 1-.5-9 6 6 0 0 1 11.5 1.5 3.75 3.75 0 0 1 0 7.5z"/>'

_SHIELD = '<path d="M12 3l8 3v6c0 4.5-3.4 7.8-8 9-4.6-1.2-8-4.5-8-9V6z"/>'

_TERM_FRAME = '<path d="M13 19.5H5a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5"/><path d="M7 9.5l2.5 2-2.5 2"/>'

_FOLDER_PART = ('<path d="M13 19H4.5A1.5 1.5 0 0 1 3 17.5v-10A1.5 1.5 0 0 1 4.5 6h4.6l2 2.2h8.4'
                'A1.5 1.5 0 0 1 21 9.7V12"/>')

_LOCK_BADGE = ('<rect x="15" y="16" width="6" height="4.5" rx="1" fill="{c}"/>'           # candado cerrado (relleno)
               '<path d="M16.5 16v-1.5a1.5 1.5 0 0 1 3 0V16"/>')

_OPEN_LOCK_BADGE = '<rect x="15" y="16" width="6" height="4.5" rx="1"/><path d="M16.5 16v-2.8a1.5 1.5 0 0 1 3 0"/>'

_PLUG = '<path d="M9 3v4M15 3v4"/><path d="M6.5 7h11v3a5.5 5.5 0 0 1-11 0z"/><path d="M12 15.5V21"/>'

ICON_SVG = {
    # ── Acciones generales ──
    "search":   '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    "refresh":  '<path d="M20 11a8 8 0 0 0-14.6-4.4L4 8"/><path d="M4 4v4h4"/>'
                '<path d="M4 13a8 8 0 0 0 14.6 4.4L20 16"/><path d="M20 20v-4h-4"/>',
    "settings": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/>'
                '<circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "plus":     '<path d="M12 5v14M5 12h14"/>',
    "minus":    '<path d="M5 12h14"/>',
    "edit":     '<path d="M16.5 4.5a2.1 2.1 0 0 1 3 3L8 19l-4 1 1-4z"/><path d="M14.5 6.5l3 3"/>',
    "trash":    '<path d="M4 7h16"/><path d="M9 7V4.5h6V7"/><path d="M6 7l1 12.5h10L18 7"/><path d="M10 11v5M14 11v5"/>',
    "save":     '<path d="M5 4h11l3 3v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path d="M8 4v5h7V4"/><path d="M8 20v-6h8v6"/>',
    "open":     '<path d="M3 18V6a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v2"/>'
                '<path d="M3 18l2.6-7.2a1 1 0 0 1 1-.8H21l-2.7 7.3a1 1 0 0 1-.9.7H3z"/>',
    "export":   '<path d="M12 15V4"/><path d="M8 8l4-4 4 4"/><path d="M5 14v5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5"/>',
    "import":   '<path d="M12 4v11"/><path d="M8 11l4 4 4-4"/><path d="M5 14v5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5"/>',
    "copy":     '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "close":    '<path d="M6 6l12 12M18 6L6 18"/>',
    "check":    '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "more":     '<circle cx="5" cy="12" r="1.3" fill="{c}"/><circle cx="12" cy="12" r="1.3" fill="{c}"/>'
                '<circle cx="19" cy="12" r="1.3" fill="{c}"/>',
    "filter":   '<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/>',
    "play":     '<path d="M7 5v14l11-7z"/>',
    "stop":     '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "pause":    '<path d="M9 5v14M15 5v14"/>',
    "eye":      '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "link":     '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/>'
                '<path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "lock":     '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "exit":     '<path d="M14 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4"/><path d="M10 16l-4-4 4-4"/><path d="M6 12h10"/>',
    "folder_plus": f'<path d="{_FOLDER_PATH}"/><path d="M12 10.5v5M9.5 13h5"/>',
    # ── Navegación ──
    "chevron_down":  '<path d="M6 9l6 6 6-6"/>',
    "chevron_up":    '<path d="M6 15l6-6 6 6"/>',
    "chevron_left":  '<path d="M15 6l-6 6 6 6"/>',
    "chevron_right": '<path d="M9 6l6 6-6 6"/>',
    "arrow_left":    '<path d="M19 12H5"/><path d="M11 6l-6 6 6 6"/>',
    "arrow_right":   '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    "arrow_up":      '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
    "home":          '<path d="M4 11l8-7 8 7"/><path d="M6 9.5V20h4.5v-5h3v5H18V9.5"/>',
    "list":          '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6v.01M4.5 12v.01M4.5 18v.01"/>',
    "grid":          '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/>'
                     '<rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
    # ── Estado / avisos ──
    "info":     '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.6v.01"/>',
    "warning":  '<path d="M12 3.5L2.8 19.5h18.4z"/><path d="M12 10v4.5"/><path d="M12 17.2v.01"/>',
    "error":    '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "success":  '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16.5 9.5"/>',
    "help":     '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.6v.6"/>'
                '<path d="M12 17v.01"/>',
    "dot":      '<circle cx="12" cy="12" r="4.5" fill="{c}" stroke="none"/>',
    "clock":    '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    # ── Objetos / lugares ──
    "folder":   f'<path d="{_FOLDER_PATH}" fill="{{c}}" fill-opacity="0.18"/>',
    "file":     _FILE_BASE,
    "drive":    '<rect x="3" y="13" width="18" height="7" rx="2"/>'
                '<path d="M5 13l2.2-7.3A1 1 0 0 1 8.2 5h7.6a1 1 0 0 1 1 .7L19 13"/><path d="M7 16.5v.01M10 16.5v.01"/>',
    "monitor":  _MONITOR,
    "terminal": '<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7 9.5l3 2.5-3 2.5"/><path d="M12.5 15h4.5"/>',
    "network":  '<rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/>'
                '<rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4M6 16v-2h12v2"/>',
    "server":   '<rect x="4" y="4" width="16" height="7" rx="1.5"/><rect x="4" y="13" width="16" height="7" rx="1.5"/>'
                '<path d="M8 7.5v.01M8 16.5v.01"/>',
    "user":     '<circle cx="12" cy="8" r="4"/><path d="M4 20c1.5-3.5 4.5-5 8-5s6.5 1.5 8 5"/>',
    "calendar": '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    "chip":     '<rect x="7" y="7" width="10" height="10" rx="1.5"/>'
                '<path d="M10 4v3M14 4v3M10 17v3M14 17v3M4 10h3M4 14h3M17 10h3M17 14h3"/>',
    "language": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
                '<path d="M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/>',
    "moon":     '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "app":      '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M6.5 6.5v.01M9 6.5v.01"/>',
    # ── Red: protocolos y servicios (metáforas genéricas, sin logos de marcas) ──
    "mail":         '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3.5 6.5l8.5 6.5 8.5-6.5"/>',
    "ssh":          _TERM_FRAME + _LOCK_BADGE,
    "telnet":       _TERM_FRAME + _OPEN_LOCK_BADGE,          # candado abierto: sin cifrado
    "sftp":         _FOLDER_PART + _LOCK_BADGE,
    "ftp":          _FOLDER_PART + '<path d="M15.5 21v-6M13.8 16.7l1.7-1.7 1.7 1.7M19.5 15v6M17.8 19.3l1.7 1.7 1.7-1.7"/>',
    "vnc":          _MONITOR + '<path d="M10 7.5v5.5l1.6-1.4 1.2 2.4 1-.5-1.2-2.4h2.2z"/>',
    "rdp":          _MONITOR + '<path d="M9 12.5l5-5M10.5 7.5H14V11"/>',
    "wsl":          _WINDOW + '<path d="M7 12l2.5 2L7 16"/><path d="M11.5 16.5h4.5"/>',
    "web":          _WINDOW + '<circle cx="12" cy="14.5" r="3.2"/><path d="M8.8 14.5h6.4"/>',
    "https":        _WINDOW + '<rect x="9.5" y="13" width="5" height="4" rx="0.8"/><path d="M10.7 13v-1.2a1.3 1.3 0 0 1 2.6 0V13"/>',
    "websocket":    '<path d="M4 9h14"/><path d="M15 6l3 3-3 3"/><path d="M20 15H6"/><path d="M9 12l-3 3 3 3"/>',
    "cloud":        _CLOUD,
    "cloud_sync":   _CLOUD + '<path d="M9.8 14a2.3 2.3 0 0 1 4.1-1.2M14.2 15a2.3 2.3 0 0 1-4.1 1.2"/>'
                             '<path d="M14.2 11.6v1.4h-1.4M9.8 17.4V16h1.4"/>',
    "cloud_folder": _CLOUD + '<path d="M9.3 16.3v-3a.6.6 0 0 1 .6-.6h1.5l.8.8h2.2a.6.6 0 0 1 .6.6v2.2z"/>',
    "cloud_upload": _CLOUD + '<path d="M12 16.8v-4.6M10 14.2l2-2 2 2"/>',
    "share_folder": f'<path d="{_FOLDER_PATH}"/>' + '<circle cx="9.5" cy="14" r="1.2"/><circle cx="14.5" cy="11.8" r="1.2"/>'
                    '<circle cx="14.5" cy="16.2" r="1.2"/><path d="M10.6 13.5l2.8-1.2M10.6 14.5l2.8 1.2"/>',
    "dns":          '<path d="M12 3v18"/><path d="M12 5h6l2 2-2 2h-6"/><path d="M12 11H6l-2 2 2 2h6"/><path d="M9 21h6"/>',
    "tag":          '<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7L21 12.3a1 1 0 0 1 0 1.4l-7.3 7.3a1 1 0 0 1-1.4 0z"/>'
                    '<circle cx="8" cy="8" r="1.5"/>',
    # ── Red: equipos y conexión ──
    "router":       '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 16.5v.01M10 16.5v.01"/><path d="M14.5 16.5h3"/>'
                    '<path d="M16 13V9.5"/><path d="M13.2 7.2a4 4 0 0 1 5.6 0"/><path d="M11.2 5a6.8 6.8 0 0 1 9.6 0"/>',
    "switch":       '<rect x="2.5" y="7" width="19" height="10" rx="2"/>'
                    '<path d="M6 14v-2.5h2.2V14M10.9 14v-2.5h2.2V14M15.8 14v-2.5H18V14"/>',
    "wifi":         '<path d="M2.5 9a14 14 0 0 1 19 0"/><path d="M5.5 12.5a9.5 9.5 0 0 1 13 0"/><path d="M8.7 16a5 5 0 0 1 6.6 0"/>'
                    '<path d="M12 19.5v.01"/>',
    "ethernet":     '<path d="M4 5h16v10h-4v3.5H8V15H4z"/><path d="M8 8v3M10.7 8v3M13.3 8v3M16 8v3"/>',
    "camera":       '<rect x="3" y="7" width="13" height="10" rx="2"/><path d="M16 10.5l5-3v9l-5-3"/>',
    "printer":      '<path d="M7 9V4h10v5"/><rect x="3.5" y="9" width="17" height="7" rx="1.5"/><path d="M7 14h10v6H7z"/>',
    "database":     '<ellipse cx="12" cy="6" rx="7" ry="2.5"/><path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6"/>'
                    '<path d="M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
    "container":    '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
    "laptop":       '<rect x="5" y="5" width="14" height="10" rx="1.2"/><path d="M3 19h18l-2-4H5z"/>',
    "phone":        '<rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 17.5h2"/>',
    "serial":       '<path d="M3 7h18l-2.5 10h-13z"/>'
                    '<path d="M7.5 10.5v.01M10.5 10.5v.01M13.5 10.5v.01M16.5 10.5v.01M9 13.5v.01M12 13.5v.01M15 13.5v.01"/>',
    "usb":          '<path d="M8 3h8v6H8z"/><path d="M10.5 5.5v1M13.5 5.5v1"/>'
                    '<path d="M6.5 9h11v6a3 3 0 0 1-3 3h-5a3 3 0 0 1-3-3z"/><path d="M12 18v3"/>',
    "plug":         _PLUG,
    "unplug":       _PLUG + '<path d="M3.5 3.5l17 17"/>',
    "power":        '<path d="M12 3v8"/><path d="M6.6 6.6a8 8 0 1 0 10.8 0"/>',
    # ── Red: seguridad y diagnóstico ──
    "shield":       _SHIELD,
    "vpn":          _SHIELD + '<rect x="9.25" y="11.5" width="5.5" height="4.5" rx="0.8"/>'
                              '<path d="M10.5 11.5v-1.3a1.5 1.5 0 0 1 3 0v1.3"/>',
    "firewall":     '<rect x="3" y="5" width="18" height="14" rx="1.5"/>'
                    '<path d="M3 9.7h18M3 14.3h18M9 5v4.7M15 5v4.7M6 9.7v4.6M12 9.7v4.6M18 9.7v4.6M9 14.3V19M15 14.3V19"/>',
    "key":          '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9"/><path d="M17 6l2.5 2.5M14.5 8.5l2 2"/>',
    "unlock":       '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
    "certificate":  '<path d="M14 19H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5"/><path d="M7 8.5h10M7 12h5"/>'
                    '<circle cx="18" cy="15.5" r="2.5"/><path d="M16.8 17.7L16 21l2-1 2 1-.8-3.3"/>',
    "activity":     '<path d="M3 12h4l2.5-6 5 12 2.5-6h4"/>',
    "gauge":        '<path d="M4.5 18a9 9 0 1 1 15 0"/><path d="M12 13.5l4-4"/><circle cx="12" cy="13.5" r="1.2"/>',
    "route":        '<circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/>'
                    '<path d="M8 18h7.5a3 3 0 0 0 0-6h-7a3 3 0 0 1 0-6H16"/>',
    "radar":        '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/>'
                    '<circle cx="12" cy="12" r="1" fill="{c}"/>',
    "broadcast":    '<circle cx="12" cy="12" r="2"/>'
                    '<path d="M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8"/>',
    "transfer":     '<path d="M8 20V5M4 9l4-4 4 4"/><path d="M16 4v15M12 15l4 4 4-4"/>',
    # ── Varios ──
    "users":        '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c1-3.3 3.6-5 6.5-5s5.5 1.7 6.5 5"/>'
                    '<path d="M16 4.7a3.5 3.5 0 0 1 0 6.6"/><path d="M18 15.3c1.7.7 3 2.3 3.5 4.7"/>',
    "star":         '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
    "pin":          '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/><path d="M12 14v7"/>',
    "bell":         '<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    # ── Tipos de archivo extra ──
    "file_key":     _FILE_BASE + '<circle cx="10" cy="15.5" r="2"/><path d="M11.5 14l3.5-3.5M14 11.5l1.2 1.2"/>',
    "file_capture": _FILE_BASE + '<path d="M8 15h2l1.2-3 1.8 6 1.2-3H16"/>',
    "file_mail":    _FILE_BASE + '<rect x="8" y="12" width="8" height="6" rx="0.8"/><path d="M8.3 12.5l3.7 2.7 3.7-2.7"/>',
    # ── Tipos de archivo (página + glifo) ──
    "file_text":     _FILE_BASE + '<path d="M9 13h6M9 16.5h6M9 9.5h2"/>',
    "file_doc":      _FILE_BASE + '<path d="M8.5 12h7M8.5 15h7M8.5 18h4.5"/>',
    "file_sheet":    _FILE_BASE + '<rect x="8" y="11.5" width="8" height="6.5" rx="0.5"/><path d="M8 14.75h8M12 11.5v6.5"/>',
    "file_slides":   _FILE_BASE + '<rect x="8" y="11.5" width="8" height="5" rx="0.5"/><path d="M12 16.5v2"/>',
    "file_pdf":      _FILE_BASE + '<path d="M10 18.5v-7h2.25a2 2 0 0 1 0 4H10"/>',
    "file_archive":  _FILE_BASE + '<path d="M10 4.5v1.5M10 8v1.5M10 11.5v1.5"/><rect x="8.5" y="14.5" width="3" height="3.5" rx="0.6"/>',
    "file_image":    _FILE_BASE + '<circle cx="10" cy="12.5" r="1.25"/><path d="M8 18.5l3-3.5 2 2 1.5-1.5 1.5 3"/>',
    "file_audio":    _FILE_BASE + '<path d="M11 17V11l4.5-1.2v5.7"/><circle cx="9.5" cy="17" r="1.5"/><circle cx="14" cy="15.5" r="1.5"/>',
    "file_video":    _FILE_BASE + '<path d="M10 11.5v6l5-3z"/>',
    "file_code":     _FILE_BASE + '<path d="M10 12l-2.2 2.5 2.2 2.5M14 12l2.2 2.5-2.2 2.5"/>',
    "file_config":   _FILE_BASE + '<path d="M8.5 12.5h7M8.5 16.5h7"/>'
                                  '<circle cx="11" cy="12.5" r="1.1" fill="{c}"/><circle cx="13.5" cy="16.5" r="1.1" fill="{c}"/>',
    "file_exec":     _FILE_BASE + '<rect x="8" y="11" width="8" height="7" rx="1"/><path d="M8 13.3h8"/>',
    "file_disk":     _FILE_BASE + '<circle cx="12" cy="15" r="3.5"/><circle cx="12" cy="15" r="0.9"/>',
    "file_db":       _FILE_BASE + '<ellipse cx="12" cy="12" rx="3.5" ry="1.4"/>'
                                  '<path d="M8.5 12v5c0 .8 1.6 1.4 3.5 1.4s3.5-.6 3.5-1.4v-5"/>'
                                  '<path d="M8.5 14.5c0 .8 1.6 1.4 3.5 1.4s3.5-.6 3.5-1.4"/>',
    "file_firmware": _FILE_BASE + '<rect x="9.5" y="12.5" width="5" height="5" rx="0.8"/>'
                                  '<path d="M11 11v1.5M13 11v1.5M11 17.5V19M13 17.5V19M8 14h1.5M8 16h1.5M14.5 14H16M14.5 16H16"/>',
}

_ICON_PIXMAP_SIZES = (16, 20, 24, 32, 40, 48, 64)

_icon_cache = {}


def _svg_pixmap(name: str, color: str, px: int):
    """Renderiza un ícono a un QPixmap de px×px píxeles físicos."""
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    if QSvgRenderer is None or name not in ICON_SVG:
        return pm
    svg = (_SVG_HEAD + ICON_SVG[name] + "</svg>").replace("{c}", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    return pm


def _resolve_color(color: str) -> str:
    """Acepta una clave de THEME ('text_secondary', 'ok', 'ft_red'…) o un hex ya resuelto."""
    return THEME.get(color, color)


def icon(name: str, color: str = "text_secondary") -> "QIcon":
    """
    QIcon nítido en cualquier tamaño y DPI, con estado deshabilitado automático.
    color: clave de THEME. Ej.: icon("save"), icon("success", "ok"), icon("save", "text_on_accent").
    Debe llamarse desde el hilo principal (crea QPixmap).
    """
    key = (name, color)
    if key not in _icon_cache:
        ico = QIcon()
        normal, disabled = _resolve_color(color), THEME["disabled_text"]
        for px in _ICON_PIXMAP_SIZES:
            ico.addPixmap(_svg_pixmap(name, normal, px), QIcon.Normal, QIcon.Off)
            ico.addPixmap(_svg_pixmap(name, disabled, px), QIcon.Disabled, QIcon.Off)
        _icon_cache[key] = ico
    return _icon_cache[key]


def icon_pixmap(name: str, size: int = 16, color: str = "text_secondary"):
    """QPixmap HiDPI para QLabel (avisos, estados vacíos, diálogos)."""
    dpr = QGuiApplication.instance().devicePixelRatio() if QGuiApplication.instance() else 1.0
    pm = _svg_pixmap(name, _resolve_color(color), int(round(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    return pm


def icon_label(name: str, size: int = 16, color: str = "text_secondary") -> "QLabel":
    lbl = QLabel()
    lbl.setPixmap(icon_pixmap(name, size, color))
    lbl.setFixedSize(size, size)
    return lbl


def set_button_icon(btn, name: str, color: str = None) -> None:
    """Ícono en un botón con texto. El color se adapta al tipo de botón."""
    if color is None:
        color = {"btnPrimary": "text_on_accent", "btnTable": "text_on_accent",
                 "btnStart": "start_text", "btnConnect": "start_text",
                 "btnStop": "stop_text", "btnDisconnect": "stop_text", "btnDanger": "stop_text",
                 "btnSecondary": "accent_text"}.get(btn.objectName(), "text_secondary")
    btn.setIcon(icon(name, color))
    btn.setIconSize(QSize(ICON_SIZE["sm"], ICON_SIZE["sm"]))
    btn.setProperty("hasIcon", True)


def make_icon_button(name: str, help_key: str, shortcut: str = None, parent=None) -> "QToolButton":
    """Botón solo-ícono. SOLO para acciones universales (cerrar, buscar, actualizar, configuración,
    más opciones, navegación). Siempre con ayuda contextual."""
    btn = QToolButton(parent)
    btn.setObjectName("btnIcon")
    btn.setIcon(icon(name))
    btn.setIconSize(QSize(ICON_SIZE["sm"], ICON_SIZE["sm"]))
    btn.setAutoRaise(True)
    set_help(btn, help_key, shortcut)
    btn.setAccessibleName(tr_opt(f"tip.{help_key}.title") or tr(f"tip.{help_key}"))
    return btn



PROTOCOL_ICONS = {
    "ssh": "ssh", "sftp": "sftp", "telnet": "telnet", "ftp": "ftp", "rdp": "rdp", "vnc": "vnc",
    "http": "web", "https": "https", "wsl": "wsl", "shell": "terminal",
}


def protocol_icon(proto: str, color: str = "text_secondary") -> "QIcon":
    """Ícono monocromo de un protocolo de sesión (árbol, pestañas, combos)."""
    return icon(PROTOCOL_ICONS.get(proto, "network"), color)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  TIPOS DE ARCHIVO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FILE_CATEGORIES = {
    "folder":   ("folder",        "ft_folder", ()),
    "pdf":      ("file_pdf",      "ft_red",    (".pdf",)),
    "doc":      ("file_doc",      "ft_blue",   (".doc", ".docx", ".docm", ".odt", ".rtf")),
    "sheet":    ("file_sheet",    "ft_green",  (".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv")),
    "slides":   ("file_slides",   "ft_orange", (".ppt", ".pptx", ".odp")),
    "text":     ("file_text",     "ft_gray",   (".txt", ".md", ".log", ".nfo")),
    "code":     ("file_code",     "ft_teal",   (".py", ".pyw", ".js", ".ts", ".html", ".htm", ".css", ".c", ".h",
                                                ".cpp", ".hpp", ".cs", ".java", ".sh", ".bat", ".cmd", ".ps1",
                                                ".lua", ".go", ".rs", ".php", ".sql", ".ino")),
    "config":   ("file_config",   "ft_gray",   (".ini", ".cfg", ".conf", ".json", ".xml", ".yaml", ".yml",
                                                ".toml", ".reg", ".env", ".properties")),
    "archive":  ("file_archive",  "ft_brown",  (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
                                                ".zst", ".cab", ".lz", ".lzh")),
    "image":    ("file_image",    "ft_purple", (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico",
                                                ".svg", ".tif", ".tiff", ".heic", ".psd")),
    "audio":    ("file_audio",    "ft_pink",   (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus")),
    "video":    ("file_video",    "ft_pink",   (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v")),
    "exec":     ("file_exec",     "ft_blue",   (".exe", ".msi", ".appimage", ".deb", ".rpm", ".apk", ".jar", ".lnk")),
    "disk":     ("file_disk",     "ft_gray",   (".iso", ".img", ".dmg", ".vhd", ".vhdx", ".vmdk", ".wim")),
    "database": ("file_db",       "ft_orange", (".db", ".sqlite", ".sqlite3", ".mdb", ".accdb")),
    "firmware": ("file_firmware", "ft_teal",   (".hex", ".bin", ".rom", ".elf", ".fw", ".uf2", ".eep")),
    "key":      ("file_key",      "ft_orange", (".pem", ".crt", ".cer", ".der", ".key", ".pub", ".ppk", ".p12",
                                                ".pfx", ".csr", ".gpg", ".asc")),
    "capture":  ("file_capture",  "ft_teal",   (".pcap", ".pcapng", ".cap", ".har")),
    "mail":     ("file_mail",     "ft_blue",   (".eml", ".msg", ".mbox")),
    "file":     ("file",          "ft_gray",   ()),        # cualquier otro
}

_EXT_TO_CATEGORY = {ext: cat for cat, (_i, _c, exts) in FILE_CATEGORIES.items() for ext in exts}

# Respaldo por tipo MIME para archivos sin extensión o con extensión desconocida
_MIME_TO_CATEGORY = (
    ("application/pdf", "pdf"), ("image/", "image"), ("audio/", "audio"), ("video/", "video"),
    ("application/zip", "archive"), ("application/x-7z", "archive"), ("application/x-rar", "archive"),
    ("application/gzip", "archive"), ("application/x-tar", "archive"),
    ("application/x-executable", "exec"), ("application/x-msdownload", "exec"),
    ("application/x-sqlite3", "database"), ("application/json", "config"), ("text/", "text"),
)

_mime_db = None


def file_category(path: str, is_dir: bool = None, deep: bool = False) -> str:
    """
    Categoría de un archivo ('pdf', 'archive', 'folder'…).
    deep=True: si la extensión no alcanza, mira el CONTENIDO (firma/magic bytes) con QMimeDatabase.
    Para listas grandes usar deep=False (rápido, solo extensión).
    """
    if is_dir is None:
        is_dir = os.path.isdir(path)
    if is_dir:
        return "folder"
    cat = _EXT_TO_CATEGORY.get(os.path.splitext(path)[1].lower())
    if cat:
        return cat
    global _mime_db
    if _mime_db is None:
        _mime_db = QMimeDatabase()
    mode = QMimeDatabase.MatchDefault if deep else QMimeDatabase.MatchExtension
    mime = _mime_db.mimeTypeForFile(path, mode).name()
    for prefix, category in _MIME_TO_CATEGORY:
        if mime.startswith(prefix):
            return category
    return "file"


def file_icon(path: str, is_dir: bool = None) -> "QIcon":
    ico_name, color, _exts = FILE_CATEGORIES[file_category(path, is_dir)]
    return icon(ico_name, color)


def file_type_name(path: str, is_dir: bool = None) -> str:
    """Nombre legible y traducido: 'Documento PDF', 'Archivo comprimido (ZIP)', 'Archivo XYZ'."""
    cat = file_category(path, is_dir)
    ext = os.path.splitext(path)[1].lstrip(".").upper()
    if cat == "file":
        return tr("ftype.generic", ext=ext) if ext else tr("ftype.file")
    name = tr(f"ftype.{cat}")
    if cat in ("archive", "image", "audio", "video", "disk", "firmware") and ext:
        name += f" ({ext})"
    return name


def warm_file_icons() -> None:
    """Crea de antemano todos los íconos de archivo (hilo principal).
    Obligatorio antes de usar FileIconProvider: QFileSystemModel pide íconos desde otro hilo."""
    for ico_name, color, _exts in FILE_CATEGORIES.values():
        icon(ico_name, color)


def remote_file_icon(name: str, is_dir: bool, is_link: bool = False, mode: int = 0) -> "QIcon":
    """Ícono de una entrada remota (SFTP/FTP/WSL): solo por nombre y permisos, sin tocar el disco local."""
    if is_link and not is_dir:
        return icon("link", "ft_gray")
    if is_dir:
        return icon("folder", "ft_folder")
    cat = _EXT_TO_CATEGORY.get(os.path.splitext(name)[1].lower(), "file")
    if cat == "file" and mode & 0o111:
        cat = "exec"
    ico_name, color, _exts = FILE_CATEGORIES[cat]
    return icon(ico_name, color)


def remote_file_type(name: str, is_dir: bool) -> str:
    cat = "folder" if is_dir else _EXT_TO_CATEGORY.get(os.path.splitext(name)[1].lower(), "file")
    ext = os.path.splitext(name)[1].lstrip(".").upper()
    if cat == "file":
        return tr("ftype.generic", ext=ext) if ext else tr("ftype.file")
    return tr(f"ftype.{cat}")


def setup_appearance(app) -> None:
    """Fuente, paleta, glifos de controles, stylesheet, cursor y traducciones. UNA sola vez."""
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    FONTS["ui"] = pick_font(UI_FONT_CANDIDATES)
    FONTS["mono"] = pick_font(MONO_FONT_CANDIDATES)
    base_font = QFont(FONTS["ui"])
    base_font.setPixelSize(13)
    app.setFont(base_font)

    apply_palette(app, THEME)
    icons = build_theme_icons(THEME, THEME_NAME)
    app.setStyleSheet(build_stylesheet(THEME, icons, FONTS))

    app._hand_cursor_filter = _HandCursorFilter(app)   # mantener referencia viva
    app.installEventFilter(app._hand_cursor_filter)

    install_qt_translations(app)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  AYUDA CONTEXTUAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_HELP_WIDGET_TYPES = (QPushButton, QToolButton, QCheckBox, QRadioButton)


def set_help(widget, key: str, shortcut: str = None, **kwargs) -> None:
    """
    Asigna ayuda contextual traducida a un widget o QAction.
      · tip.<key>        → explicación (obligatoria)
      · tip.<key>.title  → título (opcional; en botones/checkbox se usa su propio texto)
    También la copia a la barra de estado (statusTip).
    """
    body = tr(f"tip.{key}", **kwargs)
    title = tr_opt(f"tip.{key}.title")
    if not title and isinstance(widget, _HELP_WIDGET_TYPES + (QAction,)):
        title = widget.text().replace("&", "")
    html = "<qt>"
    if title:
        html += f"<b>{title}</b>"
    if shortcut:
        html += f'&nbsp;&nbsp;&nbsp;<span style="color:{THEME["text_muted"]};">{shortcut}</span>'
    if title or shortcut:
        html += "<br>"
    html += f'<span style="color:{THEME["text_secondary"]};">{body}</span></qt>'
    widget.setToolTip(html)
    widget.setStatusTip(body)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  COMPONENTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _repolish(w) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def make_card(section_title: str = None, spacing: int = SP["md"], header_widget=None):
    """Tarjeta con padding estándar, etiqueta de sección opcional y widget a la derecha del título
    (ej. un botón secundario). Devuelve (frame, layout)."""
    card = QFrame()
    card.setObjectName("card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(SP["lg"], SP["md"] + 2, SP["lg"], SP["lg"])
    lay.setSpacing(spacing)
    if section_title or header_widget:
        row = QHBoxLayout()
        row.setSpacing(SP["sm"])
        if section_title:
            lbl = QLabel(section_title.upper())
            lbl.setObjectName("lblSection")
            row.addWidget(lbl)
        row.addStretch(1)
        if header_widget is not None:
            row.addWidget(header_widget)
        lay.addLayout(row)
    return card, lay


def make_section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("lblSection")
    return lbl


def make_divider(vertical: bool = False) -> QFrame:
    line = QFrame()
    line.setObjectName("vdivider" if vertical else "divider")
    return line


def make_badge(text: str, kind: str = "neutral") -> QLabel:
    """kind: ok | error | warn | info | neutral"""
    lbl = QLabel(text)
    lbl.setObjectName(f"badge{kind.capitalize()}")
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lbl


def set_badge(lbl: QLabel, text: str, kind: str) -> None:
    lbl.setText(text)
    lbl.setObjectName(f"badge{kind.capitalize()}")
    _repolish(lbl)


def make_kpi(value: str, caption: str):
    """Tarjeta KPI: número grande + leyenda. Devuelve (frame, label_valor)."""
    card, lay = make_card(spacing=2)
    lay.setContentsMargins(SP["lg"], SP["sm"], SP["lg"], SP["sm"])
    val = QLabel(value)
    val.setObjectName("lblKpi")
    cap = QLabel(caption)
    cap.setObjectName("lblKpiCaption")
    lay.addWidget(val)
    lay.addWidget(cap)
    return card, val


def make_log_view() -> QPlainTextEdit:
    log = QPlainTextEdit()
    log.setObjectName("logView")
    log.setReadOnly(True)
    log.setMaximumBlockCount(5000)      # evita que crezca sin límite
    return log


class EmptyState(QWidget):
    """Estado vacío: ícono grande apagado + frase útil + botón opcional. Centrado."""

    def __init__(self, text: str, icon_name: str = None, action_button=None):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP["xl"], SP["xl"], SP["xl"], SP["xl"])
        lay.setSpacing(SP["md"])
        lay.addStretch(1)
        if icon_name:
            lay.addWidget(icon_label(icon_name, ICON_SIZE["xl"], "text_muted"), 0, Qt.AlignHCenter)
        self.label = QLabel(text)
        self.label.setObjectName("emptyState")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        lay.addWidget(self.label)
        if action_button is not None:
            lay.addWidget(action_button, 0, Qt.AlignHCenter)
        lay.addStretch(1)

    def setText(self, text: str) -> None:
        self.label.setText(text)


def make_empty_state(text: str, icon_name: str = None, action_button=None) -> "EmptyState":
    return EmptyState(text, icon_name, action_button)


def set_field_error(widget, message: str = None, error_label=None) -> None:
    """Marca (o limpia, con message=None) un campo inválido: borde rojo + mensaje."""
    widget.setProperty("invalid", bool(message))
    _repolish(widget)
    if error_label is not None:
        error_label.setText(message or "")
        error_label.setVisible(bool(message))


def make_error_label() -> "QLabel":
    lbl = QLabel()
    lbl.setObjectName("fieldError")
    lbl.setWordWrap(True)
    lbl.setVisible(False)
    return lbl


def add_search_icon(edit) -> None:
    """Lupa dentro del campo de búsqueda, a la izquierda (sección 7)."""
    edit.addAction(icon("search", "text_muted"), edit.LeadingPosition if hasattr(edit, "LeadingPosition")
                   else edit.ActionPosition.LeadingPosition)


def make_button(text: str, object_name: str = None, help_key: str = None, slot=None,
                shortcut: str = None, icon_name: str = None) -> QPushButton:
    """QPushButton con objectName, ayuda contextual, slot e ícono opcional en una línea."""
    btn = QPushButton(text)
    if object_name:
        btn.setObjectName(object_name)
    if icon_name:
        set_button_icon(btn, icon_name)
    if help_key:
        set_help(btn, help_key, shortcut=shortcut)
    if slot is not None:
        btn.clicked.connect(lambda checked=False: slot())
    return btn


def attach_menu(btn: QPushButton, menu) -> None:
    """Asocia un menú desplegable a un botón (flecha dibujada por el QSS)."""
    menu.setToolTipsVisible(True)
    btn.setMenu(menu)
    btn.setProperty("hasMenu", True)
    _repolish(btn)


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("lblField")
    return lbl


def span(text, color_key: str, bold: bool = True) -> str:
    """Fragmento de rich text con un color semántico del tema."""
    weight = "font-weight:600;" if bold else ""
    return f'<span style="color:{THEME[color_key]};{weight}">{text}</span>'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  MENSAJES Y CONFIRMACIONES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_KIND_ICON = {"info": ("info", "ip"), "success": ("success", "ok"),
              "warning": ("warning", "counter"), "error": ("error", "error"),
              "question": ("help", "ip")}


def _message_box(kind: str, parent, title: str, text: str, details: str = None):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextFormat(Qt.PlainText)
    ico_name, color = _KIND_ICON[kind]
    box.setIconPixmap(icon_pixmap(ico_name, ICON_SIZE["xl"], color))
    if details:
        box.setDetailedText(details)
    return box


def show_message(kind: str, parent, title: str, text: str, details: str = None) -> None:
    """kind: info | success | warning | error. 'details' agrega un desplegable 'Mostrar detalles'."""
    box = _message_box(kind, parent, title, text, details)
    ok = box.addButton(tr("common.ok"), QMessageBox.AcceptRole)
    ok.setObjectName("btnPrimary")
    box.setDefaultButton(ok)
    _exec(box)


def ask_confirm(parent, title: str, text: str, confirm_text: str = None, danger: bool = False) -> bool:
    """
    Pregunta Sí/No con verbos claros ('Eliminar' / 'Cancelar', nunca 'Sí' / 'No').
    danger=True → botón rojo y 'Cancelar' como opción por defecto (Enter no borra nada).
    """
    box = _message_box("warning" if danger else "question", parent, title, text)
    yes = box.addButton(confirm_text or tr("common.accept"), QMessageBox.AcceptRole)
    no = box.addButton(tr("common.cancel"), QMessageBox.RejectRole)
    yes.setObjectName("btnDanger" if danger else "btnPrimary")
    box.setDefaultButton(no if danger else yes)
    box.setEscapeButton(no)
    _exec(box)
    return box.clickedButton() is yes


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  AVISO DENTRO DE LA VENTANA (banner)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Banner(QFrame):
    """
    Aviso persistente arriba de una tarjeta o pantalla: requiere atención pero no bloquea.
    kind: info | success | warning | error. Acción opcional (botón secundario) y botón cerrar.
    """
    actionClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SP["md"], SP["sm"], SP["sm"], SP["sm"])
        lay.setSpacing(SP["sm"])
        self._icon = QLabel()
        self._icon.setFixedSize(ICON_SIZE["md"], ICON_SIZE["md"])
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setTextFormat(Qt.PlainText)
        self._action = QPushButton()
        self._action.setObjectName("btnSecondary")
        self._action.clicked.connect(self.actionClicked)
        self._close = make_icon_button("close", "close_notice")
        self._close.clicked.connect(self.hide)
        lay.addWidget(self._icon, 0, Qt.AlignTop)
        lay.addWidget(self._text, 1)
        lay.addWidget(self._action, 0, Qt.AlignVCenter)
        lay.addWidget(self._close, 0, Qt.AlignTop)
        self.hide()

    def show_message(self, kind: str, text: str, action_text: str = None, closable: bool = True) -> None:
        ico_name, color = _KIND_ICON[kind]
        self.setProperty("kind", kind)
        _repolish(self)
        self._icon.setPixmap(icon_pixmap(ico_name, ICON_SIZE["md"], color))
        self._text.setText(text)
        self._action.setVisible(bool(action_text))
        self._action.setText(action_text or "")
        self._close.setVisible(closable)
        self.show()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  NOTIFICACIÓN TEMPORAL (toast)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Toast(QFrame):
    """
    Confirmación breve que desaparece sola ('Archivo guardado', 'Copiado').
    Aparece abajo a la derecha de la ventana, encima de la barra de estado. No usar para errores.
    Uso: Toast.show_text(self, tr("toast.saved"), "success")
    """
    _active = None

    def __init__(self, window, text: str, kind: str = "success", msec: int = 3000):
        super().__init__(window)
        self.setObjectName("toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SP["md"], SP["sm"] + 2, SP["lg"], SP["sm"] + 2)
        lay.setSpacing(SP["sm"])
        ico_name, color = _KIND_ICON[kind]
        lay.addWidget(icon_label(ico_name, ICON_SIZE["sm"], color))
        lbl = QLabel(text)
        lay.addWidget(lbl)
        self.adjustSize()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(180)
        QTimer.singleShot(msec, self._fade_out)

    @classmethod
    def show_text(cls, window, text: str, kind: str = "success", msec: int = 3000) -> None:
        if cls._active is not None:
            cls._active.deleteLater()
        toast = cls(window, text, kind, msec)
        cls._active = toast
        sb = window.statusBar().height() if isinstance(window, QMainWindow) and window.statusBar() else 0
        toast.move(window.width() - toast.width() - SP["lg"], window.height() - toast.height() - sb - SP["lg"])
        toast.show()
        toast.raise_()
        toast._anim.setStartValue(0.0)
        toast._anim.setEndValue(1.0)
        toast._anim.start()

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._remove)
        self._anim.start()

    def _remove(self) -> None:
        if Toast._active is self:
            Toast._active = None
        self.deleteLater()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  INDICADOR DE ACTIVIDAD (spinner)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class BusySpinner(QWidget):
    """Para esperas de duración desconocida (conectando, leyendo). Si se conoce el total,
    usar QProgressBar."""
    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self) -> None:
        self.show()
        self._timer.start(16)

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = 2.0
        r = QRectF(w, w, self.width() - 2 * w, self.height() - 2 * w)
        pen = QPen(QColor(THEME["border_strong"]), w)
        p.setPen(pen)
        p.drawEllipse(r)
        pen.setColor(QColor(THEME["accent"]))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, int(-self._angle * 16), int(100 * 16))
        p.end()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  TAREAS LARGAS EN SEGUNDO PLANO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TaskWorker(QThread):
    """
    Ejecuta fn(worker, *args, **kwargs) en otro hilo. Dentro de fn:
        worker.report(actual, total, texto)   → progreso
        if worker.is_cancelled(): return      → respetar "Detener"
    Señales: progress(int, int, str), succeeded(object), failed(str), cancelled().
    """
    progress = Signal(int, int, str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def is_cancelled(self) -> bool:
        return self._cancel

    def report(self, current: int, total: int, text: str = "") -> None:
        self.progress.emit(int(current), int(total), text)

    def run(self):
        try:
            result = self._fn(self, *self._args, **self._kwargs)
        except Exception as e:                     # se informa en la UI, nunca se pierde
            logging.exception("Error en tarea en segundo plano")
            self.failed.emit(str(e))
            return
        if self._cancel:
            self.cancelled.emit()
        else:
            self.succeeded.emit(result)


def open_with_system(path: str) -> bool:
    """Abre un archivo o carpeta con la aplicación predeterminada del sistema."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def reveal_in_folder(path: str) -> None:
    """Abre el explorador del sistema con el archivo seleccionado."""
    path = os.path.normpath(path)
    try:
        if IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", path])
        elif IS_MACOS:
            subprocess.Popen(["open", "-R", path])
        else:
            open_with_system(path if os.path.isdir(path) else os.path.dirname(path))
    except OSError:
        open_with_system(os.path.dirname(path))


def copy_to_clipboard(text: str) -> None:
    QGuiApplication.clipboard().setText(text)



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  PERSISTENCIA (QSettings)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def app_settings() -> "QSettings":
    return QSettings(APP_ORG, APP_NAME)


def save_window_state(win, splitters: dict = None, headers: dict = None) -> None:
    """Guardar en closeEvent: geometría, estado, splitters y columnas de tablas."""
    st = app_settings()
    st.setValue("window/geometry", win.saveGeometry())
    if isinstance(win, QMainWindow):
        st.setValue("window/state", win.saveState())
    for name, sp in (splitters or {}).items():
        st.setValue(f"splitter/{name}", sp.saveState())
    for name, header in (headers or {}).items():
        st.setValue(f"header/{name}", header.saveState())


def restore_window_state(win, splitters: dict = None, headers: dict = None) -> None:
    """Llamar al final de _build_ui(). Si no hay nada guardado, no hace nada."""
    st = app_settings()
    geo = st.value("window/geometry")
    if geo is not None:
        win.restoreGeometry(geo)
    state = st.value("window/state")
    if state is not None and isinstance(win, QMainWindow):
        win.restoreState(state)
    for name, sp in (splitters or {}).items():
        val = st.value(f"splitter/{name}")
        if val is not None:
            sp.restoreState(val)
    for name, header in (headers or {}).items():
        val = st.value(f"header/{name}")
        if val is not None:
            header.restoreState(val)



def remember_dir(key: str, path: str = None) -> str:
    """Última carpeta usada en un diálogo (por clave). Sin path: la lee."""
    st = app_settings()
    if path:
        st.setValue(f"last_dir/{key}", path if os.path.isdir(path) else os.path.dirname(path))
    return st.value(f"last_dir/{key}", os.path.expanduser("~"))


def install_excepthook() -> None:
    """Cualquier error no controlado se registra y se muestra en un diálogo con detalles,
    en vez de cerrar el programa sin aviso."""
    def _hook(exc_type, exc, tb):
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.error("Error no controlado:\n%s", details)
        if QApplication.instance() is not None:
            show_message("error", None, tr("msg.unexpected_title"),
                         tr("msg.unexpected_text", detail=str(exc)), details=details)
    sys.excepthook = _hook
