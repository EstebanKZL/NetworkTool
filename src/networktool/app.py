"""Punto de entrada de la aplicación."""

import argparse
import os
import sys
import time

from networktool.common import (
    APP_ICON_ICO, APP_ICON_PNG, APP_NAME, APP_VERSION, IS_WINDOWS, _force_window_icon, logger, resource_path, setup_logging,
    setup_windows_taskbar_icon,
)
from networktool.qt_compat import (
    QApplication, QIcon, QMessageBox, QTimer, Qt, _QSharedMemory, _QT_BACKEND, _exec,
)
from networktool.i18n import check_translations, tr
from networktool.ui.main_window import MainWindow
from networktool.ui.theme import install_excepthook, setup_appearance

class SingleApplication(QApplication):
    def __init__(self, argv, key="NetworkToolPro"):
        super().__init__(argv)
        self.key   = key
        self._lock = None
        self._is_running = False

        if _QT_BACKEND == "PySide6":
            self._shm = _QSharedMemory(key)
            if self._shm.attach():
                self._shm.detach()
                if not self._shm.create(1):
                    self._is_running = True
            elif not self._shm.create(1):
                self._is_running = True

        elif IS_WINDOWS:
            import ctypes
            ERROR_ALREADY_EXISTS = 183
            mutex_name = f"Global\\NetworkTool_{key}"
            handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
            last_err = ctypes.windll.kernel32.GetLastError()
            if handle and last_err == ERROR_ALREADY_EXISTS:
                self._is_running = True
            else:
                self._lock = handle

        else:
            import fcntl
            self._lock_path = f"/tmp/NetworkTool_{key}.lock"
            try:
                self._lock = open(self._lock_path, "w")
                fcntl.lockf(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError:
                self._is_running = True

    def is_running(self):
        return self._is_running

def run_selftest(path: str) -> int:
    """Diagnóstico sin interfaz: comprueba dependencias y lectura de red, escribe un
    informe JSON en `path` y devuelve 0 si todo está bien. Útil con el .exe, que no
    tiene consola:  NetworkTool.exe --selftest informe.json"""
    import json
    import traceback
    from networktool.common import nettool_data_dir
    from networktool.net.adapters import get_adapters, get_ip_info
    from networktool.net.discovery import read_arp_table
    from networktool.net.services import oui_db_path, oui_lookup
    from networktool.system import is_admin
    report, ok = {"version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)), "qt": _QT_BACKEND}, True
    checks = {
        "admin": is_admin,
        "data_dir": lambda: str(nettool_data_dir()),
        "adapters": lambda: {a: get_ip_info(a) for a in get_adapters()},
        "arp_entries": lambda: len(read_arp_table()),
        "oui_db": lambda: oui_db_path().exists() and oui_lookup("AC:C6:62:00:00:01"),
        "icon": lambda: os.path.exists(resource_path(APP_ICON_ICO)),
        # bóveda de credenciales: cifrar y descifrar con la cuenta del usuario
        "vault_crypto": lambda: __import__("networktool.data.vault", fromlist=["x"]).decrypt(
            __import__("networktool.data.vault", fromlist=["x"]).encrypt("ok")) == "ok",
        # terminal local / WSL: pseudo-terminal de Windows (pywinpty)
        "local_pty": lambda: __import__("networktool.net.wsl", fromlist=["x"]).has_pty(),
        "wsl_distros": lambda: [d["name"] for d in __import__("networktool.net.wsl", fromlist=["x"]).list_distros()],
        # sesiones integradas: paramiko (SSH/SFTP, usa cryptography) y pyte (terminal)
        "ssh_libs": lambda: f"paramiko {__import__('paramiko').__version__}, "
                            f"cryptography {__import__('cryptography').__version__}, pyte ok"
                            if __import__("pyte") else "",
    }
    for name, fn in checks.items():
        try:
            report[name] = fn()
        except Exception:
            report[name] = "ERROR: " + traceback.format_exc(limit=3)
            ok = False
    # el ejecutable compilado tiene que traer VERSION y el ícono (si no, la build está incompleta)
    if APP_VERSION == "0.0.0" or report.get("icon") is not True:
        ok = False
    report["ok"] = ok
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    return 0 if ok else 1

def main():
    setup_windows_taskbar_icon()

    if _QT_BACKEND == "PySide6":
        if hasattr(Qt, "AA_UseHighDpiPixmaps"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    else:
        if hasattr(Qt, "AA_EnableHighDpiScaling"):
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        if hasattr(Qt, "AA_UseHighDpiPixmaps"):
            QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    parser = argparse.ArgumentParser(description="NetworkTool")
    parser.add_argument("--debug", action="store_true", help="Activar modo debug")
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--selftest", metavar="ARCHIVO.json", help="Diagnóstico sin interfaz; guarda un informe JSON")
    args, _unknown = parser.parse_known_args()
    if args.selftest:
        setup_logging(False)
        sys.exit(run_selftest(args.selftest))
    if args.elevated:
        # Reinicio como Administrador: dar tiempo a que la instancia anterior libere el bloqueo
        time.sleep(1.5)

    debug_mode = args.debug or os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
    # Prueba de humo (CI): abre la ventana real, la cierra a los pocos segundos y sale con 0;
    # cualquier error no controlado termina con código 1 en lugar de mostrar un diálogo.
    smoke = os.environ.get("NETWORKTOOL_SMOKE_TEST") == "1"
    setup_logging(debug_mode)

    try:
        app = SingleApplication(sys.argv, f"NetworkTool_{APP_VERSION}")
        if app.is_running():
            if IS_WINDOWS:
                import ctypes as _ct
                _ct.windll.user32.MessageBoxW(0, tr("msg.already_running"), "NetworkTool", 0x40)
            sys.exit(0)

        if not getattr(sys, "frozen", False):
            check_translations()       # solo en desarrollo: avisa claves faltantes
        setup_appearance(app)          # fuente + paleta + íconos + QSS + cursor + traducciones Qt
        install_excepthook()           # errores no controlados → registro + diálogo con detalles
        if smoke:
            def _smoke_hook(exc_type, exc, tb):
                import traceback as _tb
                sys.stderr.write("".join(_tb.format_exception(exc_type, exc, tb)))
                os._exit(1)
            sys.excepthook = _smoke_hook

        for name in [APP_ICON_ICO, APP_ICON_PNG]:
            path = resource_path(name)
            if os.path.exists(path):
                app.setWindowIcon(QIcon(path))
                break

        win = MainWindow(debug=debug_mode)
        win.show()
        if smoke:
            QTimer.singleShot(4000, win.close)

        if os.name == 'nt':
            # FIX v5.2.2: usar int(win.winId()) — directo y confiable
            hwnd      = int(win.winId())
            icon_path = next(
                (resource_path(n) for n in [APP_ICON_ICO]
                 if os.path.exists(resource_path(n))),
                None,
            )
            QTimer.singleShot(300, lambda: _force_window_icon(hwnd, icon_path))

        rc = _exec(app)
        # Cierre ordenado: la ventana (y sus hilos) se destruye mientras Qt sigue vivo, antes de
        # que el intérprete desarme los objetos en un orden arbitrario. No usar os._exit: en
        # Windows corta Qt con la QApplication viva y termina en un fallo de segmento.
        win.deleteLater()
        app.processEvents()
        del win
        import gc
        gc.collect()
        try:
            from networktool.ui.theme import app_settings
            app_settings().sync()
        except Exception:
            pass
        sys.exit(rc)

    except Exception as _err:
        import traceback as _tb_mod
        _tb_str = _tb_mod.format_exc()
        logger.critical(f"Error de inicio: {_err}\n{_tb_str}")
        if os.environ.get("NETWORKTOOL_SMOKE_TEST") == "1":
            sys.stderr.write(_tb_str)
            sys.exit(1)
        try:
            if QApplication.instance() is None:
                QApplication(sys.argv)
            _mb = QMessageBox()
            _mb.setWindowTitle(tr("msg.startup_error_title"))
            _mb.setIcon(QMessageBox.Critical)
            _mb.setText(tr("msg.startup_error_text", app=APP_NAME, error=str(_err)))
            _mb.setDetailedText(_tb_str)
            _exec(_mb)
        except Exception:
            print("=" * 60)
            print("ERROR DE INICIO — NetworkTool")
            print("=" * 60)
            print(_tb_str)
            input("Presione Enter para salir...")
        sys.exit(1)
