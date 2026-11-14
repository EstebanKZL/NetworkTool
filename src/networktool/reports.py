"""Informes: comparación de escaneos, Excel y PDF."""

from typing import Dict, List, Optional, Tuple

from networktool.common import APP_DEVELOPER, APP_VERSION, _html_escape, _now_str, logger
from networktool.data.inventory import Inventory
from networktool.i18n import tr
from networktool.qt_compat import QPageLayout, QPageSize, QPdfWriter, QTextDocument

def comparison_html(cmp: Dict, inventory: Optional["Inventory"] = None, colors: Optional[Dict] = None) -> str:
    """colors: claves ok / error / counter / muted. Por defecto, las del tema activo."""
    if colors is None:
        from networktool.ui.theme import THEME
        colors = {"ok": THEME["ok"], "error": THEME["error"], "counter": THEME["counter"], "muted": THEME["text_secondary"]}
    old_s, new_s = cmp.get("old_scan") or {}, cmp.get("new_scan") or {}
    def name(h):
        alias = inventory.alias_for_key(h["key"]) if inventory else ""
        extra = f" · <b>{_html_escape(alias)}</b>" if alias else ""
        vendor = h.get("vendor") or ""
        return (f"{_html_escape(h['ip'])} &nbsp; <span style='color:{colors['muted']}'>{_html_escape(h.get('mac', ''))}"
                f"{' · ' + _html_escape(vendor) if vendor else ''}</span>{extra}")
    parts = [tr("cmp.header", old=_html_escape(old_s.get('started', '?')), old_n=old_s.get('total', 0),
                new=_html_escape(new_s.get('started', '?')), new_n=new_s.get('total', 0),
                net=_html_escape(new_s.get('network', '')))]
    for title, color, items, fmt in (
        (tr("cmp.new"), colors["ok"], cmp["new"], name),
        (tr("cmp.missing"), colors["error"], cmp["missing"], name),
        (tr("cmp.ip_changed"), colors["counter"], cmp["ip_changed"],
         lambda pair: f"{_html_escape(pair[0]['ip'])} → {name(pair[1])}"),
    ):
        parts.append(f"<h3 style='color:{color}'>{title}: {len(items)}</h3>")
        parts.append("<ul>" + "".join(f"<li>{fmt(i)}</li>" for i in items) + "</ul>" if items else "<p>—</p>")
    return "".join(parts)

def device_history_text(inventory: "Inventory", device: Dict) -> str:
    hist = inventory.ip_history(device["key"])
    lines = [f"{device.get('alias') or device.get('ip')}",
             f"MAC: {device.get('mac')}   {tr('col.vendor')}: {device.get('vendor') or '-'}",
             f"{tr('col.type')}: {device.get('dev') or '-'}   {tr('col.ports')}: {device.get('ports') or '-'}",
             f"{tr('col.first_seen')}: {device.get('first_seen')}",
             f"{tr('col.last_seen')}: {device.get('last_seen')}",
             tr("hist.scans", n=inventory.scan_count_for(device['key'])), "",
             tr("hist.ips")]
    lines += [f"  {h['ip']:<16} {h['first_seen']}  →  {h['last_seen']}" for h in hist] or ["  —"]
    if device.get("notes"):
        lines += ["", tr("col.notes") + ":", device["notes"]]
    return "\n".join(lines)

# -----------------------------
# INFORMES: EXCEL Y PDF
# -----------------------------
def report_cols() -> List[str]:
    return ["IP", tr("col.alias"), "Hostname", "MAC", tr("col.vendor"), tr("col.ports"), tr("col.device"),
            tr("col.status"), tr("col.notes")]

def export_excel(path: str, summary: List[Tuple[str, str]], rows: List[List], cmp: Optional[Dict],
                 inventory_rows: List[Dict]) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise RuntimeError(tr("rep.no_openpyxl"))
    wb = Workbook()
    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="007ACC")

    def table(ws, header, data):
        ws.append(header)
        for c in range(1, len(header) + 1):
            cell = ws.cell(row=1, column=c); cell.font = head_font; cell.fill = head_fill
            cell.alignment = Alignment(vertical="center")
        for row in data:
            ws.append(["" if v is None else v for v in row])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for c in range(1, len(header) + 1):
            width = max(len(str(ws.cell(row=r, column=c).value or "")) for r in range(1, ws.max_row + 1))
            ws.column_dimensions[get_column_letter(c)].width = min(max(10, width + 2), 60)

    ws = wb.active; ws.title = tr("rep.sheet_devices")
    table(ws, report_cols(), rows)

    ws2 = wb.create_sheet(tr("rep.sheet_summary"))
    ws2.column_dimensions["A"].width = 28; ws2.column_dimensions["B"].width = 60
    for k, v in summary:
        ws2.append([k, v]); ws2.cell(row=ws2.max_row, column=1).font = Font(bold=True)
    if cmp:
        ws2.append([]); ws2.append([tr("rep.comparison"), (cmp.get("old_scan") or {}).get("started", "")])
        ws2.cell(row=ws2.max_row, column=1).font = Font(bold=True, color="007ACC")
        for title, items in ((tr("cmp.new"), cmp["new"]), (tr("cmp.missing"), cmp["missing"])):
            ws2.append([f"{title} ({len(items)})", ", ".join(h["ip"] for h in items)])
        ws2.append([f"{tr('cmp.ip_changed')} ({len(cmp['ip_changed'])})",
                    ", ".join(f"{a['ip']}→{b['ip']}" for a, b in cmp["ip_changed"])])

    ws3 = wb.create_sheet(tr("btn.inventory"))
    table(ws3, [tr("col.alias"), "IP", "MAC", tr("col.vendor"), tr("col.type"), "Hostname", tr("col.first_seen"),
                tr("col.last_seen"), tr("col.notes")],
          [[d.get("alias"), d.get("ip"), d.get("mac"), d.get("vendor"), d.get("dev"), d.get("hostname"),
            d.get("first_seen"), d.get("last_seen"), d.get("notes")] for d in inventory_rows])
    wb.save(path)

def report_html(summary: List[Tuple[str, str]], rows: List[List], cmp: Optional[Dict], inventory=None) -> str:
    css = ("body{font-family:Segoe UI,Arial;font-size:9pt;color:#222} h1{color:#007acc;font-size:16pt}"
           "table{border-collapse:collapse;width:100%} th{background:#007acc;color:#fff;padding:4px;text-align:left}"
           "td{border-bottom:1px solid #ccc;padding:3px} .k{font-weight:bold;padding-right:12px}")
    html = [f"<html><head><style>{css}</style></head><body><h1>{tr('rep.title')} · NetworkTool v{APP_VERSION}</h1><table>"]
    html += [f"<tr><td class='k'>{_html_escape(k)}</td><td>{_html_escape(v)}</td></tr>" for k, v in summary]
    html.append("</table><br><table><tr>" + "".join(f"<th>{c}</th>" for c in report_cols()) + "</tr>")
    for row in rows:
        html.append("<tr>" + "".join(f"<td>{_html_escape(v)}</td>" for v in row) + "</tr>")
    html.append("</table>")
    if cmp:
        print_colors = {"ok": "#1b6b43", "error": "#a52e24", "counter": "#7d5200", "muted": "#666666"}
        html.append(f"<h2>{tr('rep.comparison')}</h2>" + comparison_html(cmp, inventory, print_colors))
    html.append(f"<p style='color:#888'>{tr('rep.generated', time=_now_str())} · {APP_DEVELOPER}</p></body></html>")
    return "".join(html)

def export_pdf(path: str, html: str) -> None:
    writer = QPdfWriter(path)
    try:
        writer.setPageSize(QPageSize(getattr(QPageSize, "A4", None) or QPageSize.PageSizeId.A4))
        writer.setPageOrientation(getattr(QPageLayout, "Landscape", None) or QPageLayout.Orientation.Landscape)
    except Exception as e:
        logger.debug(f"PDF: tamaño de página por defecto ({e})")
    writer.setResolution(120)
    doc = QTextDocument()
    doc.setHtml(html)
    printer = getattr(doc, "print_", None) or getattr(doc, "print")
    printer(writer)
