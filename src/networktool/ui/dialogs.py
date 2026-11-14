"""Diálogos y ventanas secundarias."""

import csv
import ipaddress
import platform
import re
import subprocess
import webbrowser
from typing import Dict, List, Optional

from networktool.common import (
    APP_DEVELOPER, APP_NAME, APP_REPO_URL, APP_VERSION, IS_WINDOWS, STATUS_ONLINE, _IPV4_RE, _html_escape,
    _http_session, _normalize_mask, mask_to_cidr, nettool_data_dir,
)
from networktool.data.inventory import Inventory
from networktool.data.profiles import ProfileStore, _clean_profile
from networktool.data.sessions import PORT_TO_PROTOCOL
from networktool.i18n import LANGUAGES, get_lang_code, set_lang_code, tr, tr_value
from networktool.net.adapters import get_ip_info
from networktool.net.ipconfig import _configured_ipv4, _parse_extra_ips, _validate_static
from networktool.net.services import get_service_name
from networktool.qt_compat import (
    QAbstractItemView, QApplication, QCheckBox, QColor, QComboBox, QDialog, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSize, QSpinBox, QStackedWidget,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, Qt, _QT_BACKEND, _exec,
    _exec_menu,
)
from networktool.reports import comparison_html, device_history_text
from networktool.settings import DEFAULT_SCAN_PORTS, format_port_spec, parse_port_spec, settings
from networktool.system import (
    _make_ntp_linux_cmd, _launch_rdp, open_arp, open_in_terminal, open_in_vlc, open_netstat,
    open_nmap_quick, open_ping, open_protocol, open_traceroute,
)
from networktool.ui.theme import (
    ICON_SIZE, SP, THEME, copy_to_clipboard, field_label, get_theme_name, icon, icon_pixmap, make_button,
    make_card, make_divider, make_empty_state, open_with_system, set_help, set_theme_name, show_message, span,
)
from networktool.workers import FuncWorker, SingleIPScannerThread


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  BASE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class _Dialog(QDialog):
    """Diálogo con título, márgenes estándar y fila de botones al pie."""

    def __init__(self, title: str, parent=None, subtitle: str = None, min_width: int = 440):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(min_width)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        self.root.setSpacing(SP["md"])
        lbl = QLabel(title)
        lbl.setObjectName("lblTitle")
        self.root.addWidget(lbl)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("lblSubtitle")
            sub.setWordWrap(True)
            self.root.addWidget(sub)

    def form(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(SP["md"])
        grid.setVerticalSpacing(SP["sm"])
        grid.setColumnStretch(1, 1)
        self.root.addLayout(grid)
        return grid

    @staticmethod
    def add_row(grid: QGridLayout, row: int, label: str, widget, help_key: str = None):
        grid.addWidget(field_label(label), row, 0, Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(widget, row, 1)
        if help_key:
            set_help(widget, help_key)

    def buttons(self, *buttons) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(SP["sm"])
        row.addStretch(1)
        for b in buttons:
            row.addWidget(b)
        self.root.addLayout(row)
        return row


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("lblHint")
    lbl.setWordWrap(True)
    return lbl


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  CONFIGURACIÓN IP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class ManualConfigDialog(_Dialog):
    def __init__(self, adapter_name, parent=None):
        super().__init__(tr("dlg.manual_ip"), parent, tr("dlg.manual_ip_sub", adapter=adapter_name), 460)
        self.adapter_name = adapter_name
        self.extra_ips: List[str] = []
        grid = self.form()
        self.ip_edit = QLineEdit(); self.ip_edit.setPlaceholderText(tr("ph.ip"))
        self.mask_edit = QLineEdit(); self.mask_edit.setPlaceholderText(tr("ph.mask"))
        self.gateway_edit = QLineEdit(); self.gateway_edit.setPlaceholderText(tr("ph.gateway"))
        self.dns_edit = QLineEdit(); self.dns_edit.setPlaceholderText(tr("ph.dns"))
        self.extra_edit = QPlainTextEdit(); self.extra_edit.setFixedHeight(64)
        self.extra_edit.setPlaceholderText(tr("ph.extra_ips"))
        self.add_row(grid, 0, tr("lbl.ip"), self.ip_edit, "ip")
        self.add_row(grid, 1, tr("lbl.mask"), self.mask_edit, "mask")
        self.add_row(grid, 2, "Gateway", self.gateway_edit, "gateway")
        self.add_row(grid, 3, "DNS", self.dns_edit, "dns")
        self.add_row(grid, 4, tr("lbl.extra_ips"), self.extra_edit, "extra_ips")
        self.root.addWidget(_hint(tr("hint.admin_needed")))
        self.buttons(make_button(tr("common.cancel"), None, None, self.reject),
                     make_button(tr("btn.apply"), "btnPrimary", "apply_static", self.apply_config))

    def apply_config(self):
        ip, mask = self.ip_edit.text().strip(), self.mask_edit.text().strip()
        gateway, dns = self.gateway_edit.text().strip(), self.dns_edit.text().strip() or None
        if not ip or not mask:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.ip_mask_required"))
            return
        try:
            _, norm_mask, _, _ = _validate_static(ip, mask, gateway, dns)
            extra = _parse_extra_ips(self.extra_edit.toPlainText().split(), norm_mask, ip)
        except ValueError as e:
            QMessageBox.warning(self, tr("msg.error_title"), str(e))
            return
        self.mask_edit.setText(norm_mask)
        self.extra_ips = [f"{a}/{mask_to_cidr(m)}" for a, m in extra]
        self.accept()


class ProfileManagerDialog(_Dialog):
    """Alta, edición, orden, importación y exportación de perfiles de IP."""

    def __init__(self, store: "ProfileStore", adapter: str = "", parent=None):
        super().__init__(tr("dlg.profiles"), parent, tr("dlg.profiles_sub"), 820)
        self.store = store
        self.adapter = adapter
        self._current = -1
        self.setMinimumHeight(480)

        body = QHBoxLayout()
        body.setSpacing(SP["lg"])
        left = QVBoxLayout()
        left.setSpacing(SP["sm"])
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._load_row)
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.list)
        self.list_stack.addWidget(make_empty_state(tr("empty.profiles_list"), "network"))
        left.addWidget(self.list_stack, 1)
        order = QHBoxLayout()
        order.addWidget(make_button(tr("btn.move_up"), None, "move_up", lambda: self._move(-1)))
        order.addWidget(make_button(tr("btn.move_down"), None, "move_down", lambda: self._move(1)))
        left.addLayout(order)
        body.addLayout(left, 2)

        card, right = make_card(tr("section.profile"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(SP["md"])
        grid.setVerticalSpacing(SP["sm"])
        grid.setColumnStretch(1, 1)
        self.f_name = QLineEdit()
        self.f_group = QLineEdit(); self.f_group.setPlaceholderText(tr("ph.profile_group"))
        self.f_ip = QLineEdit(); self.f_ip.setPlaceholderText(tr("ph.ip"))
        self.f_mask = QLineEdit(); self.f_mask.setPlaceholderText(tr("ph.mask"))
        self.f_gw = QLineEdit(); self.f_gw.setPlaceholderText(tr("ph.optional"))
        self.f_dns = QLineEdit(); self.f_dns.setPlaceholderText(tr("ph.dns"))
        self.f_extra = QPlainTextEdit(); self.f_extra.setFixedHeight(60)
        self.f_extra.setPlaceholderText(tr("ph.extra_ips"))
        for r, (label, w, h) in enumerate(((tr("lbl.name"), self.f_name, "profile_name"),
                                           (tr("lbl.group"), self.f_group, "profile_group"),
                                           (tr("lbl.ip"), self.f_ip, "ip"), (tr("lbl.mask"), self.f_mask, "mask"),
                                           ("Gateway", self.f_gw, "gateway"), ("DNS", self.f_dns, "dns"),
                                           (tr("lbl.extra_ips"), self.f_extra, "extra_ips"))):
            self.add_row(grid, r, label, w, h)
        right.addLayout(grid)
        row1 = QHBoxLayout()
        row1.setSpacing(SP["sm"])
        row1.addWidget(make_button(tr("btn.new"), None, "profile_new", self._new))
        row1.addWidget(make_button(tr("btn.from_current"), None, "from_current", self._from_current))
        row1.addStretch(1)
        row1.addWidget(make_button(tr("btn.delete"), "btnDanger", "profile_delete", self._delete))
        row1.addWidget(make_button(tr("btn.save"), "btnPrimary", "profile_save", self._save))
        right.addLayout(row1)
        right.addStretch(1)
        body.addWidget(card, 3)
        self.root.addLayout(body, 1)

        self.buttons(make_button(tr("btn.import"), "btnSecondary", "profiles_import", self._import),
                     make_button(tr("btn.export"), "btnSecondary", "profiles_export", self._export),
                     make_button(tr("common.close"), None, None, self.accept))
        self._refresh_list(0)

    @staticmethod
    def _label(p):
        return (f"[{p['group']}] " if p.get("group") else "") + f"{p['name']}  —  {p['ip']}"

    def _refresh_list(self, select=None):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.store.profiles:
            self.list.addItem(self._label(p))
        self.list.blockSignals(False)
        self.list_stack.setCurrentIndex(0 if self.store.profiles else 1)
        if self.store.profiles:
            row = min(max(select if select is not None else self._current, 0), len(self.store.profiles) - 1)
            self.list.setCurrentRow(row)
            self._load_row(row)
        else:
            self._new()

    def _load_row(self, row):
        self._current = row
        if not 0 <= row < len(self.store.profiles):
            return
        p = self.store.profiles[row]
        self.f_name.setText(p["name"]); self.f_group.setText(p.get("group", ""))
        self.f_ip.setText(p["ip"]); self.f_mask.setText(p["mask"]); self.f_gw.setText(p.get("gateway", ""))
        self.f_dns.setText(p.get("dns", "")); self.f_extra.setPlainText("\n".join(p.get("extra_ips", [])))

    def _new(self):
        self._current = -1
        self.list.clearSelection()
        for w in (self.f_name, self.f_group, self.f_ip, self.f_gw, self.f_dns):
            w.clear()
        self.f_mask.setText("255.255.255.0"); self.f_extra.clear()
        self.f_name.setFocus()

    def _form_profile(self) -> Optional[Dict]:
        try:
            ip, mask, gw, dns = _validate_static(self.f_ip.text(), self.f_mask.text(), self.f_gw.text(), self.f_dns.text())
            extra = _parse_extra_ips(self.f_extra.toPlainText().split(), mask, ip)
        except ValueError as e:
            QMessageBox.warning(self, tr("msg.invalid_profile"), str(e))
            return None
        return _clean_profile({
            "name": self.f_name.text().strip() or ip, "group": self.f_group.text(), "ip": ip, "mask": mask,
            "gateway": gw, "dns": ", ".join(dns), "extra_ips": [f"{a}/{mask_to_cidr(m)}" for a, m in extra],
        })

    def _save(self):
        p = self._form_profile()
        if not p:
            return
        if 0 <= self._current < len(self.store.profiles):
            self.store.profiles[self._current] = p
            row = self._current
        else:
            self.store.profiles.append(p)
            row = len(self.store.profiles) - 1
        self.store.save()
        self._refresh_list(row)

    def _delete(self):
        if not 0 <= self._current < len(self.store.profiles):
            return
        p = self.store.profiles[self._current]
        if QMessageBox.question(self, tr("msg.delete_title"), tr("msg.delete_profile", name=p["name"]),
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            del self.store.profiles[self._current]
            self.store.save()
            self._refresh_list(self._current - 1)

    def _move(self, delta):
        i, j = self._current, self._current + delta
        if 0 <= i < len(self.store.profiles) and 0 <= j < len(self.store.profiles):
            self.store.profiles[i], self.store.profiles[j] = self.store.profiles[j], self.store.profiles[i]
            self.store.save()
            self._refresh_list(j)

    def _from_current(self):
        if not self.adapter:
            return
        ip, mask, gw, _ = get_ip_info(self.adapter)
        if not re.fullmatch(_IPV4_RE, ip or ""):
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.adapter_no_ip_named", adapter=self.adapter))
            return
        self._new()
        self.f_name.setText(f"{self.adapter} {ip}")
        self.f_ip.setText(ip); self.f_mask.setText(mask)
        self.f_gw.setText(gw if re.fullmatch(_IPV4_RE, gw or "") else "")
        extra = [f"{a}/{mask_to_cidr(m)}" for a, m in _configured_ipv4(self.adapter) if a != ip]
        self.f_extra.setPlainText("\n".join(extra))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("btn.import"), "", tr("filter.json"))
        if not path:
            return
        replace = QMessageBox.question(self, tr("btn.import"), tr("msg.import_replace"),
                                       QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes
        try:
            n = self.store.import_from(path, replace=replace)
        except Exception as e:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.import_failed", detail=e))
            return
        self._refresh_list(0)
        QMessageBox.information(self, tr("btn.import"), tr("msg.profiles_imported", n=n))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("btn.export"), "profiles_networktool.json", tr("filter.json"))
        if path:
            try:
                self.store.export_to(path)
            except Exception as e:
                QMessageBox.warning(self, tr("msg.error_title"), tr("msg.export_failed", detail=e))


class AdapterIPsDialog(_Dialog):
    """Lista las IPs del adaptador y permite agregar o quitar IPs secundarias
    sin tocar el resto de la configuración."""

    def __init__(self, tool, adapter: str):
        super().__init__(tr("dlg.adapter_ips"), tool, adapter, 480)
        self.tool = tool
        self.adapter = adapter
        self.setMinimumHeight(400)
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
        self.root.addWidget(self.info)
        self.list = QListWidget()
        self.root.addWidget(self.list, 1)
        add = QHBoxLayout()
        add.setSpacing(SP["sm"])
        self.f_ip = QLineEdit(); self.f_ip.setPlaceholderText(tr("ph.ip"))
        set_help(self.f_ip, "ip")
        self.f_mask = QLineEdit("255.255.255.0")
        set_help(self.f_mask, "mask")
        add.addWidget(self.f_ip, 2)
        add.addWidget(self.f_mask, 1)
        add.addWidget(make_button(tr("btn.add"), "btnPrimary", "add_secondary", self._add))
        self.root.addLayout(add)
        self.root.addWidget(_hint(tr("hint.secondary_ip")))
        self.buttons(make_button(tr("btn.remove_ip"), "btnDanger", "remove_ip", self._remove),
                     make_button(tr("common.close"), None, None, self.accept))
        self.refresh()

    def refresh(self):
        _, _, gw, dhcp = get_ip_info(self.adapter)
        self.info.setText(f'<span style="color:{THEME["text_secondary"]};">DHCP</span>&nbsp;{span(tr_value(dhcp), "ip")}'
                          f'&nbsp;&nbsp;│&nbsp;&nbsp;<span style="color:{THEME["text_secondary"]};">Gateway</span>'
                          f'&nbsp;{span(tr_value(gw), "ip")}')
        self.list.clear()
        for a, m in _configured_ipv4(self.adapter):
            self.list.addItem(f"{a}/{mask_to_cidr(m)}   ({m})")

    def _selected_ip(self):
        item = self.list.currentItem()
        return item.text().split("/")[0] if item else None

    def _remove(self):
        ip = self._selected_ip()
        if not ip:
            return
        if self.list.count() <= 1:
            QMessageBox.information(self, tr("btn.remove_ip"), tr("msg.only_ip"))
            return
        if QMessageBox.question(self, tr("btn.remove_ip"), tr("msg.remove_ip_confirm", ip=ip, adapter=self.adapter),
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.tool.apply_ip_config_async("remove_ip", self.adapter, ip, on_done=self.refresh)

    def _add(self):
        ip, mask = self.f_ip.text().strip(), self.f_mask.text().strip()
        try:
            ipaddress.IPv4Address(ip)
            _normalize_mask(mask)
        except Exception:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.invalid_ip_mask"))
            return
        self.tool.apply_ip_config_async("add_ip", self.adapter, ip, mask, on_done=self.refresh)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  INVENTARIO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class AliasDialog(_Dialog):
    def __init__(self, device: Dict, parent=None):
        sub = f"IP {device.get('ip', '')}  ·  MAC {device.get('mac', '')}"
        if device.get("vendor"):
            sub += f"  ·  {device['vendor']}"
        super().__init__(tr("dlg.alias"), parent, sub, 440)
        grid = self.form()
        self.alias = QLineEdit(device.get("alias") or "")
        self.alias.setPlaceholderText(tr("ph.alias"))
        self.notes = QPlainTextEdit(device.get("notes") or "")
        self.notes.setFixedHeight(100)
        self.add_row(grid, 0, tr("lbl.alias"), self.alias, "alias")
        self.add_row(grid, 1, tr("lbl.notes"), self.notes, "notes")
        self.buttons(make_button(tr("common.cancel"), None, None, self.reject),
                     make_button(tr("btn.save"), "btnPrimary", "save_alias", self.accept))


class CompareDialog(_Dialog):
    def __init__(self, cmp: Dict, inventory: "Inventory", parent=None):
        super().__init__(tr("dlg.compare"), parent, None, 640)
        self.setMinimumHeight(480)
        view = QTextEdit()
        view.setObjectName("reportView")
        view.setReadOnly(True)
        view.setHtml(comparison_html(cmp, inventory))
        self.root.addWidget(view, 1)
        self.buttons(make_button(tr("common.close"), None, None, self.accept))


class InventoryDialog(_Dialog):
    """Todos los equipos vistos alguna vez y el historial de escaneos."""
    COLS = ["col.alias", "col.ip", "col.mac", "col.vendor", "col.type", "col.first_seen", "col.last_seen", "col.notes"]

    def __init__(self, inventory: "Inventory", parent=None):
        super().__init__(tr("dlg.inventory"), parent, tr("dlg.inventory_sub"), 1000)
        self.inv = inventory
        self.tool = parent
        self.resize(1100, 620)
        tabs = QTabWidget()
        self.root.addWidget(tabs, 1)

        # Equipos
        w_dev = QWidget()
        dl = QVBoxLayout(w_dev)
        dl.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        dl.setSpacing(SP["sm"])
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("ph.search_inventory"))
        self.search.setClearButtonEnabled(True)
        set_help(self.search, "search_inventory")
        self.search.textChanged.connect(self.reload_devices)
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("lblHint")
        top.addWidget(self.search, 1)
        top.addWidget(self.count_lbl)
        dl.addLayout(top)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in self.COLS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda r, c: self._edit())
        self.dev_stack = QStackedWidget()
        self.dev_stack.addWidget(self.table)
        self.dev_stack.addWidget(make_empty_state(tr("empty.inventory"), "database"))
        dl.addWidget(self.dev_stack, 1)
        btns = QHBoxLayout()
        btns.addWidget(make_button(tr("btn.edit_alias"), None, "edit_alias", self._edit))
        btns.addWidget(make_button(tr("btn.history"), None, "history", self._history))
        btns.addWidget(make_button(tr("btn.delete"), "btnDanger", "inventory_delete", self._delete))
        btns.addStretch(1)
        btns.addWidget(make_button(tr("action.export_csv"), "btnSecondary", "inventory_csv", self._export_csv))
        dl.addLayout(btns)
        tabs.addTab(w_dev, tr("tab.devices"))

        # Escaneos
        w_sc = QWidget()
        sl = QVBoxLayout(w_sc)
        sl.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        self.scans_tbl = QTableWidget(0, 5)
        self.scans_tbl.setHorizontalHeaderLabels(["#", tr("col.date"), tr("col.network"), tr("lbl.adapter"),
                                                  tr("col.devices")])
        self.scans_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.scans_tbl.verticalHeader().setVisible(False)
        self.scans_tbl.setShowGrid(False)
        self.scans_tbl.setAlternatingRowColors(True)
        self.scans_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scans_tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        sl.addWidget(self.scans_tbl, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(make_button(tr("btn.compare_selected"), "btnPrimary", "compare_selected", self._compare_selected))
        sl.addLayout(row)
        tabs.addTab(w_sc, tr("tab.scans"))

        self.buttons(make_button(tr("common.close"), None, None, self.accept))
        self._rows: List[Dict] = []
        self.reload_devices()
        self.reload_scans()

    def reload_devices(self, *_):
        self._rows = self.inv.all_devices(self.search.text().strip())
        self.table.setRowCount(len(self._rows))
        for r, d in enumerate(self._rows):
            vals = [d.get("alias"), d.get("ip"), d.get("mac"), d.get("vendor"), d.get("dev"),
                    d.get("first_seen"), d.get("last_seen"), (d.get("notes") or "").replace("\n", " ")]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v or ""))
                if c == 0 and v:
                    it.setForeground(QColor(THEME["counter"]))
                elif c == 1:
                    it.setForeground(QColor(THEME["ip"]))
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()
        self.count_lbl.setText(tr("lbl.n_devices", n=len(self._rows)))
        self.dev_stack.setCurrentIndex(0 if self._rows or self.search.text() else 1)

    def reload_scans(self):
        scans = self.inv.scans()
        self.scans_tbl.setRowCount(len(scans))
        for r, s in enumerate(scans):
            for c, v in enumerate([s["id"], s["started"], s["network"], s["adapter"], s["total"]]):
                self.scans_tbl.setItem(r, c, QTableWidgetItem(str(v)))

    def _selected(self) -> Optional[Dict]:
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def _edit(self):
        d = self._selected()
        if not d:
            return
        dlg = AliasDialog(d, self)
        if _exec(dlg) == QDialog.Accepted:
            self.inv.set_meta(d["key"], dlg.alias.text(), dlg.notes.toPlainText())
            self.reload_devices()
            if self.tool is not None and hasattr(self.tool, "refresh_aliases"):
                self.tool.refresh_aliases()

    def _history(self):
        d = self._selected()
        if d:
            QMessageBox.information(self, tr("dlg.device_history"), device_history_text(self.inv, d))

    def _delete(self):
        d = self._selected()
        if d and QMessageBox.question(self, tr("msg.delete_title"),
                                      tr("msg.delete_device", name=d.get("alias") or d.get("ip")),
                                      QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.inv.delete_device(d["key"])
            self.reload_devices()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("action.export_csv"), "inventory.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([tr(c) for c in self.COLS] + ["Hostname", tr("col.ports"), tr("col.network")])
                for d in self._rows:
                    w.writerow([d.get("alias"), d.get("ip"), d.get("mac"), d.get("vendor"), d.get("dev"),
                                d.get("first_seen"), d.get("last_seen"), d.get("notes"),
                                d.get("hostname"), d.get("ports"), d.get("network")])
        except Exception as e:
            QMessageBox.critical(self, tr("msg.error_title"), tr("msg.save_failed", detail=e))

    def _compare_selected(self):
        r = self.scans_tbl.currentRow()
        if r < 0:
            return
        scan = self.inv.get_scan(int(self.scans_tbl.item(r, 0).text()))
        prev = self.inv.previous_scan(scan["network"], scan["id"]) if scan else None
        if not prev:
            QMessageBox.information(self, tr("action.compare"), tr("msg.no_previous_scan"))
            return
        _exec(CompareDialog(self.inv.compare_scans(prev["id"], scan["id"]), self.inv, self))


class FilterDialog(_Dialog):
    """Filtro por tipo de equipo / servicio."""
    TYPES = [("camera", "filter.camera"), ("server", "filter.server"), ("web", "filter.web"),
             ("ssh", "filter.ssh"), ("smb", "filter.smb"), ("rdp", "filter.rdp")]

    def __init__(self, active: List[str], parent=None):
        super().__init__(tr("dlg.filter"), parent, tr("dlg.filter_sub"), 340)
        self.cleared = False
        self.checks = []
        for key, label in self.TYPES:
            cb = QCheckBox(tr(label))
            cb.setChecked(key in active)
            set_help(cb, f"filter_{key}")
            self.checks.append((cb, key))
            self.root.addWidget(cb)
        self.buttons(make_button(tr("btn.clear_filters"), "btnSecondary", "clear_filters", self._clear),
                     make_button(tr("common.cancel"), None, None, self.reject),
                     make_button(tr("btn.apply"), "btnPrimary", "apply_filter", self.accept))

    def _clear(self):
        for cb, _ in self.checks:
            cb.setChecked(False)
        self.cleared = True
        self.accept()

    def selected(self) -> List[str]:
        return [key for cb, key in self.checks if cb.isChecked()]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  PREFERENCIAS Y ACERCA DE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _settings_page(title: str, subtitle: str = None):
    """Página de configuración: título + subtítulo + contenido con scroll. Devuelve (scroll, layout)."""
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(SP["xl"], SP["lg"], SP["xl"], SP["lg"])
    lay.setSpacing(SP["md"])
    t = QLabel(title)
    t.setObjectName("lblTitle")
    lay.addWidget(t)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("lblSubtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(inner)
    return scroll, lay


def _form_grid() -> QGridLayout:
    g = QGridLayout()
    g.setHorizontalSpacing(SP["md"])
    g.setVerticalSpacing(SP["sm"])
    g.setColumnMinimumWidth(0, 140)
    g.setColumnStretch(1, 1)
    return g


def _form_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return lbl


class SettingsDialog(QDialog):
    """Configuración con navegación lateral: General (tema, idioma, datos) y Escaneo
    (puertos, hilos y tiempos). Tema e idioma se aplican al reiniciar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.resize(820, 600)
        self.setMinimumSize(720, 480)
        self._savers = []
        self.restart_needed = False

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(200)
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(SP["sm"], SP["md"], SP["sm"], SP["md"])
        self.nav = QListWidget()
        self.nav.setObjectName("sideNav")
        self.nav.setIconSize(QSize(ICON_SIZE["sm"], ICON_SIZE["sm"]))
        set_help(self.nav, "settings_nav")
        side_lay.addWidget(self.nav)
        self.pages = QStackedWidget()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(side)
        body.addWidget(self.pages, 1)

        hint = QLabel(tr("settings.restart_hint"))
        hint.setObjectName("lblHint")
        foot = QHBoxLayout()
        foot.setContentsMargins(SP["lg"], SP["md"], SP["lg"], SP["md"])
        foot.setSpacing(SP["sm"])
        foot.addWidget(hint, 1)
        foot.addWidget(make_button(tr("common.cancel"), None, "cancel", self.reject))
        btn_save = make_button(tr("btn.save"), "btnPrimary", "save_settings", self.accept)
        btn_save.setDefault(True)
        foot.addWidget(btn_save)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(body, 1)
        root.addWidget(make_divider())
        root.addLayout(foot)

        self._build_general()
        self._build_scan()
        self.nav.setCurrentRow(0)

    def add_page(self, icon_name: str, title: str, page, on_save=None) -> None:
        self.nav.addItem(QListWidgetItem(icon(icon_name), title))
        self.pages.addWidget(page)
        if on_save:
            self._savers.append(on_save)

    # ── General ──────────────────────────────────────────────────────────
    def _build_general(self) -> None:
        page, lay = _settings_page(tr("settings.general"), tr("settings.general_sub"))
        card, card_lay = make_card(tr("settings.appearance"))
        grid = _form_grid()
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItem(icon("moon"), tr("theme.dark"), "dark")
        self.cmb_theme.addItem(icon("monitor"), tr("theme.light"), "light")
        self.cmb_theme.setCurrentIndex(max(0, self.cmb_theme.findData(get_theme_name())))
        set_help(self.cmb_theme, "theme")
        self.cmb_lang = QComboBox()
        for code, name in LANGUAGES.items():
            self.cmb_lang.addItem(icon("language"), name, code)
        self.cmb_lang.setCurrentIndex(max(0, self.cmb_lang.findData(get_lang_code())))
        set_help(self.cmb_lang, "language")
        grid.addWidget(_form_label(tr("settings.theme")), 0, 0)
        grid.addWidget(self.cmb_theme, 0, 1)
        grid.addWidget(_form_label(tr("settings.language")), 1, 0)
        grid.addWidget(self.cmb_lang, 1, 1)
        card_lay.addLayout(grid)
        lay.addWidget(card)

        card2, card2_lay = make_card(tr("settings.data"))
        row = QHBoxLayout()
        row.addWidget(_hint(tr("settings.logs_hint")), 1)
        row.addWidget(make_button(tr("settings.open_logs"), None, "open_data",
                                  lambda: open_with_system(str(nettool_data_dir())), icon_name="open"))
        card2_lay.addLayout(row)
        lay.addWidget(card2)
        lay.addStretch(1)
        self.add_page("settings", tr("settings.general"), page, on_save=self._save_general)

    def _save_general(self) -> bool:
        """True si algo requiere reiniciar."""
        changed = False
        if self.cmb_theme.currentData() != get_theme_name():
            set_theme_name(self.cmb_theme.currentData())
            changed = True
        if self.cmb_lang.currentData() != get_lang_code():
            set_lang_code(self.cmb_lang.currentData())
            changed = True
        return changed

    # ── Escaneo ──────────────────────────────────────────────────────────
    def _build_scan(self) -> None:
        cfg = settings()
        page, lay = _settings_page(tr("settings.scan"), tr("dlg.preferences_sub"))

        btn_reco = make_button(tr("btn.recommended_ports"), "btnSecondary", "recommended_ports",
                               lambda: self.f_ports.setPlainText(DEFAULT_SCAN_PORTS))
        card, clay = make_card(tr("section.scan_ports"), header_widget=btn_reco)
        self.f_ports = QPlainTextEdit(cfg.get("scan_ports") or DEFAULT_SCAN_PORTS)
        self.f_ports.setFixedHeight(76)
        set_help(self.f_ports, "scan_ports")
        self.f_ports.textChanged.connect(self._update_counts)
        clay.addWidget(self.f_ports)
        self.lbl_ports = QLabel()
        self.lbl_ports.setTextFormat(Qt.RichText)
        clay.addWidget(self.lbl_ports)
        lay.addWidget(card)

        card2, lay2 = make_card(tr("section.detail_ports"))
        self.f_detail = QLineEdit(cfg.get("detail_ports"))
        set_help(self.f_detail, "detail_ports")
        self.f_detail.textChanged.connect(self._update_counts)
        lay2.addWidget(self.f_detail)
        self.lbl_detail = QLabel()
        self.lbl_detail.setTextFormat(Qt.RichText)
        lay2.addWidget(self.lbl_detail)
        lay.addWidget(card2)

        card3, lay3 = make_card(tr("section.performance"))
        grid = _form_grid()
        grid.setColumnMinimumWidth(0, 200)
        self.f_workers = QSpinBox(); self.f_workers.setRange(1, 256)
        self.f_workers.setValue(cfg.int_value("scan_workers", 1, 256))
        self.f_timeout = QSpinBox(); self.f_timeout.setRange(50, 5000); self.f_timeout.setSingleStep(50)
        self.f_timeout.setSuffix(" ms"); self.f_timeout.setValue(cfg.int_value("port_timeout_ms", 50, 5000))
        self.f_dworkers = QSpinBox(); self.f_dworkers.setRange(1, 1000)
        self.f_dworkers.setValue(cfg.int_value("detail_workers", 1, 1000))
        self.f_monitor = QSpinBox(); self.f_monitor.setRange(10, 3600); self.f_monitor.setSuffix(" s")
        self.f_monitor.setValue(cfg.int_value("monitor_interval", 10, 3600))
        for r, (label, w, h) in enumerate(((tr("lbl.scan_workers"), self.f_workers, "scan_workers"),
                                           (tr("lbl.port_timeout"), self.f_timeout, "port_timeout"),
                                           (tr("lbl.detail_workers"), self.f_dworkers, "detail_workers"),
                                           (tr("lbl.monitor_interval"), self.f_monitor, "monitor_interval"))):
            grid.addWidget(_form_label(label), r, 0)
            w.setMinimumWidth(140)
            grid.addWidget(w, r, 1, Qt.AlignLeft)
            set_help(w, h)
        lay3.addLayout(grid)
        lay.addWidget(card3)
        lay.addStretch(1)
        self.add_page("radar", tr("settings.scan"), page)
        self._update_counts()

    def _count_label(self, text: str) -> str:
        try:
            n = len(parse_port_spec(text))
            return span(tr("lbl.n_ports", n=n), "ok" if n <= 5000 else "counter")
        except ValueError as e:
            return span(tr("lbl.invalid_ports", token=_html_escape(str(e))), "error")

    def _update_counts(self, *_):
        self.lbl_ports.setText(self._count_label(self.f_ports.toPlainText()))
        self.lbl_detail.setText(self._count_label(self.f_detail.text()))

    def _save_scan(self) -> bool:
        try:
            scan = parse_port_spec(self.f_ports.toPlainText())
            detail = parse_port_spec(self.f_detail.text())
        except ValueError as e:
            self.nav.setCurrentRow(1)
            show_message("warning", self, tr("msg.error_title"), tr("lbl.invalid_ports", token=str(e)))
            return False
        cfg = settings()
        spec = format_port_spec(scan)
        cfg.set("scan_ports", "" if spec == DEFAULT_SCAN_PORTS else spec)
        cfg.set("detail_ports", format_port_spec(detail))
        cfg.set("scan_workers", self.f_workers.value())
        cfg.set("port_timeout_ms", self.f_timeout.value())
        cfg.set("detail_workers", self.f_dworkers.value())
        cfg.set("monitor_interval", self.f_monitor.value())
        cfg.save()
        return True

    def accept(self) -> None:
        if not self._save_scan():
            return
        self.restart_needed = any([saver() for saver in self._savers])
        super().accept()
        if self.restart_needed:
            show_message("info", self.parent(), tr("msg.restart_title"), tr("msg.restart_text", app=APP_NAME))


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about.title", app=APP_NAME))
        self.setMinimumWidth(500)
        app_icon = QApplication.windowIcon()
        logo = QLabel()
        logo.setPixmap(app_icon.pixmap(48, 48) if not app_icon.isNull() else icon_pixmap("app", 48, "accent"))
        name = QLabel(APP_NAME)
        name.setObjectName("lblTitle")
        ver = QLabel(tr("about.version", v=APP_VERSION))
        ver.setObjectName("lblSubtitle")
        head = QHBoxLayout()
        head.setSpacing(SP["md"])
        head.addWidget(logo, 0, Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(name)
        titles.addWidget(ver)
        head.addLayout(titles, 1)

        info = [
            (tr("about.developer"), APP_DEVELOPER),
            (tr("about.license"), "GPL-3.0"),
            ("Qt", _QT_BACKEND),
            ("Python", platform.python_version()),
            (tr("about.system"), f"{platform.system()} {platform.release()} ({platform.machine()})"),
        ]
        self._info_text = "\n".join([f"{APP_NAME} v{APP_VERSION}"] + [f"{k}: {v}" for k, v in info])
        grid = _form_grid()
        grid.setColumnMinimumWidth(0, 100)
        for r, (k, v) in enumerate(info):
            grid.addWidget(_form_label(k), r, 0)
            val = QLabel(v)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(val, r, 1)
        r = len(info)
        grid.addWidget(_form_label("GitHub"), r, 0)
        repo = QLabel(f'<a href="{APP_REPO_URL}" style="color:{THEME["accent"]};">{APP_REPO_URL}</a>')
        repo.setTextFormat(Qt.RichText)
        repo.setOpenExternalLinks(True)
        repo.setToolTip(tr("tip.github"))
        grid.addWidget(repo, r, 1)

        btn_copy = make_button(tr("about.copy"), "btnSecondary", "about_copy", icon_name="copy")
        btn_copy.clicked.connect(lambda: (copy_to_clipboard(self._info_text),
                                          btn_copy.setText(tr("about.copied"))))
        btn_repo = make_button(tr("action.github"), "btnSecondary", "github",
                               lambda: webbrowser.open(APP_REPO_URL), icon_name="external")
        btn_close = make_button(tr("common.close"), "btnPrimary", None, self.accept)
        btn_close.setDefault(True)
        foot = QHBoxLayout()
        foot.setSpacing(SP["sm"])
        foot.addWidget(btn_copy)
        foot.addWidget(btn_repo)
        foot.addStretch(1)
        foot.addWidget(btn_close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP["xl"], SP["xl"], SP["xl"], SP["lg"])
        lay.setSpacing(SP["lg"])
        lay.addLayout(head)
        d = QLabel(tr("about.text"))
        d.setWordWrap(True)
        lay.addWidget(d)
        lay.addLayout(grid)
        lay.addLayout(foot)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  DETALLE DE UN EQUIPO Y RE-ESCANEO DE PUERTOS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class RescanDialog(_Dialog):
    """Qué puertos analizar al re-escanear un equipo (por defecto: Preferencias)."""

    def __init__(self, ip: str, parent=None):
        super().__init__(tr("dlg.rescan"), parent, tr("dlg.rescan_sub", ip=ip), 460)
        self.f_ports = QLineEdit(settings().get("detail_ports"))
        set_help(self.f_ports, "detail_ports")
        self.f_ports.textChanged.connect(self._update)
        self.root.addWidget(self.f_ports)
        quick = QHBoxLayout()
        quick.setSpacing(SP["sm"])
        for label, spec in (("1-1024", "1-1024"), ("1-10000", "1-10000"), (tr("lbl.all_ports"), "1-65535"),
                            (tr("lbl.scan_list"), settings().get("scan_ports") or DEFAULT_SCAN_PORTS)):
            b = QPushButton(label)
            b.setObjectName("btnSecondary")
            b.setStatusTip(tr("tip.quick_ports", spec=spec[:60]))
            b.setToolTip(tr("tip.quick_ports", spec=spec[:60]))
            b.clicked.connect(lambda ch=False, s=spec: self.f_ports.setText(s))
            quick.addWidget(b)
        quick.addStretch(1)
        self.root.addLayout(quick)
        self.lbl = QLabel()
        self.lbl.setTextFormat(Qt.RichText)
        self.root.addWidget(self.lbl)
        self.buttons(make_button(tr("common.cancel"), None, None, self.reject),
                     make_button(tr("btn.start_rescan"), "btnStart", "start_rescan", self._accept))
        self._update()

    def _update(self, *_):
        try:
            n = len(parse_port_spec(self.f_ports.text()))
            self.lbl.setText(span(tr("lbl.n_ports", n=n), "ok" if n <= 10000 else "counter"))
        except ValueError as e:
            self.lbl.setText(span(tr("lbl.invalid_ports", token=_html_escape(str(e))), "error"))

    def _accept(self):
        try:
            self.ports = parse_port_spec(self.f_ports.text())
        except ValueError as e:
            QMessageBox.warning(self, tr("msg.error_title"), tr("lbl.invalid_ports", token=str(e)))
            return
        self.accept()


class PortScanProgressDialog(_Dialog):
    def __init__(self, ip, ports: List[int], parent=None):
        super().__init__(tr("dlg.port_scan", ip=ip), parent, tr("dlg.port_scan_sub", n=len(ports)), 480)
        self.ip = ip
        self.final_data = None
        self.found_ports: List[str] = []
        self.found_lbl = QLabel(tr("lbl.found_ports_none"))
        self.found_lbl.setTextFormat(Qt.RichText)
        self.found_lbl.setWordWrap(True)
        self.root.addWidget(self.found_lbl)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(ports))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(tr("fmt.ports_progress"))
        self.root.addWidget(self.progress_bar)
        self.btn_cancel = make_button(tr("btn.stop"), "btnStop", "stop", self.cancel_scan)
        self.buttons(self.btn_cancel)

        cfg = settings()
        self.thread = SingleIPScannerThread(ip, ports, cfg.int_value("detail_workers", 1, 1000),
                                            cfg.int_value("port_timeout_ms", 50, 5000) / 1000)
        self.thread.progress.connect(self.progress_bar.setValue)
        self.thread.port_found.connect(self.on_port_found)
        self.thread.finished_scan.connect(self.on_finished)
        self.thread.start()

    def on_port_found(self, port):
        self.found_ports.append(str(port))
        text = ", ".join(self.found_ports)
        self.found_lbl.setText(tr("lbl.found_ports", ports=span(text if len(text) < 200 else text[:197] + "…", "ok")))

    def cancel_scan(self):
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText(tr("btn.stopping"))
        self.thread.cancel()

    def on_finished(self, data):
        self.final_data = data
        self.accept()

    def reject(self):
        if self.thread.isRunning():
            self.cancel_scan()
            return
        super().reject()

    def closeEvent(self, event):
        if self.thread.isRunning():
            self.thread.cancel()
            self.thread.wait()
        event.accept()


class IPDetailsWindow(QWidget):
    """Ventana independiente con el análisis de un equipo: puertos, servicios y acciones."""

    def __init__(self, ip_data, parent_tool=None):
        super().__init__(None)
        self.ip_data = ip_data
        self.parent_tool = parent_tool
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowFlag(Qt.Window, True)
        self.setObjectName("page")
        self.setWindowTitle(tr("dlg.details", ip=ip_data["ip"]))
        self.resize(900, 640)
        if parent_tool is not None and parent_tool.window() is not None:
            self.setWindowIcon(parent_tool.window().windowIcon())
        self._web_worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        root.setSpacing(SP["md"])
        d = self.ip_data

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(d["ip"])
        t.setObjectName("lblTitle")
        sub = QLabel(d.get("dev") or "")
        sub.setObjectName("lblSubtitle")
        titles.addWidget(t)
        titles.addWidget(sub)
        head.addLayout(titles)
        head.addStretch(1)
        from networktool.ui.theme import make_badge
        online = d.get("status", STATUS_ONLINE) == STATUS_ONLINE
        head.addWidget(make_badge(tr("status.online") if online else tr("status.offline"), "ok" if online else "error"))
        root.addLayout(head)

        card, lay = make_card(tr("section.general"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(SP["md"])
        grid.setVerticalSpacing(SP["xs"])
        fields = [("Hostname", d.get("host")), ("MAC", d.get("mac")), (tr("col.vendor"), d.get("vendor")),
                  (tr("col.device"), d.get("dev"))]
        for i, (label, value) in enumerate(fields):
            r, c = divmod(i, 2)
            grid.addWidget(field_label(label), r, c * 2, Qt.AlignRight | Qt.AlignVCenter)
            val = QLineEdit(str(value or ""))
            val.setReadOnly(True)
            grid.addWidget(val, r, c * 2 + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)
        root.addWidget(card)

        tabs = QTabWidget()
        tabs.addTab(self._ports_tab(), tr("tab.open_ports"))
        tabs.addTab(self._services_tab(), tr("tab.services"))
        tabs.addTab(self._actions_tab(), tr("tab.quick_actions"))
        root.addWidget(tabs, 1)

        self.buttons_row = QHBoxLayout()
        self.buttons_row.addStretch(1)
        self.buttons_row.addWidget(make_button(tr("common.close"), None, None, self.close))
        self.buttons_row.addWidget(make_button(tr("btn.rescan"), "btnStart", "rescan", self.rescan_ip))
        root.addLayout(self.buttons_row)

    # ── Sesiones integradas ────────────────────────────────────────────
    def _open_session(self, proto: str, port: int) -> None:
        ip = self.ip_data["ip"]
        if self.parent_tool is not None and hasattr(self.parent_tool, "open_session"):
            self.parent_tool.open_session.emit({"protocol": proto, "host": ip, "port": port,
                                                "name": f"{ip} ({proto.upper()})"})
            win = self.parent_tool.window()
            win.raise_()
            win.activateWindow()

    def _open_port(self, port: int) -> None:
        proto = PORT_TO_PROTOCOL.get(port)
        if proto in ("ssh", "telnet", "ftp"):
            self._open_session(proto, port)
        else:
            open_protocol(self.ip_data["ip"], port, self)

    def _ports_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        ports_list = [p for p in str(self.ip_data.get("ports") or "").split(",") if p.strip().isdigit()]
        if not ports_list:
            layout.addWidget(make_empty_state(tr("empty.ports"), "plug"))
            return widget
        services = self.ip_data.get("services", {})
        ip = self.ip_data["ip"]
        table = QTableWidget(len(ports_list), 4)
        for i, (key, tip) in enumerate((("col.port", None), ("col.service", None), ("col.details", None),
                                        ("col.actions", None))):
            table.setHorizontalHeaderItem(i, QTableWidgetItem(tr(key)))
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table.setColumnWidth(3, 132)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        for i, port_str in enumerate(ports_list):
            port = int(port_str)
            info = services.get(port) or services.get(str(port)) or \
                {"name": get_service_name(port), "details": None}
            it = QTableWidgetItem(str(port))
            it.setForeground(QColor(THEME["ip"]))
            table.setItem(i, 0, it)
            table.setItem(i, 1, QTableWidgetItem(info.get("name", "")))
            det = QTableWidgetItem(info.get("details") or "—")
            det.setForeground(QColor(THEME["text_secondary"]))
            table.setItem(i, 2, det)

            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(SP["sm"], 0, SP["sm"], 0)
            cl.setSpacing(SP["xs"])
            btn = QPushButton(tr("btn.open"))
            btn.setObjectName("btnTable")
            set_help(btn, "open_port", port=port)
            btn.clicked.connect(lambda ch=False, p=port: self._open_port(p))
            cl.addWidget(btn)
            more = QPushButton(tr("btn.more_short"))
            more.setObjectName("btnTableMore")
            set_help(more, "port_more")
            menu = QMenu(more)
            menu.addAction(tr("open.http")).triggered.connect(lambda ch=False, p=port: webbrowser.open(f"http://{ip}:{p}"))
            menu.addAction(tr("open.https")).triggered.connect(lambda ch=False, p=port: webbrowser.open(f"https://{ip}:{p}"))
            menu.addAction(tr("open.vlc")).triggered.connect(lambda ch=False, p=port: open_in_vlc(f"rtsp://{ip}:{p}"))
            menu.addSeparator()
            menu.addAction(tr("open.ssh")).triggered.connect(lambda ch=False, p=port: self._open_session("ssh", p))
            menu.addAction(tr("open.sftp")).triggered.connect(lambda ch=False, p=port: self._open_session("sftp", p))
            menu.addAction(tr("open.telnet")).triggered.connect(lambda ch=False, p=port: self._open_session("telnet", p))
            menu.addAction(tr("open.ftp")).triggered.connect(lambda ch=False, p=port: self._open_session("ftp", p))
            menu.addSeparator()
            menu.addAction(tr("open.rdp")).triggered.connect(lambda ch=False, p=port: self._rdp(p))
            menu.addAction(tr("open.smb")).triggered.connect(self._smb)
            more.clicked.connect(lambda ch=False, m=menu, b=more: _exec_menu(m, b.mapToGlobal(b.rect().bottomLeft())))
            cl.addWidget(more)
            table.setCellWidget(i, 3, cell)
        layout.addWidget(table)
        return widget

    def _rdp(self, port=3389):
        if not _launch_rdp(self.ip_data["ip"], port):
            QMessageBox.information(self, "RDP", tr("msg.rdp_missing", target=f"{self.ip_data['ip']}:{port}"))

    def _smb(self):
        ip = self.ip_data["ip"]
        if IS_WINDOWS:
            subprocess.Popen(["explorer", "\\\\" + ip])
        else:
            webbrowser.open(f"smb://{ip}")

    def _services_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        layout.setSpacing(SP["md"])
        card, lay = make_card(tr("section.detected_services"))
        special = self.ip_data.get("special_services", [])
        if special:
            for name, info in special:
                row = QHBoxLayout()
                lbl = QLabel(f"{span(_html_escape(name), 'ok')}&nbsp;&nbsp;{_html_escape(info)}")
                lbl.setTextFormat(Qt.RichText)
                lbl.setWordWrap(True)
                row.addWidget(lbl, 1)
                btn = QPushButton(tr("btn.open"))
                btn.setObjectName("btnTable")
                set_help(btn, "open_service")
                ip = self.ip_data["ip"]
                if "RTSP" in name:
                    btn.clicked.connect(lambda ch=False, url=info: open_in_vlc(url))
                elif "NTP" in name:
                    btn.clicked.connect(lambda ch=False: self._open_ntp(ip))
                else:
                    btn.clicked.connect(lambda ch=False: webbrowser.open(f"http://{ip}"))
                row.addWidget(btn)
                lay.addLayout(row)
        else:
            lay.addWidget(make_empty_state(tr("empty.services"), "server"))
        layout.addWidget(card)

        card2, lay2 = make_card(tr("section.web_info"))
        self.web_lbl = QLabel(tr("status.loading"))
        self.web_lbl.setObjectName("lblHint")
        self.web_lbl.setTextFormat(Qt.RichText)
        self.web_lbl.setWordWrap(True)
        lay2.addWidget(self.web_lbl)
        layout.addWidget(card2)
        layout.addStretch(1)
        # Consulta HTTP en segundo plano (antes congelaba la ventana hasta 1,5 s)
        self._web_worker = FuncWorker(self._fetch_web_info, self.ip_data["ip"])
        self._web_worker.done.connect(self._on_web_info)
        self._web_worker.start()
        return widget

    @staticmethod
    def _fetch_web_info(ip):
        r = _http_session.get(f"http://{ip}", timeout=2)
        m = re.search(r"<title>(.*?)</title>", r.text, re.IGNORECASE | re.DOTALL)
        return r.headers.get("Server", "—"), (m.group(1).strip() if m else "—")

    def _on_web_info(self, ok, result):
        try:
            if ok:
                server, title = result
                self.web_lbl.setText(f'<span style="color:{THEME["text_secondary"]};">{tr("lbl.web_server")}</span>'
                                     f'&nbsp;{span(_html_escape(server), "ip")}<br>'
                                     f'<span style="color:{THEME["text_secondary"]};">{tr("lbl.web_title")}</span>'
                                     f'&nbsp;{span(_html_escape(title[:120]), "text")}')
            else:
                self.web_lbl.setText(tr("lbl.no_web_info"))
        except RuntimeError:
            pass   # ventana ya cerrada

    def _open_ntp(self, ip):
        if IS_WINDOWS:
            open_in_terminal(f"w32tm /stripchart /computer:{ip} /samples:5 /dataonly")
        else:
            open_in_terminal(_make_ntp_linux_cmd(ip))

    def _actions_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        layout.setSpacing(SP["md"])
        ip = self.ip_data["ip"]
        for title, actions in (
            (tr("section.common_actions"), [
                ("action.open_browser", "qa_browser", lambda: webbrowser.open(f"http://{ip}")),
                ("open.ssh", "qa_ssh", lambda: self._open_session("ssh", 22)),
                ("open.sftp", "qa_sftp", lambda: self._open_session("sftp", 22)),
                ("open.telnet", "qa_telnet", lambda: self._open_session("telnet", 23)),
                ("open.rdp", "qa_rdp", lambda: self._rdp()),
                ("open.smb", "qa_smb", self._smb),
            ]),
            (tr("section.diagnostics"), [
                ("qa.ping", "qa_ping", lambda: open_ping(ip)),
                ("qa.trace", "qa_trace", lambda: open_traceroute(ip)),
                ("qa.netstat", "qa_netstat", lambda: open_netstat(ip)),
                ("qa.arp", "qa_arp", lambda: open_arp(ip)),
                ("qa.nmap", "qa_nmap", lambda: open_nmap_quick(ip)),
            ]),
        ):
            card, lay = make_card(title)
            grid = QGridLayout()
            grid.setSpacing(SP["sm"])
            for i, (key, help_key, fn) in enumerate(actions):
                grid.addWidget(make_button(tr(key), None, help_key, fn), i // 3, i % 3)
            lay.addLayout(grid)
            layout.addWidget(card)
        layout.addStretch(1)
        return widget

    def rescan_ip(self):
        dlg = RescanDialog(self.ip_data["ip"], self)
        if _exec(dlg) != QDialog.Accepted:
            return
        progress_dlg = PortScanProgressDialog(self.ip_data["ip"], dlg.ports, self)
        if _exec(progress_dlg) == QDialog.Accepted and progress_dlg.final_data:
            data = progress_dlg.final_data
            if self.parent_tool:
                self.parent_tool.update_row_by_ip(data)
                self.parent_tool.show_ip_details_from_record(data)
            self.close()

    def closeEvent(self, event):
        worker = self._web_worker
        if worker is not None and worker.isRunning():
            try:
                worker.done.disconnect()
            except Exception:
                pass
            # La ventana se destruye al cerrar: el hilo sigue vivo hasta terminar su consulta
            _ORPHAN_WORKERS.append(worker)
            worker.finished.connect(lambda w=worker: _ORPHAN_WORKERS.remove(w) if w in _ORPHAN_WORKERS else None)
        event.accept()


_ORPHAN_WORKERS: List = []
