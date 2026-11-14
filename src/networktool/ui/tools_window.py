"""Ventana de herramientas (ping con gráfico, traceroute, WoL, DNS, subredes)."""

import ipaddress
import re
import socket
import time
from datetime import datetime
from typing import List

from networktool.common import _IPV4_RE, _html_escape, _normalize_mac, _normalize_mask, logger
from networktool.i18n import tr
from networktool.net.adapters import get_ip_info
from networktool.qt_compat import (
    QCheckBox, QColor, QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPainter, QPen, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QThread, QVBoxLayout,
    QWidget, Qt,
)
from networktool.system import _run_command
from networktool.tools import send_magic_packet, split_subnet, subnet_info
from networktool.ui.theme import (
    SP, THEME, field_label, make_button, make_card, make_log_view, mono_font, set_help, span,
)
from networktool.workers import FuncWorker, PingWorker, TraceWorker


class LatencyChart(QWidget):
    """Gráfico de latencia de las últimas N muestras (las pérdidas se marcan en rojo)."""

    def __init__(self, parent=None, capacity: int = 120):
        super().__init__(parent)
        self.capacity = capacity
        self.samples: List[float] = []
        self.setMinimumHeight(180)

    def clear(self):
        self.samples = []
        self.update()

    def add(self, ms: float):
        self.samples.append(ms)
        self.samples = self.samples[-self.capacity:]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 56, 12, 12, 24
        cw, ch = max(1, w - left - right), max(1, h - top - bottom)
        p.fillRect(0, 0, w, h, QColor(THEME["bg_alt"]))
        grid, muted = QColor(THEME["border"]), QColor(THEME["text_secondary"])
        ok = [s for s in self.samples if s >= 0]
        peak = max(ok) * 1.2 if ok else 0
        top_ms = next((v for v in (4, 10, 20, 40, 100, 200, 400, 1000, 2000) if v >= peak), 4000)
        for i in range(5):
            y = top + int(ch * i / 4)
            p.setPen(QPen(grid, 1))
            p.drawLine(left, y, left + cw, y)
            p.setPen(QPen(muted, 1))
            p.drawText(SP["xs"], y + 4, f"{top_ms * (4 - i) / 4:g} ms")
        if not self.samples:
            p.setPen(QPen(muted, 1))
            p.drawText(left + SP["md"], top + ch // 2, tr("chart.no_data"))
            p.end()
            return
        step = cw / max(1, self.capacity - 1)
        prev = None
        for i, s in enumerate(self.samples):
            x = left + int(i * step)
            if s < 0:
                p.setPen(QPen(QColor(THEME["error"]), 2))
                p.drawLine(x, top, x, top + ch)
                prev = None
                continue
            y = top + ch - int(ch * min(s, top_ms) / top_ms)
            p.setPen(QPen(QColor(THEME["ip"]), 2))
            if prev:
                p.drawLine(prev[0], prev[1], x, y)
            else:
                p.drawLine(x, y, x, y)
            prev = (x, y)
        p.setPen(QPen(muted, 1))
        p.drawText(left, h - 6, tr("chart.legend", n=len(self.samples)))
        p.end()


def _table(headers) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    return t


class ToolsWindow(QWidget):
    """Ping con gráfico, traceroute, Wake-on-LAN, DNS y calculadora de subredes."""
    TABS = ["ping", "trace", "wol", "dns", "subnet"]

    def __init__(self, tool=None):
        super().__init__(None)
        self.tool = tool
        self.setObjectName("page")
        self.setWindowTitle(tr("dlg.tools"))
        self.resize(900, 600)
        self._workers: List[QThread] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        lay.setSpacing(SP["md"])
        title = QLabel(tr("dlg.tools"))
        title.setObjectName("lblTitle")
        lay.addWidget(title)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_ping(), tr("tool.ping"))
        self.tabs.addTab(self._build_trace(), tr("tool.trace"))
        self.tabs.addTab(self._build_wol(), tr("tool.wol"))
        self.tabs.addTab(self._build_dns(), tr("tool.dns"))
        self.tabs.addTab(self._build_subnet(), tr("tool.subnet"))

    @staticmethod
    def _page():
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        lay.setSpacing(SP["md"])
        return w, lay

    def open_tab(self, name: str, target: str = "", mac: str = ""):
        self.tabs.setCurrentIndex(self.TABS.index(name) if name in self.TABS else 0)
        if target:
            for w in (self.ping_target, self.trace_target, self.dns_query):
                w.setText(target)
            self.subnet_in.setText(target)
        if mac:
            self.wol_mac.setEditText(mac)
        self.show()
        self.raise_()
        self.activateWindow()

    def _run(self, worker: QThread):
        self._workers.append(worker)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        worker.start()

    # ── Ping ───────────────────────────────────────────────────────────
    def _build_ping(self):
        w, l = self._page()
        row = QHBoxLayout()
        row.setSpacing(SP["sm"])
        self.ping_target = QLineEdit()
        self.ping_target.setPlaceholderText(tr("ph.target"))
        set_help(self.ping_target, "target")
        self.ping_target.returnPressed.connect(self._ping_toggle)
        self.ping_interval = QSpinBox()
        self.ping_interval.setRange(200, 10000)
        self.ping_interval.setValue(1000)
        self.ping_interval.setSuffix(" ms")
        self.ping_interval.setSingleStep(100)
        set_help(self.ping_interval, "ping_interval")
        self.ping_count = QSpinBox()
        self.ping_count.setRange(0, 100000)
        self.ping_count.setValue(0)
        self.ping_count.setSpecialValueText(tr("lbl.continuous"))
        set_help(self.ping_count, "ping_count")
        self.ping_btn = make_button(tr("btn.start_short"), "btnStart", "ping_start", self._ping_toggle)
        row.addWidget(field_label(tr("lbl.target")))
        row.addWidget(self.ping_target, 2)
        row.addWidget(field_label(tr("lbl.interval")))
        row.addWidget(self.ping_interval)
        row.addWidget(field_label(tr("lbl.count")))
        row.addWidget(self.ping_count)
        row.addWidget(self.ping_btn)
        l.addLayout(row)
        self.ping_chart = LatencyChart()
        l.addWidget(self.ping_chart, 1)
        self.ping_stats = QLabel("—")
        self.ping_stats.setTextFormat(Qt.RichText)
        l.addWidget(self.ping_stats)
        self.ping_worker = None
        self._ping_data: List[float] = []
        return w

    def _ping_toggle(self):
        if self.ping_worker and self.ping_worker.isRunning():
            self.ping_worker.stop()
            return
        target = self.ping_target.text().strip()
        if not target:
            return
        self._ping_data = []
        self.ping_chart.clear()
        self.ping_worker = PingWorker(target, self.ping_interval.value(), self.ping_count.value())
        self.ping_worker.sample.connect(self._ping_sample)
        self.ping_worker.finished.connect(self._ping_stopped)
        self.ping_btn.setText(tr("btn.stop"))
        self.ping_btn.setObjectName("btnStop")
        self.ping_btn.style().unpolish(self.ping_btn)
        self.ping_btn.style().polish(self.ping_btn)
        self._run(self.ping_worker)

    def _ping_stopped(self):
        self.ping_btn.setText(tr("btn.start_short"))
        self.ping_btn.setObjectName("btnStart")
        self.ping_btn.style().unpolish(self.ping_btn)
        self.ping_btn.style().polish(self.ping_btn)

    def _ping_sample(self, ms: float):
        self._ping_data.append(ms)
        self.ping_chart.add(ms)
        ok = [x for x in self._ping_data if x >= 0]
        sent, lost = len(self._ping_data), len(self._ping_data) - len(ok)
        jitter = (sum(abs(a - b) for a, b in zip(ok, ok[1:])) / (len(ok) - 1)) if len(ok) > 1 else 0
        sep = f'&nbsp;&nbsp;<span style="color:{THEME["text_muted"]};">│</span>&nbsp;&nbsp;'
        f = lambda k: f'<span style="color:{THEME["text_secondary"]};">{tr(k)}</span>&nbsp;'
        last = tr("trace.no_reply") if ms < 0 else f"{ms:.1f} ms"
        text = (f("ping.last") + span(last, "error" if ms < 0 else "ip") + sep +
                f("ping.sent") + span(sent, "text") + sep +
                f("ping.lost") + span(f"{lost} ({lost * 100 / sent:.0f}%)", "error" if lost else "ok"))
        if ok:
            text += (sep + f("ping.minavgmax") + span(f"{min(ok):.1f} / {sum(ok) / len(ok):.1f} / {max(ok):.1f} ms", "ip")
                     + sep + f("ping.jitter") + span(f"{jitter:.1f} ms", "ip"))
        self.ping_stats.setText(text)

    # ── Traceroute ─────────────────────────────────────────────────────
    def _build_trace(self):
        w, l = self._page()
        row = QHBoxLayout()
        row.setSpacing(SP["sm"])
        self.trace_target = QLineEdit()
        self.trace_target.setPlaceholderText(tr("ph.target"))
        set_help(self.trace_target, "target")
        self.trace_target.returnPressed.connect(self._trace_toggle)
        self.trace_resolve = QCheckBox(tr("lbl.resolve_names"))
        set_help(self.trace_resolve, "trace_resolve")
        self.trace_btn = make_button(tr("btn.start_short"), "btnStart", "trace_start", self._trace_toggle)
        row.addWidget(field_label(tr("lbl.target")))
        row.addWidget(self.trace_target, 2)
        row.addWidget(self.trace_resolve)
        row.addWidget(self.trace_btn)
        l.addLayout(row)
        self.trace_tbl = _table([tr("col.hop"), "IP", tr("col.times")])
        self.trace_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        l.addWidget(self.trace_tbl, 1)
        self.trace_status = QLabel("")
        self.trace_status.setObjectName("lblHint")
        l.addWidget(self.trace_status)
        self.trace_worker = None
        return w

    def _trace_toggle(self):
        if self.trace_worker and self.trace_worker.isRunning():
            self.trace_worker.stop()
            return
        target = self.trace_target.text().strip()
        if not target:
            return
        self.trace_tbl.setRowCount(0)
        self.trace_status.setText(tr("trace.running", target=target))
        self.trace_worker = TraceWorker(target, self.trace_resolve.isChecked())
        self.trace_worker.hop.connect(self._trace_hop)
        self.trace_worker.done.connect(self.trace_status.setText)
        self.trace_worker.finished.connect(lambda: self.trace_btn.setText(tr("btn.start_short")))
        self.trace_btn.setText(tr("btn.stop"))
        self._run(self.trace_worker)

    def _trace_hop(self, n: int, ip: str, times: str):
        r = self.trace_tbl.rowCount()
        self.trace_tbl.insertRow(r)
        for c, v in enumerate((str(n), ip, times)):
            it = QTableWidgetItem(v)
            if ip == "*":
                it.setForeground(QColor(THEME["text_muted"]))
            elif c == 1:
                it.setForeground(QColor(THEME["ip"]))
            self.trace_tbl.setItem(r, c, it)

    # ── Wake-on-LAN ────────────────────────────────────────────────────
    def _build_wol(self):
        w, l = self._page()
        card, cl = make_card(tr("section.wol"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(SP["md"])
        grid.setVerticalSpacing(SP["sm"])
        grid.setColumnStretch(1, 1)
        self.wol_mac = QComboBox()
        self.wol_mac.setEditable(True)
        self.wol_mac.lineEdit().setPlaceholderText(tr("ph.wol_mac"))
        self.wol_mac.currentIndexChanged.connect(self._wol_pick)
        self.wol_bcast = QLineEdit("255.255.255.255")
        self.wol_port = QSpinBox()
        self.wol_port.setRange(1, 65535)
        self.wol_port.setValue(9)
        for r, (label, wid, h) in enumerate((("MAC", self.wol_mac, "wol_mac"), ("Broadcast", self.wol_bcast, "wol_bcast"),
                                             (tr("lbl.udp_port"), self.wol_port, "wol_port"))):
            grid.addWidget(field_label(label), r, 0, Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(wid, r, 1)
            set_help(wid, h)
        cl.addLayout(grid)
        note = QLabel(tr("hint.wol"))
        note.setObjectName("lblHint")
        note.setWordWrap(True)
        cl.addWidget(note)
        row = QHBoxLayout()
        self.wol_status = QLabel("")
        self.wol_status.setTextFormat(Qt.RichText)
        row.addWidget(self.wol_status, 1)
        row.addWidget(make_button(tr("btn.send_magic"), "btnPrimary", "wol_send", self._wol_send))
        cl.addLayout(row)
        l.addWidget(card)
        l.addStretch(1)
        self._wol_fill()
        return w

    def _wol_fill(self):
        self.wol_mac.blockSignals(True)
        self.wol_mac.clear()
        self.wol_mac.addItem("")
        inv = getattr(self.tool, "inventory", None) if self.tool else None
        if inv is not None:
            for d in inv.all_devices():
                mac = _normalize_mac(d.get("mac"))
                if mac:
                    host = d.get("hostname") if d.get("hostname") not in (None, "", "N/A") else ""
                    label = d.get("alias") or host or d.get("vendor") or ""
                    self.wol_mac.addItem(f"{mac}  —  {d.get('ip')}  {label or ''}".rstrip(), mac)
        self.wol_mac.blockSignals(False)
        if self.tool is not None:
            try:
                ip, mask, _, _ = get_ip_info(self.tool.combo.currentText())
                self.wol_bcast.setText(str(ipaddress.IPv4Network(f"{ip}/{_normalize_mask(mask)}",
                                                                 strict=False).broadcast_address))
            except Exception:
                pass

    def _wol_pick(self, idx):
        mac = self.wol_mac.itemData(idx)
        if mac:
            self.wol_mac.setEditText(mac)

    def _wol_send(self):
        mac = self.wol_mac.currentText().split()[0] if self.wol_mac.currentText().strip() else ""
        try:
            ipaddress.IPv4Address(self.wol_bcast.text().strip())
            send_magic_packet(mac, self.wol_bcast.text().strip(), self.wol_port.value())
        except Exception as e:
            self.wol_status.setText(span(tr("log.error", detail=_html_escape(e)), "error"))
            return
        self.wol_status.setText(span(tr("wol.sent", mac=_normalize_mac(mac),
                                        target=f"{self.wol_bcast.text().strip()}:{self.wol_port.value()}",
                                        time=datetime.now().strftime(tr("fmt.time"))), "ok"))
        logger.info(f"Wake-on-LAN enviado a {mac}")

    # ── DNS ────────────────────────────────────────────────────────────
    def _build_dns(self):
        w, l = self._page()
        row = QHBoxLayout()
        row.setSpacing(SP["sm"])
        self.dns_query = QLineEdit()
        self.dns_query.setPlaceholderText(tr("ph.dns_query"))
        set_help(self.dns_query, "dns_query")
        self.dns_server = QLineEdit()
        self.dns_server.setPlaceholderText(tr("ph.dns_server"))
        set_help(self.dns_server, "dns_server")
        self.dns_query.returnPressed.connect(self._dns_run)
        row.addWidget(self.dns_query, 2)
        row.addWidget(self.dns_server, 1)
        row.addWidget(make_button(tr("btn.lookup"), "btnPrimary", "dns_lookup", self._dns_run))
        l.addLayout(row)
        self.dns_out = make_log_view()
        l.addWidget(self.dns_out, 1)
        return w

    def _dns_run(self):
        q, server = self.dns_query.text().strip(), self.dns_server.text().strip()
        if not q:
            return
        self.dns_out.setPlainText(tr("dns.querying", q=q))

        def lookup():
            lines = []
            is_ip = bool(re.fullmatch(_IPV4_RE, q))
            t0 = time.time()
            if server:
                out, err, _ = _run_command(["nslookup", q, server], timeout=10)
                lines.append(f"nslookup {q} {server}\n{(out or err).strip()}")
            elif is_ip:
                try:
                    name, aliases, _ = socket.gethostbyaddr(q)
                    lines.append(tr("dns.reverse", q=q, name=name) +
                                 (f"\nAlias: {', '.join(aliases)}" if aliases else ""))
                except Exception as e:
                    lines.append(tr("dns.reverse_none", q=q, detail=e))
            else:
                infos = socket.getaddrinfo(q, None)
                v4 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET})
                v6 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET6})
                lines.append(f"{q}\n  IPv4: {', '.join(v4) or '-'}\n  IPv6: {', '.join(v6) or '-'}")
            lines.append("\n" + tr("dns.time", ms=f"{(time.time() - t0) * 1000:.0f}"))
            return "\n".join(lines)
        worker = FuncWorker(lookup)
        worker.done.connect(lambda ok, res: self.dns_out.setPlainText(res if ok else tr("log.error", detail=res)))
        self._run(worker)

    # ── Subredes ───────────────────────────────────────────────────────
    def _build_subnet(self):
        w, l = self._page()
        row = QHBoxLayout()
        row.setSpacing(SP["sm"])
        self.subnet_in = QLineEdit()
        self.subnet_in.setPlaceholderText(tr("ph.subnet"))
        set_help(self.subnet_in, "subnet_in")
        self.subnet_mask = QLineEdit()
        self.subnet_mask.setPlaceholderText(tr("ph.subnet_mask"))
        set_help(self.subnet_mask, "mask")
        self.subnet_in.returnPressed.connect(self._subnet_calc)
        row.addWidget(self.subnet_in, 2)
        row.addWidget(self.subnet_mask, 1)
        row.addWidget(make_button(tr("btn.calculate"), "btnPrimary", "subnet_calc", self._subnet_calc))
        l.addLayout(row)
        self.subnet_tbl = _table([tr("col.field"), tr("col.value")])
        l.addWidget(self.subnet_tbl, 2)
        row2 = QHBoxLayout()
        row2.setSpacing(SP["sm"])
        self.split_prefix = QSpinBox()
        self.split_prefix.setRange(1, 32)
        self.split_prefix.setValue(26)
        self.split_prefix.setPrefix("/")
        set_help(self.split_prefix, "split_prefix")
        row2.addWidget(field_label(tr("lbl.split_into")))
        row2.addWidget(self.split_prefix)
        row2.addWidget(make_button(tr("btn.split"), None, "subnet_split", self._subnet_split))
        row2.addStretch(1)
        l.addLayout(row2)
        self.split_out = make_log_view()
        self.split_out.setFont(mono_font(12))
        l.addWidget(self.split_out, 1)
        return w

    def _subnet_calc(self):
        try:
            info = subnet_info(self.subnet_in.text(), self.subnet_mask.text())
        except Exception as e:
            self.subnet_tbl.setRowCount(1)
            self.subnet_tbl.setItem(0, 0, QTableWidgetItem(tr("msg.error_title")))
            self.subnet_tbl.setItem(0, 1, QTableWidgetItem(str(e)))
            return
        self.subnet_tbl.setRowCount(len(info))
        for r, (k, v) in enumerate(info):
            key = QTableWidgetItem(k)
            key.setForeground(QColor(THEME["text_secondary"]))
            val = QTableWidgetItem(v)
            val.setForeground(QColor(THEME["ip"]))
            self.subnet_tbl.setItem(r, 0, key)
            self.subnet_tbl.setItem(r, 1, val)
        prefix = int(info[1][1].split("/")[1])
        self.split_prefix.setMinimum(prefix)
        if self.split_prefix.value() <= prefix:
            self.split_prefix.setValue(min(32, prefix + 1))

    def _subnet_split(self):
        try:
            text = self.subnet_in.text().strip()
            if "/" not in text:
                text = f"{text}/{_normalize_mask(self.subnet_mask.text() or '24')}"
            subs = split_subnet(str(ipaddress.IPv4Interface(text).network), self.split_prefix.value())
            self.split_out.setPlainText(tr("subnet.n_subnets", n=len(subs)) + "\n" + "\n".join(subs))
        except Exception as e:
            self.split_out.setPlainText(tr("log.error", detail=e))

    def closeEvent(self, event):
        for wk in list(self._workers):
            try:
                if hasattr(wk, "stop"):
                    wk.stop()
                wk.wait(1500)
            except Exception:
                pass
        event.accept()
