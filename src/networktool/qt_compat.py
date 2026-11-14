"""Capa de compatibilidad PySide6 / PySide2 (prompt de diseño v6.3, sección 2).

Nunca importar PySide6/PySide2 fuera de _import_qt(). Los demás módulos hacen
`from networktool.qt_compat import QLabel, ...`.
"""

import sys

# ══════════════════════════════════════════════════════════════════════════
# CAPA DE COMPATIBILIDAD AUTOMÁTICA: PySide6 / PySide2
# ══════════════════════════════════════════════════════════════════════════
# Orden de prioridad:
#   1. PySide6  → Python 3.10+, Windows 10/11, Linux
#   2. PySide2  → Python 3.8/3.9, Windows 7/8/10, Linux
#
# Cada nombre se busca en QtWidgets, QtGui y QtCore: así se resuelven solas las
# clases que Qt6 movió de módulo (QAction, QShortcut, QFileSystemModel → QtGui).
# ══════════════════════════════════════════════════════════════════════════
_QT_NAMES = (
    # ── Widgets ──
    "QApplication", "QMainWindow", "QWidget", "QFrame", "QGroupBox", "QLabel",
    "QPushButton", "QToolButton", "QToolBar", "QLineEdit", "QComboBox",
    "QScrollArea", "QScrollBar", "QSizePolicy", "QSplitter", "QStackedWidget", "QStackedLayout",
    "QHBoxLayout", "QVBoxLayout", "QGridLayout", "QFormLayout",
    "QMessageBox", "QSpacerItem", "QTabWidget", "QTabBar",
    "QCheckBox", "QTextEdit", "QPlainTextEdit", "QProgressBar", "QStatusBar",
    "QFileDialog", "QListWidget", "QListWidgetItem",
    "QTableWidget", "QTableWidgetItem", "QTableView", "QTreeView", "QListView",
    "QHeaderView", "QAbstractItemView", "QAbstractScrollArea", "QTreeWidget", "QTreeWidgetItem",
    "QDialog", "QDialogButtonBox", "QInputDialog", "QSpinBox", "QDoubleSpinBox",
    "QRadioButton", "QButtonGroup", "QMenu", "QFileIconProvider", "QGraphicsOpacityEffect",
    # ── Gui ──
    "QAction", "QShortcut", "QKeySequence",
    "QColor", "QFont", "QFontDatabase", "QFontMetrics", "QIcon", "QPalette",
    "QPainter", "QPen", "QBrush", "QPixmap", "QImage", "QTextCursor",
    "QDragEnterEvent", "QDropEvent", "QDesktopServices", "QGuiApplication",
    "QPdfWriter", "QTextDocument", "QPageSize", "QPageLayout",
    # ── Core ──
    "Qt", "QObject", "QEvent", "QThread", "QTimer", "QSettings", "QMimeData",
    "QRectF", "QPointF", "QPoint", "QSize", "QRect", "QByteArray", "QUrl",
    "QLocale", "QTranslator", "QLibraryInfo", "QStandardPaths", "QMimeDatabase",
    "QPropertyAnimation", "QEasingCurve", "QFileSystemWatcher", "QSharedMemory",
)


def _import_qt():
    import importlib
    errors = []
    for backend in ("PySide6", "PySide2"):
        try:
            mods = [importlib.import_module(f"{backend}.{m}") for m in ("QtWidgets", "QtGui", "QtCore")]
        except ImportError as e:
            errors.append(f"{backend}: {e}")
            continue
        ns, missing = {}, []
        for name in _QT_NAMES:
            obj = next((getattr(m, name) for m in mods if hasattr(m, name)), None)
            if obj is None:
                missing.append(name)
            ns[name] = obj
        ns["Signal"] = mods[2].Signal
        # QtSvg es opcional: sin él los íconos quedan vacíos pero el programa funciona.
        try:
            ns["QSvgRenderer"] = importlib.import_module(f"{backend}.QtSvg").QSvgRenderer
        except ImportError:
            ns["QSvgRenderer"] = None
            missing.append("QSvgRenderer (íconos desactivados)")
        if missing:
            print(f"[Qt] Aviso: no disponibles en {backend}: {', '.join(missing)}")
        return backend, ns

    print("=" * 65)
    print("ERROR FATAL: No se encontró ningún framework Qt compatible.")
    print("  Windows 10/11 / Linux (Python 3.10+):  pip install PySide6")
    print("  Windows 7 (Python 3.8):                pip install PySide2")
    for e in errors:
        print(f"  · {e}")
    print("=" * 65)
    try:
        input("Presioná Enter para salir...")
    except EOFError:
        pass
    sys.exit(1)


_QT_BACKEND, _qt = _import_qt()
globals().update(_qt)            # expone QApplication, QWidget, Qt, Signal, etc.
print(f"[NetworkTool] Backend Qt: {_QT_BACKEND}")

_QSharedMemory = _qt.get("QSharedMemory")
HAS_SHARED_MEMORY = _QSharedMemory is not None


def _exec(obj, *args):
    """exec() / exec_() compatible PySide6 / PySide2 (QApplication, QDialog, QMenu…)."""
    fn = getattr(obj, "exec", None)
    if not callable(fn):
        fn = obj.exec_
    return fn(*args)


def _exec_menu(menu, pos) -> None:
    """Muestra un QMenu en una posición global."""
    _exec(menu, pos)


def _global_pos(event):
    """PySide6: globalPosition().toPoint()  |  PySide2: globalPos()."""
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


def _event_pos(event):
    """Posición local del mouse. PySide6: position().toPoint() | PySide2: pos()."""
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()


_gpos = _global_pos
