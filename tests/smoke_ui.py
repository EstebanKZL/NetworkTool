"""Prueba de humo de la interfaz (sin ventana): arma la ventana principal en los dos temas,
abre los diálogos principales y falla ante cualquier error no controlado.

Uso:  QT_QPA_PLATFORM=offscreen python tests/smoke_ui.py
"""
import os
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Datos del usuario en una carpeta temporal: la prueba no toca la configuración real
_tmp = tempfile.mkdtemp(prefix="networktool-smoke-")
os.environ["APPDATA"] = _tmp
os.environ["HOME"] = _tmp

errors = []


def _hook(exc_type, exc, tb):
    errors.append("".join(traceback.format_exception(exc_type, exc, tb)))


sys.excepthook = _hook

from networktool.qt_compat import QApplication, QMessageBox, QSettings  # noqa: E402

QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _tmp)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

app = QApplication(sys.argv)
from networktool.ui.theme import setup_appearance  # noqa: E402

setup_appearance(app)
from networktool.ui import dialogs  # noqa: E402
from networktool.ui.main_window import MainWindow  # noqa: E402


def pump(n=20):
    for _ in range(n):
        app.processEvents()


win = MainWindow()
win.resize(1280, 720)
win.show()
pump()
for cls in (dialogs.SettingsDialog, dialogs.AboutDialog):
    d = cls(win)
    d.show()
    pump(5)
    if hasattr(d, "nav"):
        for row in range(d.nav.count()):
            d.nav.setCurrentRow(row)
            pump(2)
    d.reject()
win.sessions.reload()
pump()
win.close()
pump()

if errors:
    sys.stderr.write("\n".join(errors))
    sys.exit(1)
print("smoke_ui OK", flush=True)
sys.exit(0)
