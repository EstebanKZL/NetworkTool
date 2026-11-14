"""Ventana principal: encabezado, panel de sesiones, pestañas de trabajo y barra de estado.

La primera pestaña es el escáner de red (ScannerPage); cada sesión SSH / Telnet / SFTP /
FTP abre una pestaña propia, como en MobaXterm.
"""

import csv
import ipaddress
import logging
import os
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from networktool.common import (
    APP_DEVELOPER, APP_ICON_ICO, APP_NAME, APP_REPO_URL, APP_VERSION, IS_LINUX, IS_MACOS, IS_WINDOWS, STATUS_OFFLINE,
    STATUS_ONLINE, UNKNOWN, _cleanup_child_processes, _html_escape, _normalize_mac,
    _normalize_mask, _now_str, logger, mask_to_cidr, nettool_data_dir,
    resource_path, smoke_mark,
)
from networktool.data.inventory import Inventory, shared_macs
from networktool.data.profiles import ProfileStore
from networktool.data.sessions import (
    LOCAL_PROTOCOLS, PORT_TO_PROTOCOL, PROTOCOL_LABELS, PROTOCOLS, SessionStore, parse_quick_connect,
)
from networktool.data.vault import vault
from networktool.net.wsl import has_pty, list_distros, local_shells, wsl_command
from networktool.i18n import tr, tr_value
from networktool.net.adapters import (
    _live_ipv4, debug_adapters, get_adapter_link_status, get_adapters, get_ip_info,
    invalidate_adapters_cache,
)
from networktool.net.ipconfig import WARNING_PREFIX, _configured_ipv4
from networktool.net.services import mac_vendor, oui_db_needs_update, oui_lookup, update_oui_db
from networktool.qt_compat import (
    QAction, QApplication, QCheckBox, QColor, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QIcon, QKeySequence, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QStackedWidget, QStatusBar,
    QTabBar, QTabWidget, QTableWidget, QTableWidgetItem, QTimer, QVBoxLayout, QWidget, Qt, Signal,
    _exec, _exec_menu,
)
from networktool.reports import device_history_text, export_excel, export_pdf, report_html
from networktool.settings import settings
from networktool.system import is_admin, launch_external, relaunch_as_admin
from networktool.ui.dialogs import (
    AboutDialog, AdapterIPsDialog, AliasDialog, CompareDialog, FilterDialog, IPDetailsWindow,
    InventoryDialog, ManualConfigDialog, ProfileManagerDialog, SettingsDialog,
)
from networktool.ui.filebrowser import FileBrowserTab
from networktool.ui.sessions import CredentialsDialog, CredentialsManagerDialog, SessionsPanel
from networktool.ui.terminal import TerminalTab, terminal_missing_libs
from networktool.ui.theme import (
    SP, THEME, THEME_NAME, add_search_icon, attach_menu, field_label, icon, make_badge, make_button, make_card,
    make_divider, make_empty_state, make_log_view, protocol_icon, restore_window_state, save_window_state,
    set_badge, set_help, span,
)
from networktool.ui.tools_window import ToolsWindow
from networktool.ui.widgets import DotGripWidget, IPTableItem, QtLogHandler, Toast
from networktool.workers import VENDOR_PENDING, IPConfigThread, ScannerThread

COL_IP, COL_HOST, COL_MAC, COL_VENDOR, COL_PORTS, COL_DEV, COL_STATUS, COL_CONNECT, COL_ACTIONS = range(9)

# Botones de conexión directa de la tabla (como el escaneo de MobaXterm): servicio → puertos
CONNECT_SERVICES = [("ssh", (22,)), ("sftp", (22,)), ("telnet", (23,)), ("ftp", (21,)),
                    ("rdp", (3389,)), ("vnc", (5900, 5901)), ("web", (443, 8443, 80, 8080, 8000, 8888))]
DATA_COLS = 7


def _is_camera(dev: str) -> bool:
    return "camera" in dev.lower()


def _is_server(dev: str) -> bool:
    d = dev.lower()
    return "server" in d or "web" in d or "ntp" in d


# ══════════════════════════════════════════════════════════════════════════
#  PÁGINA DEL ESCÁNER
# ══════════════════════════════════════════════════════════════════════════
class ScannerPage(QWidget):
    vendor_resolved = Signal(str, str)
    vendor_db_updated = Signal(bool, str)
    log_line = Signal(str, str)
    open_session = Signal(dict)          # sesión ad-hoc creada desde la tabla
    save_session = Signal(dict)          # sesión prellenada para guardar

    def __init__(self, main: "MainWindow", debug: bool = False):
        super().__init__()
        self.main = main
        self.debug = debug
        self.setObjectName("page")
        self.scan_results: List[Dict] = []
        self.detail_windows = []
        self.scan_thread = None
        self.config_thread = None
        self._is_closing = False
        self.profile_store = ProfileStore()
        self._config_on_done = None
        self._restore_pending = False
        self._scan_is_monitor = False
        self._monitor_misses: Dict[str, int] = {}
        self._monitor_events: List[str] = []
        self._scan_started = ""
        self._scan_network = ""
        self._scan_adapter = ""
        self._last_comparison: Optional[Dict] = None
        self._sort_col: Optional[int] = None
        self._sort_order = Qt.AscendingOrder
        self._type_filters: List[str] = []
        try:
            self.inventory: Optional[Inventory] = Inventory()
        except Exception as e:
            logger.error(f"No se pudo abrir el inventario: {e}")
            self.inventory = None

        self.vendor_resolved.connect(self.update_vendor_ui)
        self.vendor_db_updated.connect(self._on_vendor_db_updated)
        self._build_ui()
        self.log_line.connect(self.log)
        self._log_handler = QtLogHandler(self.log_line.emit)
        logging.getLogger().addHandler(self._log_handler)
        self.refresh_adapters()
        if debug:
            debug_adapters()
        if oui_db_needs_update():
            # Base de fabricantes offline: se descarga en segundo plano si falta o tiene > 90 días
            threading.Thread(target=lambda: logger.info(update_oui_db()[1]), daemon=True).start()

    # ── Atajos hacia la ventana ────────────────────────────────────────
    def status(self, text: str, ms: int = 0) -> None:
        self.main.statusBar().showMessage(text, ms)

    def toast(self, text: str, kind: str = "ok", ms: int = 4500) -> None:
        self.main.toast.show_message(text, kind, ms)

    # ── Construcción de la interfaz ────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["md"])
        root.setSpacing(SP["md"])

        root.addWidget(self._build_network_card())

        # Resultados + actividad (splitter vertical)
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._build_results_card())
        self.log_card, log_lay = make_card()
        head_row = QHBoxLayout()
        lbl = QLabel(tr("section.activity").upper())
        lbl.setObjectName("lblSection")
        head_row.addWidget(lbl)
        head_row.addStretch(1)
        head_row.addWidget(make_button(tr("btn.clear_log"), "btnSecondary", "clear_log",
                                       lambda: self.activity.clear()))
        log_lay.addLayout(head_row)
        log_lay.setContentsMargins(SP["lg"], SP["sm"], SP["lg"], SP["md"])
        log_lay.setSpacing(SP["xs"])
        self.activity = make_log_view()
        self.activity.setMinimumHeight(56)
        log_lay.addWidget(self.activity)
        self.splitter.addWidget(self.log_card)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([420, 150])
        self.log_card.setVisible(False)
        root.addWidget(self.splitter, 1)
        self._update_stat_labels(0, 0, 0)

    def _build_network_card(self) -> QFrame:
        card, lay = make_card(tr("section.network"))
        row = QHBoxLayout()
        row.setSpacing(SP["sm"])
        row.addWidget(field_label(tr("lbl.adapter")))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(200)
        set_help(self.combo, "adapter")
        self.combo.currentIndexChanged.connect(self.update_info)
        self.combo.currentIndexChanged.connect(lambda *_: self.monitor_chk.setChecked(False)
                                               if hasattr(self, "monitor_chk") else None)
        row.addWidget(self.combo, 3)
        row.addWidget(make_button(tr("btn.refresh"), "btnSecondary", "refresh_adapters", self.refresh_adapters,
                                  shortcut="F5"))
        row.addSpacing(SP["md"])
        row.addWidget(field_label(tr("lbl.network")))
        self.net_edit = QLineEdit()
        self.net_edit.setMinimumWidth(140)
        self.net_edit.setPlaceholderText(tr("ph.network"))
        set_help(self.net_edit, "network")
        self.net_edit.textChanged.connect(self._sync_range_enabled)
        row.addWidget(self.net_edit, 1)
        row.addWidget(field_label(tr("lbl.range")))
        self.range_start = QSpinBox()
        self.range_start.setRange(1, 254)
        self.range_start.setValue(1)
        set_help(self.range_start, "range_start")
        self.range_end = QSpinBox()
        self.range_end.setRange(1, 254)
        self.range_end.setValue(254)
        set_help(self.range_end, "range_end")
        row.addWidget(self.range_start)
        row.addWidget(field_label(tr("lbl.range_to")))
        row.addWidget(self.range_end)
        lay.addLayout(row)

        self.status_lbl = QLabel(tr("status.select_adapter"))
        self.status_lbl.setTextFormat(Qt.RichText)
        lay.addWidget(self.status_lbl)
        lay.addWidget(make_divider())
        lay.addLayout(self._build_profiles_row())
        return card

    def _build_profiles_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SP["sm"])
        lbl = QLabel(tr("section.ip_profiles").upper())
        lbl.setObjectName("lblSection")
        set_help(lbl, "profiles_section")
        row.addWidget(lbl)
        row.addSpacing(SP["sm"])
        self.presets_lay = QHBoxLayout()
        self.presets_lay.setSpacing(SP["sm"])
        row.addLayout(self.presets_lay)
        self.no_profiles_lbl = QLabel(tr("empty.profiles"))
        self.no_profiles_lbl.setObjectName("lblHint")
        row.addWidget(self.no_profiles_lbl)
        row.addStretch(1)
        row.addWidget(make_button(tr("btn.previous_config"), None, "previous_config", self.restore_previous_config))
        row.addWidget(make_button(tr("btn.adapter_ips"), None, "adapter_ips", self.show_adapter_ips))
        row.addWidget(make_button(tr("btn.dhcp"), None, "dhcp", self.set_dhcp))
        row.addWidget(make_button(tr("btn.manual_ip"), None, "manual_ip", self.show_manual_config))
        row.addWidget(make_button(tr("btn.profiles"), "btnSecondary", "manage_profiles", self.show_profile_manager))
        self._build_preset_buttons()
        return row

    def _build_results_card(self) -> QFrame:
        card, lay = make_card()
        head = QHBoxLayout()
        head.setSpacing(SP["sm"])
        lbl = QLabel(tr("section.results").upper())
        lbl.setObjectName("lblSection")
        head.addWidget(lbl)
        head.addSpacing(SP["xs"])
        # Contadores (KPI compactos): dispositivos, cámaras, servidores
        for attr, kind, help_key in (("kpi_total", "info", "kpi_devices"), ("kpi_cameras", "ok", "kpi_cameras"),
                                     ("kpi_servers", "neutral", "kpi_servers")):
            badge = make_badge("", kind)
            set_help(badge, help_key)
            setattr(self, attr, badge)
            head.addWidget(badge)
        head.addSpacing(SP["md"])
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("ph.search_table"))
        self.search_edit.setClearButtonEnabled(True)
        add_search_icon(self.search_edit)
        set_help(self.search_edit, "search_table")
        self.search_edit.textChanged.connect(self._apply_filters)
        head.addWidget(self.search_edit, 1)
        self.btn_filter = make_button(tr("btn.filter"), None, "filter", self.show_filter_dialog)
        head.addWidget(self.btn_filter)
        btn_export = QPushButton(tr("btn.export"))
        set_help(btn_export, "export")
        export_menu = QMenu(self)
        for key, help_key, slot in (("action.export_csv", "export_csv", self.export),
                                    ("action.export_xlsx", "export_xlsx", lambda: self.export_report("xlsx")),
                                    ("action.export_pdf", "export_pdf", lambda: self.export_report("pdf"))):
            act = export_menu.addAction(tr(key))
            set_help(act, help_key)
            act.triggered.connect(lambda checked=False, s=slot: s())
        attach_menu(btn_export, export_menu)
        head.addWidget(btn_export)
        head.addWidget(make_button(tr("btn.inventory"), None, "inventory", self.show_inventory))
        head.addWidget(make_button(tr("btn.clear"), "btnSecondary", "clear_results", self.clear_results))
        lay.addLayout(head)

        self.table = QTableWidget(0, 9)
        headers = [("col.ip", None), ("col.hostname", "col_hostname"), ("col.mac", None),
                   ("col.vendor", None), ("col.ports", "col_ports"), ("col.device", "col_device"),
                   ("col.status", "col_status"), ("col.connect", "col_connect"), ("col.actions", None)]
        for i, (key, tip) in enumerate(headers):
            item = QTableWidgetItem(tr(key))
            if tip:
                item.setToolTip(tr(f"tip.{tip}"))
            self.table.setHorizontalHeaderItem(i, item)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_ACTIONS, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_CONNECT, QHeaderView.Fixed)
        for col in (COL_IP, COL_STATUS):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setColumnWidth(COL_ACTIONS, 136)
        self.table.setColumnWidth(COL_CONNECT, 248)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.on_table_double_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        self.table.setStatusTip(tr("tip.table"))
        hh.sectionClicked.connect(self._on_header_clicked)
        hh.setSortIndicatorShown(False)
        self.table_stack = QStackedWidget()
        self.table_empty = make_empty_state(tr("empty.results"), "radar")
        self.table_stack.addWidget(self.table_empty)
        self.table_stack.addWidget(self.table)
        self.table_stack.setMinimumHeight(110)
        lay.addWidget(self.table_stack, 1)

        foot = QHBoxLayout()
        foot.setSpacing(SP["sm"])
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 254)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m")
        set_help(self.progress_bar, "progress")
        foot.addWidget(self.progress_bar, 1)
        foot.addSpacing(SP["md"])
        self.monitor_chk = QCheckBox(tr("lbl.monitor"))
        set_help(self.monitor_chk, "monitor")
        self.monitor_chk.toggled.connect(self._on_monitor_toggled)
        self.monitor_spin = QSpinBox()
        self.monitor_spin.setRange(10, 3600)
        self.monitor_spin.setValue(settings().int_value("monitor_interval", 10, 3600))
        self.monitor_spin.setSuffix(" s")
        set_help(self.monitor_spin, "monitor_interval")
        self._monitor_timer = QTimer(self)
        self._monitor_timer.setSingleShot(True)
        self._monitor_timer.timeout.connect(self._monitor_sweep)
        foot.addWidget(self.monitor_chk)
        foot.addWidget(self.monitor_spin)
        foot.addSpacing(SP["md"])
        self.btn_stop = make_button(tr("btn.stop"), "btnStop", "stop", self.stop_scan)
        self.btn_stop.setEnabled(False)
        self.btn_scan = make_button(tr("btn.start"), "btnStart", "start", self.start_scan, shortcut="Ctrl+E")
        foot.addWidget(self.btn_stop)
        foot.addWidget(self.btn_scan)
        lay.addLayout(foot)
        return card

    # ── Registro de actividad ──────────────────────────────────────────
    def log(self, text: str, level: str = "info") -> None:
        """level: 'ok' | 'error' | 'warn' | 'info'. El color NO se deduce del texto."""
        color = {"ok": THEME["ok"], "error": THEME["error"], "warn": THEME["counter"]}.get(level, THEME["text"])
        stamp = datetime.now().strftime(tr("fmt.time"))
        self.activity.appendHtml(
            f'<span style="color:{THEME["text_muted"]};">{stamp}</span>&nbsp;&nbsp;'
            f'<span style="color:{color};">{_html_escape(text)}</span>')

    def toggle_log(self, visible: bool) -> None:
        self.log_card.setVisible(visible)
        if visible:
            # tras el reacomodo del layout: la tabla conserva la mayor parte del alto
            QTimer.singleShot(0, lambda: self.splitter.setSizes([max(1, self.splitter.height() - 150), 150]))

    # ── Tabla ──────────────────────────────────────────────────────────
    def _sync_table_empty(self) -> None:
        self.table_stack.setCurrentWidget(self.table if self.table.rowCount() else self.table_empty)

    def on_table_double_click(self, row, column):
        item = self.table.item(row, COL_IP)
        if not item:
            return
        if column == COL_HOST:
            self.edit_alias(item.text())
        elif column == COL_IP:
            webbrowser.open(f"http://{item.text()}")
        else:
            self.show_ip_details_from_record(self._result_for(item.text()) or {"ip": item.text()})

    def clear_results(self):
        self.table.setRowCount(0)
        self.scan_results = []
        self._monitor_misses = {}
        self._update_stat_labels(0, 0, 0)
        self._sync_table_empty()

    def force_refresh_network_status(self):
        invalidate_adapters_cache()
        current = self.combo.currentText()
        self.refresh_adapters()
        idx = self.combo.findText(current)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self.update_info()

    def refresh_adapters(self):
        current = self.combo.currentText()
        invalidate_adapters_cache()
        self.combo.blockSignals(True)
        self.combo.clear()
        adapters = get_adapters()
        if adapters:
            self.combo.addItems(adapters)
        if current:
            idx = self.combo.findText(current)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)
        self.update_info()

    def _update_stat_labels(self, total: int, cameras: int, servers: int) -> None:
        self.kpi_total.setText(tr("kpi.devices_n", n=total))
        self.kpi_cameras.setText(tr("kpi.cameras_n", n=cameras))
        self.kpi_servers.setText(tr("kpi.servers_n", n=servers))

    def _adapter_name(self) -> str:
        return self.combo.currentText() if self.combo.count() else ""

    def update_info(self):
        name = self._adapter_name()
        if not name:
            self.status_lbl.setText(span(tr("status.no_adapters"), "error"))
            return
        ip, mask, gw, dhcp = get_ip_info(name)
        link_status = get_adapter_link_status(name)
        all_ips = _configured_ipv4(name)
        extra_ips = [f"{a}/{mask_to_cidr(m)}" for a, m in all_ips if a != ip]

        sep = f'&nbsp;&nbsp;<span style="color:{THEME["text_muted"]};">│</span>&nbsp;&nbsp;'
        def field(label):
            return f'<span style="color:{THEME["text_secondary"]};">{label}</span>&nbsp;'
        dhcp_ok = dhcp.lower() in ("sí", "si", "yes", "true", "enabled", "dhcp", "habilitado")
        link_up = link_status == "Conectado" or link_status.lower() in ("up", "connected")
        extra = span(f" +{len(extra_ips)}", "counter") if extra_ips else ""
        self.status_lbl.setText(
            field("IP") + span(tr_value(ip), "ip") + extra + sep +
            field(tr("lbl.mask")) + span(tr_value(mask), "ip") + sep +
            field("Gateway") + span(tr_value(gw), "ip") + sep +
            field("DHCP") + span(tr("common.yes") if dhcp_ok else tr("common.no"), "ok" if dhcp_ok else "text_secondary")
            + sep + field("Link") + span(tr_value(link_status), "ok" if link_up else "error"))
        self.status_lbl.setToolTip(tr("tip.extra_ips_list", ips=", ".join(extra_ips)) if extra_ips else "")
        self.main.set_adapter_status(f"{name}  ·  {ip}")
        net = self._default_scan_network(ip, mask)
        self.net_edit.setText(str(net) if net else "")

    @staticmethod
    def _default_scan_network(ip, mask) -> Optional[ipaddress.IPv4Network]:
        """Red real del adaptador; si es mayor a /22 se usa la /24 de la IP."""
        try:
            net = ipaddress.IPv4Network(f"{ip}/{_normalize_mask(mask)}", strict=False)
        except Exception:
            try:
                return ipaddress.IPv4Network(f"{ip}/24", strict=False)
            except Exception:
                return None
        if net.prefixlen < 22 or net.prefixlen > 30:
            net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
        return net

    def _sync_range_enabled(self, *_):
        try:
            enabled = ipaddress.IPv4Network(self.net_edit.text().strip(), strict=False).prefixlen >= 24
        except Exception:
            enabled = True
        self.range_start.setEnabled(enabled)
        self.range_end.setEnabled(enabled)

    # ── Configuración IP ───────────────────────────────────────────────
    def _confirm_admin(self) -> bool:
        """En Windows cambiar la IP exige permisos de administrador: ofrece reiniciar elevado."""
        if not IS_WINDOWS or is_admin():
            return True
        reply = QMessageBox.question(self, tr("msg.admin_title"), tr("msg.admin_required", app=APP_NAME),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            if relaunch_as_admin():
                self.main.close()
                QApplication.instance().quit()
            else:
                QMessageBox.warning(self, tr("msg.error_title"), tr("msg.admin_failed"))
        return False

    def apply_ip_config_async(self, mode, adapter, ip=None, mask=None, gateway=None, dns=None,
                              extra_ips=None, on_done=None, restoring=False):
        if self.config_thread and self.config_thread.isRunning():
            QMessageBox.information(self, tr("msg.busy_title"), tr("msg.config_busy"))
            return
        if not self._confirm_admin():
            return
        if mode in ("static", "dhcp"):
            self.monitor_chk.setChecked(False)
        if self.scan_thread and self.scan_thread.isRunning():
            self.stop_scan()
        self._config_on_done = on_done
        self._restore_pending = restoring
        logger.info(f"Aplicando {mode} en adaptador: '{adapter}'")
        what = {"dhcp": tr("cfg.dhcp"), "add_ip": tr("cfg.add_ip", ip=ip),
                "remove_ip": tr("cfg.remove_ip", ip=ip)}.get(mode, tr("cfg.static", ip=ip))
        self.status_lbl.setText(span(tr("status.applying", what=what, adapter=adapter), "counter"))
        self.config_thread = IPConfigThread(mode, adapter, ip, mask, gateway, dns, extra_ips)
        self.config_thread.finished.connect(self.on_config_finished)
        self.config_thread.start()

    def on_config_finished(self, success, msg, mode):
        invalidate_adapters_cache()
        thread = self.config_thread
        if success and thread is not None:
            if self._restore_pending:
                self.profile_store.pop_last_for(thread.adapter)
            self.profile_store.push_history(thread.adapter, thread.before)
        self._restore_pending = False
        on_done, self._config_on_done = self._config_on_done, None
        if success and mode in ("add_ip", "remove_ip"):
            self.toast(msg, "ok")
            self.log(msg, "ok")
            self.force_refresh_network_status()
            if on_done:
                on_done()
            return
        if success:
            self.clear_results()
            for win in self.detail_windows[:]:
                try:
                    win.close()
                except Exception:
                    pass
            self.detail_windows.clear()
            default = tr("cfg.static_ok") if mode == "static" else tr("cfg.dhcp_ok")
            if WARNING_PREFIX in (msg or ""):
                QMessageBox.warning(self, tr("msg.applied_warn_title"), msg)
                self.log(msg, "warn")
            else:
                self.toast(msg or default, "ok", 6000)
                self.log(msg or default, "ok")
            self.status_lbl.setText(span(tr("status.verifying"), "counter"))
            QTimer.singleShot(1500, self.force_refresh_network_status)
        else:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.config_failed", detail=msg))
            self.log(tr("msg.config_failed", detail=msg), "error")
            self.force_refresh_network_status()
        if on_done:
            on_done()

    def _current_adapter(self) -> Optional[str]:
        adapter = self._adapter_name()
        if not adapter:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.no_adapter"))
            return None
        return adapter

    def _build_preset_buttons(self):
        """Botones de perfiles (sin grupo) y menús desplegables (por grupo), en el orden guardado."""
        while self.presets_lay.count():
            item = self.presets_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        groups: Dict[str, List[Dict]] = {}
        order: List[Tuple[str, object]] = []
        for prof in self.profile_store.profiles:
            g = prof.get("group", "")
            if g:
                if g not in groups:
                    groups[g] = []
                    order.append(("group", g))
                groups[g].append(prof)
            else:
                order.append(("profile", prof))

        for kind, value in order:
            if kind == "profile":
                prof = value
                btn = QPushButton(prof["name"])
                btn.setToolTip(self._profile_tooltip(prof))
                btn.setStatusTip(tr("tip.profile_button"))
                btn.clicked.connect(lambda ch=False, pr=prof: self.apply_profile(pr))
                btn.setContextMenuPolicy(Qt.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, pr=prof, b=btn: self._profile_context_menu(pr, b.mapToGlobal(pos)))
            else:
                btn = QPushButton(value)
                btn.setStatusTip(tr("tip.profile_group_btn"))
                menu = QMenu(self)
                for prof in groups[value]:
                    act = menu.addAction(prof["name"])
                    act.setToolTip(self._profile_tooltip(prof))
                    act.triggered.connect(lambda ch=False, pr=prof: self.apply_profile(pr))
                menu.addSeparator()
                sub = menu.addMenu(tr("action.add_secondary"))
                for prof in groups[value]:
                    sub.addAction(prof["name"]).triggered.connect(
                        lambda ch=False, pr=prof: self.add_profile_as_secondary(pr))
                attach_menu(btn, menu)
            self.presets_lay.addWidget(btn)
        self.no_profiles_lbl.setVisible(not order)

    @staticmethod
    def _profile_tooltip(prof: Dict) -> str:
        rows = [f"IP: {prof['ip']}  ({prof['mask']})", f"Gateway: {prof.get('gateway') or tr('common.none')}"]
        if prof.get("dns"):
            rows.append(f"DNS: {prof['dns']}")
        if prof.get("extra_ips"):
            rows.append(tr("lbl.extra_ips") + ": " + ", ".join(prof["extra_ips"]))
        body = "<br>".join(_html_escape(r) for r in rows)
        return (f"<qt><b>{_html_escape(prof['name'])}</b><br>"
                f"<span style='color:{THEME['text_secondary']};'>{body}<br>{tr('tip.profile_button')}</span></qt>")

    def _profile_context_menu(self, prof: Dict, pos):
        menu = QMenu(self)
        menu.addAction(tr("action.apply_profile")).triggered.connect(lambda ch=False: self.apply_profile(prof))
        menu.addAction(tr("action.add_secondary_keep")).triggered.connect(
            lambda ch=False: self.add_profile_as_secondary(prof))
        _exec_menu(menu, pos)

    def apply_profile(self, prof: Dict):
        adapter = self._current_adapter()
        if adapter:
            self.apply_ip_config_async("static", adapter, prof["ip"], prof["mask"], prof.get("gateway", ""),
                                       prof.get("dns") or None, extra_ips=prof.get("extra_ips"))

    def add_profile_as_secondary(self, prof: Dict):
        adapter = self._current_adapter()
        if adapter:
            self.apply_ip_config_async("add_ip", adapter, prof["ip"], prof["mask"])

    def show_profile_manager(self):
        _exec(ProfileManagerDialog(self.profile_store, self._adapter_name(), self))
        self._build_preset_buttons()

    def show_adapter_ips(self):
        adapter = self._current_adapter()
        if adapter:
            _exec(AdapterIPsDialog(self, adapter))
            self.force_refresh_network_status()

    def restore_previous_config(self):
        adapter = self._current_adapter()
        if not adapter:
            return
        entry = self.profile_store.last_for(adapter)
        if not entry:
            QMessageBox.information(self, tr("btn.previous_config"), tr("msg.no_history", adapter=adapter))
            return
        if entry.get("dhcp"):
            desc = tr("cfg.dhcp")
        else:
            desc = f"IP {entry.get('ip')} ({entry.get('mask')})\nGateway: {entry.get('gateway') or tr('common.none')}"
            if entry.get("extra"):
                desc += "\n" + tr("lbl.extra_ips") + ": " + ", ".join(a for a, _ in entry["extra"])
        if QMessageBox.question(self, tr("btn.previous_config"),
                                tr("msg.restore_confirm", time=entry.get("time", ""), desc=desc),
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if entry.get("dhcp"):
            self.apply_ip_config_async("dhcp", adapter, restoring=True)
        else:
            self.apply_ip_config_async("static", adapter, entry["ip"], entry["mask"], entry.get("gateway", ""),
                                       extra_ips=entry.get("extra"), restoring=True)

    def set_dhcp(self):
        adapter = self._current_adapter()
        if adapter and QMessageBox.question(self, tr("msg.confirm_title"), tr("msg.dhcp_confirm", adapter=adapter),
                                            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.apply_ip_config_async("dhcp", adapter)

    def show_manual_config(self):
        adapter = self._current_adapter()
        if not adapter:
            return
        dialog = ManualConfigDialog(adapter, self)
        if _exec(dialog) == QDialog.Accepted:
            self.apply_ip_config_async("static", adapter, dialog.ip_edit.text(), dialog.mask_edit.text(),
                                       dialog.gateway_edit.text(), dialog.dns_edit.text() or None,
                                       extra_ips=dialog.extra_ips)

    # ── Fabricantes ────────────────────────────────────────────────────
    def update_vendor_db(self):
        self.status(tr("status.downloading_oui"))

        def worker():
            ok, msg = update_oui_db()
            self.vendor_db_updated.emit(ok, msg)
        threading.Thread(target=worker, daemon=True).start()

    def _on_vendor_db_updated(self, ok, msg):
        self.status(msg.splitlines()[0], 8000)
        if ok:
            self.toast(msg, "ok")
            for d in self.scan_results:
                vendor = oui_lookup(d.get("mac", "")) if d.get("mac") not in (None, UNKNOWN) else None
                if vendor:
                    self.update_vendor_ui(d["ip"], vendor)
        else:
            QMessageBox.warning(self, tr("action.update_oui"), msg)

    # ── Monitor ────────────────────────────────────────────────────────
    def _monitor_log(self, text: str, level: str = "info"):
        line = f"{datetime.now().strftime(tr('fmt.time'))}  {text}"
        self.log(f"[{tr('lbl.monitor')}] {text}", level)
        self._monitor_events.append(line)
        self._monitor_events = self._monitor_events[-50:]
        self.monitor_chk.setToolTip(tr("tip.monitor_events", events="<br>".join(
            _html_escape(e) for e in self._monitor_events[-15:])))
        self.status(f"{tr('lbl.monitor')} · {line}")

    def _on_monitor_toggled(self, on: bool):
        if not on:
            self._monitor_timer.stop()
            return
        if self.scan_thread and self.scan_thread.isRunning():
            return   # al terminar el escaneo en curso se programa la siguiente pasada
        if not self.scan_results:
            self.start_scan()
        else:
            self._monitor_timer.start(self.monitor_spin.value() * 1000)
            self.status(tr("status.monitor_next", s=self.monitor_spin.value()))

    def _monitor_sweep(self):
        if not self.monitor_chk.isChecked() or self._is_closing:
            return
        busy = (self.scan_thread and self.scan_thread.isRunning()) or \
               (self.config_thread and self.config_thread.isRunning())
        if busy:
            self._monitor_timer.start(5000)
            return
        self.start_scan(monitor=True)

    def _row_for_ip(self, ip) -> int:
        for r in range(self.table.rowCount()):
            item = self.table.item(r, COL_IP)
            if item and item.text() == ip:
                return r
        return -1

    def _paint_row(self, ip, background_key: Optional[str]):
        r = self._row_for_ip(ip)
        if r < 0:
            return
        for c in range(DATA_COLS):
            item = self.table.item(r, c)
            if item:
                item.setBackground(QColor(THEME[background_key]) if background_key else QColor(0, 0, 0, 0))

    def _status_item(self, online: bool, tooltip: str = "") -> QTableWidgetItem:
        item = QTableWidgetItem(tr("status.online") if online else tr("status.offline"))
        item.setForeground(QColor(THEME["ok"] if online else THEME["error"]))
        if tooltip:
            item.setToolTip(tooltip)
        return item

    def _set_row_status(self, ip, online: bool, tooltip: str = ""):
        r = self._row_for_ip(ip)
        if r < 0:
            return
        self.table.setItem(r, COL_STATUS, self._status_item(online, tooltip))
        rec = self._result_for(ip)
        if rec is not None:
            rec["status"] = STATUS_ONLINE if online else STATUS_OFFLINE
            if rec.get("is_new"):
                self._paint_row(ip, "warn_soft")

    def _on_host_seen(self, ip: str, mac: str):
        """Equipo ya conocido respondió en una pasada del monitor."""
        rec = self._result_for(ip)
        if rec is None:
            return
        if self.inventory is not None:
            try:
                self.inventory.touch(ip, mac or rec.get("mac"))
            except Exception as e:
                logger.debug(f"Inventario: {e}")
        self._monitor_misses[ip] = 0
        seen = tr("tip.seen_at", time=datetime.now().strftime(tr("fmt.time")))
        old_mac = rec.get("mac", UNKNOWN)
        if mac and mac != UNKNOWN and old_mac not in (None, "", UNKNOWN) and mac != old_mac:
            self._monitor_log(tr("log.mac_changed", ip=ip, old=old_mac, new=mac), "warn")
            rec["mac"] = mac
            r = self._row_for_ip(ip)
            if r >= 0:
                mi = QTableWidgetItem(mac)
                mi.setForeground(QColor(THEME["error"]))
                mi.setToolTip(tr("tip.mac_before", mac=old_mac))
                self.table.setItem(r, COL_MAC, mi)
            self._fetch_vendor_async(ip, mac)
            self._paint_row(ip, "error_soft")
        if rec.get("status") == STATUS_OFFLINE:
            self._monitor_log(tr("log.back_online", ip=ip), "ok")
        self._set_row_status(ip, True, seen)

    def _on_sweep_done(self, alive: List[str]):
        if not self._scan_is_monitor:
            return
        alive_set = set(alive)
        for rec in self.scan_results:
            ip = rec["ip"]
            if ip in alive_set:
                continue
            self._monitor_misses[ip] = self._monitor_misses.get(ip, 0) + 1
            # Dos pasadas seguidas sin respuesta para evitar falsos Offline
            if self._monitor_misses[ip] >= 2 and rec.get("status") != STATUS_OFFLINE:
                self._set_row_status(ip, False, tr("tip.no_reply_since",
                                                   time=datetime.now().strftime(tr("fmt.time"))))
                self._monitor_log(tr("log.went_offline", ip=ip), "error")
        self._refresh_stats()

    # ── Búsqueda, filtros y orden ──────────────────────────────────────
    def _apply_filters(self, *_):
        text = self.search_edit.text().strip().lower()
        shown = 0
        for r in range(self.table.rowCount()):
            cells = " ".join(self.table.item(r, c).text().lower() for c in range(DATA_COLS) if self.table.item(r, c))
            if text and self.table.item(r, COL_HOST):
                cells += " " + self.table.item(r, COL_HOST).toolTip().lower()   # alias, hostname y notas
            ok_text = not text or all(t in cells for t in text.split())
            rec = self._result_for(self.table.item(r, COL_IP).text()) if self.table.item(r, COL_IP) else None
            ok_type = not self._type_filters or any(self._matches_type(ft, rec or {}) for ft in self._type_filters)
            hide = not (ok_text and ok_type)
            self.table.setRowHidden(r, hide)
            shown += 0 if hide else 1
        active = bool(text or self._type_filters)
        self.btn_filter.setText(tr("btn.filter_n", n=len(self._type_filters)) if self._type_filters else tr("btn.filter"))
        if active:
            self.status(tr("status.filter_active", shown=shown, total=self.table.rowCount()))

    @staticmethod
    def _matches_type(kind: str, rec: Dict) -> bool:
        dev = rec.get("dev", "").lower()
        ports = {int(p) for p in str(rec.get("ports", "")).split(",") if p.strip().isdigit()}
        return {
            "camera": "camera" in dev,
            "server": "server" in dev,
            "web": "web" in dev or bool(ports & {80, 443, 8080, 8000, 8443}),
            "ssh": bool(ports & {22, 23}),
            "smb": bool(ports & {21, 139, 445}),
            "rdp": bool(ports & {3389, 5900, 5901}),
        }.get(kind, False)

    def _on_header_clicked(self, col: int):
        if col >= DATA_COLS:
            return
        if self._sort_col == col:
            self._sort_order = Qt.DescendingOrder if self._sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self._sort_col, self._sort_order = col, Qt.AscendingOrder
        hh = self.table.horizontalHeader()
        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(col, self._sort_order)
        self.table.sortItems(col, self._sort_order)

    def _resort_and_filter(self):
        if self._sort_col is not None:
            self.table.sortItems(self._sort_col, self._sort_order)
        if self.search_edit.text().strip() or self._type_filters:
            self._apply_filters()

    def show_filter_dialog(self):
        dlg = FilterDialog(self._type_filters, self)
        if _exec(dlg) == QDialog.Accepted:
            self._type_filters = dlg.selected()
            if dlg.cleared:
                self.search_edit.clear()
            self._apply_filters()

    # ── Herramientas ───────────────────────────────────────────────────
    def show_tools(self, tab: str = "ping", target: str = "", mac: str = ""):
        self.main.show_tools(tab, target, mac)

    # ── Inventario, alias y comparación ────────────────────────────────
    def _device_meta(self, data: Dict) -> Optional[Dict]:
        if self.inventory is None:
            return None
        try:
            return self.inventory.get_device(data["ip"], data.get("mac"))
        except Exception:
            return None

    def _host_item(self, data: Dict) -> QTableWidgetItem:
        """Columna Hostname: muestra el alias del inventario si existe y las notas en el tooltip."""
        host = data.get("host", "N/A")
        meta = self._device_meta(data)
        alias = (meta or {}).get("alias") or ""
        item = QTableWidgetItem(alias if alias else host)
        tip = []
        if alias:
            tip.append(tr("tip.host_alias", alias=_html_escape(alias)))
        if host != "N/A":
            tip.append(tr("tip.host_resolved", host=_html_escape(host),
                          method=data.get("host_method") or tr("common.unknown")))
        if meta:
            if meta.get("notes"):
                tip.append(tr("tip.host_notes", notes=_html_escape(meta["notes"])))
            tip.append(tr("tip.host_first_seen", time=meta.get("first_seen")))
        item.setToolTip("<qt>" + "<br>".join(tip) + "</qt>" if tip else "")
        item.setForeground(QColor(THEME["counter"] if alias else (THEME["text"] if host != "N/A" else THEME["text_muted"])))
        if alias:
            font = item.font(); font.setBold(True); item.setFont(font)
        return item

    def refresh_aliases(self):
        for d in self.scan_results:
            r = self._row_for_ip(d["ip"])
            if r >= 0:
                self.table.setItem(r, COL_HOST, self._host_item(d))

    def edit_alias(self, ip: str):
        rec = self._result_for(ip)
        if rec is None or self.inventory is None:
            return
        device = self.inventory.ensure_device(rec, self._scan_network)
        dlg = AliasDialog(device, self)
        if _exec(dlg) == QDialog.Accepted:
            self.inventory.set_meta(device["key"], dlg.alias.text(), dlg.notes.toPlainText())
            self.refresh_aliases()

    def show_device_history(self, ip: str):
        rec = self._result_for(ip)
        if rec is None or self.inventory is None:
            return
        device = self.inventory.ensure_device(rec, self._scan_network)
        QMessageBox.information(self, tr("dlg.device_history"), device_history_text(self.inventory, device))

    def _table_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        item = self.table.item(row, COL_IP) if row >= 0 else None
        if not item:
            return
        ip = item.text()
        rec = self._result_for(ip) or {"ip": ip}
        mac = rec.get("mac", UNKNOWN)
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        # Sesiones según los puertos abiertos (SSH, Telnet, FTP, RDP, VNC, Web)
        ports = [int(p) for p in str(rec.get("ports", "")).split(",") if p.strip().isdigit()]
        offered = []
        for port in ports:
            proto = PORT_TO_PROTOCOL.get(port)
            if proto and (proto, port) not in offered:
                offered.append((proto, port))
        if any(p == "ssh" for p, _ in offered):
            offered.append(("sftp", next(port for p, port in offered if p == "ssh")))
        if offered:
            sess_menu = menu.addMenu(tr("action.open_session"))
            for proto, port in offered:
                sess_menu.addAction(f"{PROTOCOL_LABELS[proto]}  ·  {port}").triggered.connect(
                    lambda ch=False, pr=proto, po=port: self.open_session.emit(
                        {"protocol": pr, "host": ip, "port": po, "name": f"{ip} ({PROTOCOL_LABELS[pr]})"}))
        save_proto, save_port = offered[0] if offered else ("ssh", 22)
        menu.addAction(tr("action.save_as_session")).triggered.connect(
            lambda ch=False: self.save_session.emit({"protocol": save_proto, "host": ip, "port": save_port,
                                                     "name": rec.get("host") if rec.get("host") not in (None, "N/A") else ip}))
        menu.addSeparator()
        menu.addAction(tr("action.view_details")).triggered.connect(lambda ch=False: self.show_ip_details_from_record(rec))
        menu.addAction(tr("action.edit_alias")).triggered.connect(lambda ch=False: self.edit_alias(ip))
        menu.addAction(tr("action.device_history")).triggered.connect(lambda ch=False: self.show_device_history(ip))
        menu.addSeparator()
        menu.addAction(tr("action.copy_ip", ip=ip)).triggered.connect(lambda ch=False: QApplication.clipboard().setText(ip))
        if mac and mac != UNKNOWN:
            menu.addAction(tr("action.copy_mac", mac=mac)).triggered.connect(
                lambda ch=False: QApplication.clipboard().setText(mac))
        menu.addSeparator()
        menu.addAction(tr("action.open_browser")).triggered.connect(lambda ch=False: webbrowser.open(f"http://{ip}"))
        menu.addAction(tr("tool.ping")).triggered.connect(lambda ch=False: self.show_tools("ping", ip))
        menu.addAction(tr("tool.trace")).triggered.connect(lambda ch=False: self.show_tools("trace", ip))
        if mac and mac != UNKNOWN:
            menu.addAction(tr("tool.wol")).triggered.connect(lambda ch=False: self.show_tools("wol", ip, mac))
        menu.addAction(tr("tool.subnet")).triggered.connect(
            lambda ch=False: self.show_tools("subnet", self._scan_network or ip))
        _exec_menu(menu, self.table.viewport().mapToGlobal(pos))

    def _record_scan_and_compare(self):
        if self.inventory is None or not self.scan_results:
            return
        try:
            shared = shared_macs(self.scan_results)
            for d in self.scan_results:   # equipos sin análisis completo (p. ej. cancelado)
                self.inventory.ensure_device(d, self._scan_network, _normalize_mac(d.get("mac")) in shared)
            scan_id = self.inventory.record_scan(self._scan_adapter, self._scan_network, self._scan_started,
                                                 self.scan_results)
            prev = self.inventory.previous_scan(self._scan_network, scan_id)
        except Exception as e:
            logger.error(f"No se pudo guardar el escaneo: {e}")
            return
        if not prev:
            self._last_comparison = None
            self.status(tr("status.scan_done_first", n=len(self.scan_results)))
            return
        cmp = self.inventory.compare_scans(prev["id"], scan_id)
        self._last_comparison = cmp
        for ip in {h["ip"] for h in cmp["new"]}:
            rec = self._result_for(ip)
            if rec is not None and not rec.get("is_new"):
                self._paint_row(ip, "info_soft")
                r = self._row_for_ip(ip)
                if r >= 0 and self.table.item(r, COL_IP):
                    self.table.item(r, COL_IP).setToolTip(tr("tip.new_since", time=prev["started"]))
        summary = tr("status.scan_done_cmp", n=len(self.scan_results), time=prev["started"], new=len(cmp["new"]),
                     missing=len(cmp["missing"]), changed=len(cmp["ip_changed"]))
        self.status(summary)
        self.log(summary, "ok")

    def show_last_comparison(self):
        if not self._last_comparison:
            QMessageBox.information(self, tr("action.compare"), tr("msg.no_comparison"))
            return
        _exec(CompareDialog(self._last_comparison, self.inventory, self))

    def show_inventory(self):
        if self.inventory is None:
            QMessageBox.warning(self, tr("btn.inventory"), tr("msg.inventory_unavailable"))
            return
        _exec(InventoryDialog(self.inventory, self))
        self.refresh_aliases()

    # ── Informes ───────────────────────────────────────────────────────
    def _report_rows(self) -> List[List]:
        rows = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r) or not self.table.item(r, COL_IP):
                continue
            d = self._result_for(self.table.item(r, COL_IP).text())
            if not d:
                continue
            meta = self._device_meta(d) or {}
            status = tr("status.online") if d.get("status", STATUS_ONLINE) == STATUS_ONLINE else tr("status.offline")
            rows.append([d["ip"], meta.get("alias", ""), d.get("host", ""), d.get("mac", ""), d.get("vendor", ""),
                         d.get("ports", ""), d.get("dev", ""), status, meta.get("notes", "")])
        return rows

    def _report_summary(self, rows) -> List[Tuple[str, str]]:
        adapter = self._scan_adapter or self._adapter_name()
        ip, mask, gw, dhcp = get_ip_info(adapter) if adapter else ("", "", "", "")
        count = lambda word: sum(1 for d in self.scan_results if word in d.get("dev", "").lower())
        return [
            (tr("rep.date"), _now_str()), (tr("rep.scan"), self._scan_started or "-"),
            (tr("lbl.adapter"), adapter), (tr("rep.local_ip"), f"{ip} / {mask}"), ("Gateway", tr_value(gw)),
            ("DHCP", tr_value(dhcp)),
            (tr("rep.network"), self._scan_network or "-"), (tr("rep.devices"), str(len(rows))),
            (tr("kpi.cameras"), str(count("camera"))),
            (tr("rep.offline"), str(sum(1 for d in self.scan_results if d.get("status") == STATUS_OFFLINE))),
        ]

    def export_report(self, kind: str):
        rows = self._report_rows()
        if not rows:
            QMessageBox.information(self, tr("btn.export"), tr("msg.nothing_to_export"))
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        ext, filt = ("xlsx", "Excel (*.xlsx)") if kind == "xlsx" else ("pdf", "PDF (*.pdf)")
        path, _ = QFileDialog.getSaveFileName(self, tr("dlg.save_report"), f"{tr('rep.file_prefix')}_{stamp}.{ext}", filt)
        if not path:
            return
        summary = self._report_summary(rows)
        try:
            if kind == "xlsx":
                inv_rows = self.inventory.all_devices() if self.inventory else []
                export_excel(path, summary, rows, self._last_comparison, inv_rows)
            else:
                export_pdf(path, report_html(summary, rows, self._last_comparison, self.inventory))
        except Exception as e:
            QMessageBox.critical(self, tr("msg.error_title"), tr("msg.report_failed", detail=e))
            return
        self.log(tr("log.report_saved", path=path), "ok")
        if QMessageBox.question(self, tr("msg.report_title"), tr("msg.report_saved", path=path),
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            webbrowser.open(Path(path).as_uri())

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("action.export_csv"), "", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["IP", "Host", "MAC", "Vendor", "Ports", "Device", "Status"])
                for r in range(self.table.rowCount()):
                    if not self.table.isRowHidden(r):
                        d = self._result_for(self.table.item(r, COL_IP).text()) or {}
                        writer.writerow([d.get("ip", ""), d.get("host", ""), d.get("mac", ""), d.get("vendor", ""),
                                         d.get("ports", ""), d.get("dev", ""), d.get("status", "")])
            self.toast(tr("msg.csv_saved", path=path), "ok")
        except Exception as e:
            QMessageBox.critical(self, tr("msg.error_title"), tr("msg.save_failed", detail=e))

    # ── Escaneo ────────────────────────────────────────────────────────
    def stop_scan(self):
        if self.sender() is self.btn_stop:
            self.monitor_chk.setChecked(False)
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.cancel()
            self.status(tr("status.canceling"))
            self.btn_stop.setEnabled(False)

    def start_scan(self, monitor=False):
        monitor = monitor is True   # clicked(bool) también llega aquí
        name = self._adapter_name()
        if not name or (self.scan_thread and self.scan_thread.isRunning()):
            return

        def fail(text):
            if monitor:
                self.monitor_chk.setChecked(False)
                self.status(tr("status.monitor_stopped", reason=text))
            else:
                QMessageBox.critical(self, tr("msg.error_title"), text)
        ip, mask, _, _ = get_ip_info(name)

        net_text = self.net_edit.text().strip()
        if net_text:
            try:
                network = ipaddress.IPv4Network(net_text, strict=False)
            except Exception:
                fail(tr("msg.invalid_network", net=net_text))
                return
        else:
            network = self._default_scan_network(ip, mask)
            if network is None:
                fail(tr("msg.adapter_no_ip"))
                return
        if network.num_addresses > 4096:
            fail(tr("msg.network_too_big", net=network))
            return

        hosts = list(network.hosts()) if network.prefixlen < 31 else list(network)
        if network.prefixlen >= 24:
            start_host, end_host = sorted((self.range_start.value(), self.range_end.value()))
            hosts = [h for h in hosts if start_host <= int(h) & 0xFF <= end_host]
        hosts = [str(h) for h in hosts]
        if not hosts:
            fail(tr("msg.empty_range"))
            return

        # Si la PC tiene IP en esa red se puede usar ARP (detecta equipos que no responden ping)
        local_ips = [a for a, _ in _live_ipv4(name)]
        on_link = any(ipaddress.IPv4Address(a) in network for a in local_ips)

        cfg = settings()
        ports = cfg.scan_ports()
        self._scan_is_monitor = monitor
        if not monitor:
            self.clear_results()
            self._scan_started = _now_str()
            self._scan_adapter = name
        self._scan_network = str(network)
        self.progress_bar.setRange(0, len(hosts))
        self.progress_bar.setValue(0)

        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_scan.setText(tr("btn.monitoring") if monitor else tr("btn.scanning"))
        self.main.set_busy(True)
        if not monitor:
            msg = tr("status.scanning", net=network, n=len(hosts), ports=len(ports),
                     how="ARP" if on_link else tr("status.off_link"))
            self.status(msg)
            self.log(msg)

        known = {d["ip"] for d in self.scan_results} if monitor else None
        self.scan_thread = ScannerThread(hosts, on_link=on_link, max_workers=cfg.int_value("scan_workers", 1, 256),
                                         known_ips=known, ports=ports,
                                         port_timeout=cfg.int_value("port_timeout_ms", 50, 5000) / 1000)
        self.scan_thread.seen.connect(self._on_host_seen)
        self.scan_thread.sweep_done.connect(self._on_sweep_done)
        self.scan_thread.found.connect(self.add_row_in_real_time)
        self.scan_thread.updated.connect(self.on_host_updated)
        self.scan_thread.progress.connect(self._on_scan_progress)
        if not monitor:
            self.scan_thread.phase.connect(self.status)
        self.scan_thread.completed.connect(self.on_scan_finished)
        self.scan_thread.canceled.connect(self.on_scan_canceled)
        self.scan_thread.start()

    def _on_scan_progress(self, done, total):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(min(done, total))

    def _refresh_stats(self):
        total = len(self.scan_results)
        cameras = sum(1 for d in self.scan_results if _is_camera(d["dev"]))
        servers = sum(1 for d in self.scan_results if _is_server(d["dev"]))
        self._update_stat_labels(total, cameras, servers)

    def _result_for(self, ip):
        return next((d for d in self.scan_results if d.get("ip") == ip), None)

    def _fetch_vendor_async(self, ip, mac):
        if not mac or mac == UNKNOWN:
            return

        def fetch_vendor():
            self.vendor_resolved.emit(ip, mac_vendor(mac))
        threading.Thread(target=fetch_vendor, daemon=True).start()

    def on_host_updated(self, data):
        """Llega el análisis completo (puertos/servicios) de un equipo ya listado."""
        if self._is_closing:
            return
        prev = self._result_for(data["ip"]) or {}
        prev_vendor = prev.get("vendor", VENDOR_PENDING)
        mac_changed = prev.get("mac", UNKNOWN) == UNKNOWN and data.get("mac", UNKNOWN) != UNKNOWN
        data["vendor"] = VENDOR_PENDING if mac_changed else prev_vendor
        data["is_new"] = prev.get("is_new", False)
        if self.inventory is not None:
            try:
                others = [d for d in self.scan_results if d["ip"] != data["ip"]] + [data]
                self.inventory.upsert_device(data, self._scan_network,
                                             _normalize_mac(data.get("mac")) in shared_macs(others))
            except Exception as e:
                logger.error(f"Inventario: {e}")
        self.update_row_by_ip(data)
        self._resort_and_filter()
        if data["is_new"]:
            self._paint_row(data["ip"], "warn_soft")
        if mac_changed:
            self._fetch_vendor_async(data["ip"], data["mac"])
        self._refresh_stats()

    def update_vendor_ui(self, ip, vendor):
        r = self._row_for_ip(ip)
        if r >= 0:
            self.table.setItem(r, COL_VENDOR, QTableWidgetItem(vendor))
        rec = self._result_for(ip)
        if rec is not None:
            rec["vendor"] = vendor

    def _fill_row(self, row: int, data: Dict) -> None:
        self.table.setItem(row, COL_HOST, self._host_item(data))
        mac_item = QTableWidgetItem(data.get("mac", UNKNOWN))
        mac_item.setForeground(QColor(THEME["text_secondary"]))
        self.table.setItem(row, COL_MAC, mac_item)
        self.table.setItem(row, COL_VENDOR, QTableWidgetItem(data.get("vendor", VENDOR_PENDING)))
        ports = data.get("ports", "")
        ports_item = QTableWidgetItem(ports[:30] + "…" if len(ports) > 30 else ports)
        ports_item.setForeground(QColor(THEME["ip"]))
        if len(ports) > 30:
            ports_item.setToolTip(ports)
        self.table.setItem(row, COL_PORTS, ports_item)
        dev = data.get("dev", "")
        dev_item = QTableWidgetItem(dev)
        if _is_camera(dev):
            dev_item.setForeground(QColor(THEME["ok"]))
        elif _is_server(dev):
            dev_item.setForeground(QColor(THEME["ip"]))
        self.table.setItem(row, COL_DEV, dev_item)
        self.table.setItem(row, COL_STATUS, self._status_item(data.get("status", STATUS_ONLINE) == STATUS_ONLINE))
        self._sync_action_buttons(row, data)
        self._sync_connect_buttons(row, data)

    def _sync_connect_buttons(self, row: int, data: Dict) -> None:
        """Un botón por servicio detectado: un clic abre la sesión (con la credencial guardada)."""
        ip = data["ip"]
        ports = {int(p) for p in str(data.get("ports", "")).split(",") if p.strip().isdigit()}
        found = [(proto, next(p for p in cand if p in ports)) for proto, cand in CONNECT_SERVICES
                 if ports & set(cand)]
        cell = QWidget()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(SP["xs"], 0, SP["xs"], 0)
        lay.setSpacing(SP["xs"])
        for proto, port in found:
            if proto == "web":                        # un solo botón "Web": HTTPS si está, si no HTTP
                proto = "https" if port in (443, 8443) else "http"
            btn = QPushButton("Web" if proto in ("http", "https") else PROTOCOL_LABELS[proto])
            btn.setObjectName("btnChip")
            set_help(btn, "chip_connect", proto=PROTOCOL_LABELS[proto], port=port)
            btn.clicked.connect(lambda ch=False, pr=proto, po=port: self._connect_from_table(ip, pr, po))
            lay.addWidget(btn)
        if not found:
            dash = QLabel("—" if ports or data.get("dev") != tr("dev.analyzing") else "…")
            dash.setObjectName("lblHint")
            lay.addWidget(dash)
        lay.addStretch(1)
        self.table.setCellWidget(row, COL_CONNECT, cell)

    def _connect_from_table(self, ip: str, proto: str, port: int) -> None:
        rec = self._result_for(ip) or {}
        meta = self._device_meta(rec) if rec else None
        host = (meta or {}).get("alias") or (rec.get("host") if rec.get("host") not in (None, "", "N/A") else "")
        self.open_session.emit({"protocol": proto, "host": ip, "port": port,
                                "name": f"{host or ip} ({PROTOCOL_LABELS[proto]})"})

    def _sync_action_buttons(self, row: int, data: Dict) -> None:
        cell = self.table.cellWidget(row, COL_ACTIONS)
        ip = data["ip"]
        if cell is None:
            cell = QWidget()
            lay = QHBoxLayout(cell)
            lay.setContentsMargins(SP["sm"], 0, SP["sm"], 0)
            lay.setSpacing(SP["xs"])
            btn = QPushButton(tr("btn.view"))
            btn.setObjectName("btnTable")
            set_help(btn, "view")
            btn.setMinimumWidth(52)
            # Se busca el registro al hacer clic: el análisis completo llega después de agregar la fila
            btn.clicked.connect(lambda ch=False, ip=ip: self.show_ip_details_from_record(self._result_for(ip) or {"ip": ip}))
            lay.addWidget(btn)
            lay.addStretch(1)
            self.table.setCellWidget(row, COL_ACTIONS, cell)

    def add_row_in_real_time(self, data):
        if self._is_closing or self._result_for(data["ip"]):
            return
        if data.get("mac", UNKNOWN) == UNKNOWN:
            data["vendor"] = VENDOR_PENDING
        self._fetch_vendor_async(data["ip"], data.get("mac"))

        # Insertar ordenado por IP (los equipos llegan en el orden en que responden)
        new_ip = int(ipaddress.IPv4Address(data["ip"]))
        row = self.table.rowCount()
        for r in range(self.table.rowCount()):
            item = self.table.item(r, COL_IP)
            try:
                if item and int(ipaddress.IPv4Address(item.text())) > new_ip:
                    row = r
                    break
            except Exception:
                pass
        self.table.insertRow(row)
        ip_item = IPTableItem(data["ip"])
        ip_item.setForeground(QColor(THEME["ip"]))
        font = ip_item.font(); font.setBold(True); ip_item.setFont(font)
        if data.get("found_by"):
            ip_item.setToolTip(tr("tip.found_by", how=data["found_by"]))
        self.table.setItem(row, COL_IP, ip_item)
        self._fill_row(row, data)
        self.scan_results.append(data)
        self._sync_table_empty()
        self._refresh_stats()
        self._resort_and_filter()
        if data.get("is_new"):
            self._paint_row(data["ip"], "warn_soft")
            self._monitor_log(tr("log.new_device", ip=data["ip"], mac=data.get("mac", UNKNOWN)), "warn")

    def update_row_by_ip(self, data):
        if self._is_closing:
            return
        r = self._row_for_ip(data["ip"])
        if r >= 0:
            self._fill_row(r, data)
        for idx, it in enumerate(self.scan_results):
            if it.get("ip") == data["ip"]:
                self.scan_results[idx] = data
                break
        else:
            self.scan_results.append(data)

    def _scan_finished_ui(self):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_scan.setText(tr("btn.start"))
        self.main.set_busy(False)

    def on_scan_finished(self):
        if not self._scan_is_monitor:
            QTimer.singleShot(0, self._record_scan_and_compare)
        self._scan_finished_ui()
        if self.monitor_chk.isChecked():
            if not self._monitor_timer.isActive():
                self._monitor_timer.start(self.monitor_spin.value() * 1000)
            if not self._scan_is_monitor or not self._monitor_events:
                self.status(tr("status.monitor_active", n=len(self.scan_results), s=self.monitor_spin.value()))
        else:
            self.status(tr("status.scan_done", n=len(self.scan_results)))
        if self.progress_bar.value() != self.progress_bar.maximum():
            self.progress_bar.setValue(self.progress_bar.maximum())

    def on_scan_canceled(self):
        self._scan_finished_ui()
        self.status(tr("status.scan_canceled"), 5000)
        self.log(tr("status.scan_canceled"), "warn")

    # ── Ventanas de detalle ─────────────────────────────────────────────
    def show_ip_details_from_record(self, row_data):
        try:
            ip_data = {
                "ip": row_data.get("ip", ""), "host": row_data.get("host", "N/A"),
                "mac": row_data.get("mac", UNKNOWN), "vendor": row_data.get("vendor", UNKNOWN),
                "ports": row_data.get("ports", ""), "dev": row_data.get("dev", ""),
                "status": row_data.get("status", STATUS_ONLINE), "services": row_data.get("services", {}),
                "special_services": row_data.get("special_services", []),
            }
            win = IPDetailsWindow(ip_data, self)
            win.show()
            win.raise_()
            win.activateWindow()
            self.detail_windows.append(win)
            win.destroyed.connect(lambda *_, w=win: self.safe_remove_detail_window(w))
        except Exception as e:
            import traceback
            logger.error(f"Error al abrir detalles de IP {row_data.get('ip')}: {e}\n{traceback.format_exc()}")
            QMessageBox.critical(self, tr("msg.error_title"), tr("msg.details_failed", detail=e))

    def safe_remove_detail_window(self, window):
        try:
            if window in self.detail_windows:
                self.detail_windows.remove(window)
        except Exception:
            pass

    def shutdown(self):
        self._is_closing = True
        try:
            self._monitor_timer.stop()
        except Exception:
            pass
        try:
            logging.getLogger().removeHandler(self._log_handler)
        except Exception:
            pass
        if self.inventory is not None:
            self.inventory.close()
        try:
            if self.scan_thread and self.scan_thread.isRunning():
                self.scan_thread.cancel()
                self.scan_thread.wait(2000)
        except Exception:
            pass
        for win in self.detail_windows[:]:
            try:
                win.close()
            except Exception:
                pass
        self.detail_windows.clear()


# ══════════════════════════════════════════════════════════════════════════
#  VENTANA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self, debug: bool = False):
        super().__init__()
        self.debug = debug
        os_name = "macOS" if IS_MACOS else ("Linux" if IS_LINUX else "Windows")
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — {os_name}" + (" [DEBUG]" if debug else ""))
        self.resize(1280, 720)
        self.setMinimumSize(1280, 720)
        icon_path = resource_path(APP_ICON_ICO)
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.session_store = SessionStore()
        self._remembered: Dict[str, Dict] = {}     # credenciales recordadas solo durante esta ejecución
        self.tools_window: Optional[ToolsWindow] = None
        self._build_ui()
        self._build_menus()
        self._build_status_bar()
        self.toast = Toast(self)

    # ── Estructura ─────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        self.sessions = SessionsPanel(self.session_store)
        self.sessions.open_requested.connect(self.open_session)
        self.sessions.quick_connect.connect(self.quick_connect)
        self.splitter.addWidget(self.sessions)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("workTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_context_menu)
        self.scanner = ScannerPage(self, self.debug)
        self.scanner.open_session.connect(self.open_session)
        self.scanner.save_session.connect(self._save_session_from_scan)
        self.tabs.addTab(self.scanner, icon("radar"), tr("tab.scanner"))
        right = getattr(QTabBar, "RightSide", None) or QTabBar.ButtonPosition.RightSide
        self.tabs.tabBar().setTabButton(0, right, None)   # el escáner no se cierra
        self.tabs.tabBar().setTabToolTip(0, tr("tip.tab_scanner"))
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([240, 1040])
        root.addWidget(self.splitter, 1)
        restore_window_state(self, splitters=self._persisted_splitters(),
                             headers={"devices": self.scanner.table.horizontalHeader()})

    def _persisted_splitters(self) -> dict:
        return {"main": self.splitter, "scanner": self.scanner.splitter}

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("headerBar")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(SP["lg"] + 4, SP["md"], SP["lg"] + 4, SP["md"])
        lay.setSpacing(SP["md"])
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(APP_NAME)
        t.setObjectName("lblAppTitle")
        s = QLabel(tr("app.subtitle"))
        s.setObjectName("lblAppSubtitle")
        titles.addWidget(t)
        titles.addWidget(s)
        lay.addLayout(titles)
        lay.addStretch(1)
        self.badge_busy = make_badge(tr("status.working"), "info")
        set_help(self.badge_busy, "badge_busy")
        self.badge_busy.setVisible(False)
        lay.addWidget(self.badge_busy, 0, Qt.AlignVCenter)
        self.badge_sessions = make_badge(tr("badge.sessions", n=0), "neutral")
        set_help(self.badge_sessions, "badge_sessions")
        lay.addWidget(self.badge_sessions, 0, Qt.AlignVCenter)
        admin = is_admin()
        self.badge_admin = make_badge(tr("badge.admin") if admin else tr("badge.user"), "ok" if admin else "neutral")
        set_help(self.badge_admin, "badge_admin")
        lay.addWidget(self.badge_admin, 0, Qt.AlignVCenter)
        return header

    def _build_menus(self) -> None:
        bar = self.menuBar()
        m_file = bar.addMenu(tr("menu.file"))
        m_view = bar.addMenu(tr("menu.view"))
        m_tools = bar.addMenu(tr("menu.tools"))
        m_help = bar.addMenu(tr("menu.help"))
        for m in (m_file, m_view, m_tools, m_help):
            m.setToolTipsVisible(True)

        def act(menu, key, slot, help_key=None, shortcut=None, checkable=False):
            a = QAction(tr(key), self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if help_key:
                set_help(a, help_key, shortcut=shortcut)
            a.setCheckable(checkable)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        act(m_file, "btn.new_session", lambda: self.sessions.new_session(), "new_session", "Ctrl+N")
        a_local = act(m_file, "action.local_terminal", self.open_local_terminal, "local_terminal", "Ctrl+Shift+T")
        a_local.setEnabled(has_pty())
        act(m_file, "action.start_scan", lambda: self.scanner.start_scan(), "start", "Ctrl+E")
        m_file.addSeparator()
        act(m_file, "action.credentials", self.show_credentials, "credentials", "Ctrl+K")
        act(m_file, "action.settings", self.show_settings, "preferences", "Ctrl+,")
        act(m_file, "action.open_data", lambda: webbrowser.open(nettool_data_dir().as_uri()), "open_data")
        act(m_file, "action.open_logfile",
            lambda: webbrowser.open((nettool_data_dir() / "networktool.log").as_uri()), "open_logfile")
        m_file.addSeparator()
        act(m_file, "action.exit", self.close, None, "Ctrl+Q")

        self.act_sidebar = act(m_view, "action.toggle_sessions", lambda on: self.sessions.setVisible(on),
                               "toggle_sessions", "F9", checkable=True)
        self.act_sidebar.setChecked(True)
        self.act_log = act(m_view, "action.toggle_log", lambda on: self.scanner.toggle_log(on), "toggle_log",
                           "Ctrl+L", checkable=True)

        act(m_tools, "tool.ping", lambda: self.show_tools("ping"), "tool_ping")
        act(m_tools, "tool.trace", lambda: self.show_tools("trace"), "tool_trace")
        act(m_tools, "tool.wol", lambda: self.show_tools("wol"), "tool_wol")
        act(m_tools, "tool.dns", lambda: self.show_tools("dns"), "tool_dns")
        act(m_tools, "tool.subnet", lambda: self.show_tools("subnet"), "tool_subnet")
        m_tools.addSeparator()
        act(m_tools, "btn.inventory", lambda: self.scanner.show_inventory(), "inventory", "Ctrl+I")
        act(m_tools, "action.compare", lambda: self.scanner.show_last_comparison(), "compare")
        act(m_tools, "btn.profiles", lambda: self.scanner.show_profile_manager(), "manage_profiles")
        act(m_tools, "action.update_oui", lambda: self.scanner.update_vendor_db(), "update_oui")

        a_repo = act(m_help, "action.github", lambda: webbrowser.open(APP_REPO_URL),
                     "github" if APP_REPO_URL else "github_soon")
        a_repo.setEnabled(bool(APP_REPO_URL))
        m_help.addSeparator()
        act(m_help, "action.about", lambda: _exec(AboutDialog(self)), "about", "F1")

    def _build_status_bar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.setSizeGripEnabled(False)
        sb.showMessage(tr("status.ready"))
        sep = "&nbsp;&nbsp;│&nbsp;&nbsp;"
        self.adapter_lbl = QLabel()
        self.adapter_lbl.setTextFormat(Qt.RichText)
        sb.addPermanentWidget(self.adapter_lbl)
        info = QLabel(f'<span style="font-weight:400;">{tr(f"theme.{THEME_NAME}")}{sep}v{APP_VERSION}{sep}'
                      f'{APP_DEVELOPER}</span>')
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet("padding-right: 24px;")   # deja lugar al grip
        sb.addPermanentWidget(info)
        self._grip = DotGripWidget(self, bg_color=THEME["status_bg"])
        self._reposition_grip()

    def set_adapter_status(self, text: str) -> None:
        if hasattr(self, "adapter_lbl"):
            self.adapter_lbl.setText(f'<span style="font-weight:400;">{_html_escape(text)}</span>&nbsp;&nbsp;│')

    def set_busy(self, busy: bool) -> None:
        self.badge_busy.setVisible(busy)

    def _reposition_grip(self) -> None:
        if hasattr(self, "_grip"):
            self._grip.move(self.width() - self._grip.width(), self.height() - self._grip.height())
            self._grip.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_grip()

    # ── Sesiones ───────────────────────────────────────────────────────
    def _update_sessions_badge(self) -> None:
        n = sum(1 for i in range(self.tabs.count()) if getattr(self.tabs.widget(i), "is_connected", False))
        set_badge(self.badge_sessions, tr("badge.sessions", n=n), "ok" if n else "neutral")

    def _save_session_from_scan(self, preset: Dict) -> None:
        if not self.sessions.isVisible():
            self.act_sidebar.setChecked(True)
            self.sessions.setVisible(True)
        self.sessions.new_session(preset)

    def open_session(self, session: Dict, cred: Optional[Dict] = None) -> None:
        from networktool.data.sessions import clean_session
        s = clean_session(session)
        proto = s["protocol"]
        if not PROTOCOLS[proto]["embedded"]:
            ok, detail = launch_external(s)
            if ok:
                self.statusBar().showMessage(tr("status.launched", name=s["name"]), 5000)
            else:
                QMessageBox.warning(self, tr("msg.error_title"), detail)
            return
        missing = terminal_missing_libs(proto)
        if missing:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.missing_libs", libs=missing))
            return
        if proto in LOCAL_PROTOCOLS:
            cred = self._local_command(s)
            if cred is None:
                return
        if cred is None:
            cred = self._credentials_for(s)
            if cred is None:
                return
        if proto in ("ssh", "telnet", "wsl", "shell"):
            tab = TerminalTab(s, cred)
            tab.broadcast.connect(lambda payload, src=tab: self._multiexec(src, payload))
        else:
            tab = FileBrowserTab(s, cred)
            tab.state_changed.connect(lambda on, t=tab: self._on_session_ok(t) if on else None)
        if hasattr(tab, "connected_ok"):
            tab.connected_ok.connect(lambda t=tab: self._on_session_ok(t))
        tab.auth_failed.connect(lambda t=tab: self._on_auth_failed(t))
        tab.state_changed.connect(lambda *_: self._update_sessions_badge())
        tab.state_changed.connect(lambda *_, t=tab: self._update_tab_title(t))
        idx = self.tabs.addTab(tab, protocol_icon(proto), s["name"])
        self.tabs.setTabToolTip(idx, f"{PROTOCOL_LABELS[proto]} · {s['host']}:{s['port']}")
        self.tabs.setCurrentIndex(idx)
        tab.connect_session()

    def _local_command(self, s: Dict) -> Optional[Dict]:
        """Comando de una sesión WSL / terminal local."""
        if s["protocol"] == "wsl":
            if not list_distros() and not s.get("distro"):
                QMessageBox.information(self, "WSL", tr("msg.wsl_missing"))
                return None
            command = wsl_command(s.get("distro", ""))
        else:
            shells = {sh["key"]: sh for sh in local_shells()}
            sh = shells.get(s.get("shell") or "powershell") or next(iter(shells.values()), None)
            if sh is None:
                QMessageBox.warning(self, tr("msg.error_title"), tr("msg.no_local_shell"))
                return None
            command = sh["command"]
        return {"host": "", "port": 0, "username": "", "password": "", "command": command,
                "encoding": "utf-8", "_save": False, "_cred_id": "", "_session_id": s["id"]}

    def open_local_terminal(self) -> None:
        from networktool.data.sessions import local_session
        self.open_session(local_session("shell", "powershell", "PowerShell"))

    # ── Credenciales: bóveda cifrada + autocompletar ───────────────────
    def _base_cred(self, s: Dict) -> Dict:
        return dict(host=s["host"], port=s["port"], username=s["username"], key_file=s["key_file"],
                    remote_path=s["remote_path"], ftp_passive=s["ftp_passive"], encoding=s["encoding"],
                    password="", _save=False, _cred_id="", _session_id=s["id"])

    def _saved_credential(self, s: Dict) -> Optional[Dict]:
        """Credencial guardada para la sesión: la asignada, o la ya usada en ese equipo."""
        v = vault()
        if s.get("credential_id"):
            c = v.get(s["credential_id"])
            if c is not None:
                return c
        hits = v.for_host(s["host"], s["port"], s["username"])
        return hits[0] if hits else None

    def _credentials_for(self, s: Dict, force_prompt: bool = False, error: str = "") -> Optional[Dict]:
        cred = self._base_cred(s)
        v = vault()
        saved = None if force_prompt else self._saved_credential(s)
        if saved is not None:
            pw = v.password(saved)
            if pw or s["key_file"]:
                cred.update(username=saved["username"], password=pw, _cred_id=saved["id"])
                self.statusBar().showMessage(tr("status.autofilled", name=v.label(saved)), 5000)
                return cred
        remembered = None if force_prompt else self._remembered.get(s["id"])
        if remembered:
            return dict(cred, **remembered)
        if s["protocol"] == "telnet" and not force_prompt:
            return cred                       # sin credencial guardada: el login se hace en la terminal
        dlg = CredentialsDialog(s, v, self, error=error)
        if _exec(dlg) != QDialog.Accepted:
            return None
        cred.update(username=dlg.username(), password=dlg.password(), _save=dlg.save_requested(),
                    _cred_id=dlg.chosen_id())
        if v.policy == "never":
            self._remembered[s["id"]] = {"username": cred["username"], "password": cred["password"]}
        return cred

    def _on_session_ok(self, tab) -> None:
        """Conexión autenticada: guarda la credencial en la bóveda si el usuario lo pidió."""
        cred, v = tab.cred, vault()
        if not cred.get("password") or v.policy == "never":
            return
        if cred.get("_cred_id") and v.get(cred["_cred_id"]) and v.password(v.get(cred["_cred_id"])) == cred["password"]:
            v.touch(cred["_cred_id"], cred["host"], cred["port"])
        elif cred.get("_replace_id") and v.get(cred["_replace_id"]) and \
                v.get(cred["_replace_id"]).get("username") == cred["username"]:
            # la contraseña guardada había dejado de funcionar: se actualiza esa misma credencial
            old = v.get(cred["_replace_id"])
            v.upsert(old.get("name", ""), cred["username"], cred["password"], cid=old["id"])
            v.touch(old["id"], cred["host"], cred["port"])
            cred["_cred_id"], cred["_replace_id"] = old["id"], ""
            self.statusBar().showMessage(tr("status.cred_saved", user=cred["username"]), 5000)
        elif cred.get("_save") or v.policy == "always":
            saved = v.remember(cred["host"], cred["port"], cred["username"], cred["password"])
            cred["_cred_id"], cred["_save"] = saved["id"], False
            self.statusBar().showMessage(tr("status.cred_saved", user=cred["username"]), 5000)

    def _on_auth_failed(self, tab) -> None:
        s = dict(tab.session, username=tab.cred.get("username") or tab.session["username"])
        failed_id = tab.cred.get("_cred_id", "")
        new = self._credentials_for(s, force_prompt=True, error=tr("msg.auth_failed"))
        if new is not None:
            upd = {k: new[k] for k in ("username", "password", "_save", "_cred_id")}
            upd["_replace_id"] = failed_id if vault().policy != "never" else ""
            tab.reconnect_with(upd)

    def _multiexec(self, source, payload: bytes) -> None:
        """MultiExec: lo que se escribe en una terminal marcada va a todas las marcadas."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w is not source and isinstance(w, TerminalTab) and w.btn_multi.isChecked():
                w.send(payload)

    def _update_tab_title(self, tab) -> None:
        i = self.tabs.indexOf(tab)
        if i >= 0:
            self.tabs.tabBar().setTabTextColor(
                i, QColor(THEME["text"] if getattr(tab, "is_connected", False) else THEME["text_muted"]))

    def quick_connect(self, text: str) -> None:
        """"usuario@equipo:puerto", "sftp://equipo", "telnet equipo 2323"…"""
        s = parse_quick_connect(text)
        if s is None:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.quick_invalid"))
            return
        self.open_session(s)

    def _tab_context_menu(self, pos) -> None:
        index = self.tabs.tabBar().tabAt(pos)
        w = self.tabs.widget(index) if index >= 0 else None
        if w is None or w is self.scanner:
            return
        menu = QMenu(self)
        if hasattr(w, "connect_session"):
            menu.addAction(tr("action.reconnect")).triggered.connect(lambda: w.connect_session())
            menu.addAction(tr("action.duplicate_tab")).triggered.connect(
                lambda: self.open_session(w.session, {k: v for k, v in w.cred.items()}))
        menu.addAction(tr("action.rename_tab")).triggered.connect(lambda: self._rename_tab(index))
        if not self.session_store.get(w.session.get("id", "")):
            menu.addAction(tr("action.save_as_session")).triggered.connect(
                lambda: self.sessions.new_session(dict(w.session, id="")))
        menu.addSeparator()
        menu.addAction(tr("action.close_others")).triggered.connect(lambda: self._close_others(w))
        menu.addAction(tr("action.close_tab")).triggered.connect(lambda: self.close_tab(self.tabs.indexOf(w)))
        _exec_menu(menu, self.tabs.tabBar().mapToGlobal(pos))

    def _rename_tab(self, index: int) -> None:
        from networktool.qt_compat import QInputDialog
        name, ok = QInputDialog.getText(self, tr("action.rename_tab"), tr("lbl.name"), QLineEdit.Normal,
                                        self.tabs.tabText(index))
        if ok and name.strip():
            self.tabs.setTabText(index, name.strip())

    def _close_others(self, keep) -> None:
        for i in reversed(range(self.tabs.count())):
            w = self.tabs.widget(i)
            if w is not keep and w is not self.scanner:
                self.close_tab(i)

    def show_credentials(self) -> None:
        _exec(CredentialsManagerDialog(vault(), self))

    def close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.scanner:
            return
        if getattr(widget, "is_connected", False) and QMessageBox.question(
                self, tr("msg.close_session_title"), tr("msg.close_session", name=self.tabs.tabText(index)),
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if hasattr(widget, "shutdown"):
            widget.shutdown()
        self.tabs.removeTab(index)
        widget.deleteLater()
        self._update_sessions_badge()

    def _on_tab_changed(self, index: int) -> None:
        w = self.tabs.widget(index)
        if hasattr(w, "view"):
            w.view.setFocus()

    # ── Ventanas auxiliares ────────────────────────────────────────────
    def show_tools(self, tab: str = "ping", target: str = "", mac: str = ""):
        if self.tools_window is None:
            self.tools_window = ToolsWindow(self.scanner)
            icon_path = resource_path(APP_ICON_ICO)
            if os.path.exists(icon_path):
                self.tools_window.setWindowIcon(QIcon(icon_path))
        else:
            self.tools_window._wol_fill()
        self.tools_window.open_tab(tab, target, mac)

    def show_settings(self) -> None:
        dlg = SettingsDialog(self)
        if _exec(dlg) == QDialog.Accepted:
            self.scanner.monitor_spin.setValue(settings().int_value("monitor_interval", 10, 3600))
            self.statusBar().showMessage(tr("status.settings_saved"), 4000)

    def closeEvent(self, event):
        open_sessions = [i for i in range(self.tabs.count())
                         if getattr(self.tabs.widget(i), "is_connected", False)]
        if open_sessions and QMessageBox.question(self, tr("msg.exit_title"),
                                                  tr("msg.exit_sessions", n=len(open_sessions)),
                                                  QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            event.ignore()
            return
        smoke_mark("close: tabs")
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "shutdown") and w is not self.scanner:
                w.shutdown()
        smoke_mark("close: scanner")
        self.scanner.shutdown()
        if self.tools_window is not None:
            self.tools_window.close()
        smoke_mark("close: child processes")
        _cleanup_child_processes()
        smoke_mark("close: window state")
        save_window_state(self, splitters=self._persisted_splitters(),
                          headers={"devices": self.scanner.table.horizontalHeader()})
        smoke_mark("close: accepted")
        event.accept()
