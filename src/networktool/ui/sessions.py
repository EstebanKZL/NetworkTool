"""Panel lateral de sesiones guardadas (estilo MobaXterm) y sus diálogos.

SSH / Telnet abren una terminal en una pestaña; SFTP / FTP un explorador de archivos;
RDP / VNC / Web se abren con el cliente del sistema.
"""

import os
from typing import Dict, Optional

from networktool.data.sessions import (
    LOCAL_PROTOCOLS, PROTOCOL_LABELS, PROTOCOLS, SessionStore, clean_session, local_session,
)
from networktool.net.wsl import list_distros, local_shells
from networktool.data.vault import CredentialVault, vault
from networktool.i18n import tr
from networktool.qt_compat import (
    QAbstractItemView, QCheckBox, QColor, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget, Qt, Signal, _exec, _exec_menu,
)
from networktool.ui.theme import (
    SP, THEME, add_search_icon, attach_menu, field_label, icon, make_badge, make_button, make_card,
    make_empty_state, protocol_icon,
    make_section_label, set_help,
)

ENCODINGS = ["utf-8", "latin-1", "cp1252", "cp437", "ascii"]
_ROLE = Qt.UserRole


class SessionDialog(QDialog):
    """Alta / edición de una sesión."""

    def __init__(self, session: Optional[Dict], folders, parent=None):
        super().__init__(parent)
        self.session = dict(session or {})
        self.setWindowTitle(tr("dlg.session_edit") if session and session.get("id") else tr("dlg.session_new"))
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        root.setSpacing(SP["md"])
        title = QLabel(self.windowTitle())
        title.setObjectName("lblTitle")
        root.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(SP["md"])
        grid.setVerticalSpacing(SP["sm"])
        r = 0

        def row(label_key, widget, help_key):
            nonlocal r
            lbl = field_label(tr(label_key))
            grid.addWidget(lbl, r, 0, Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(widget, r, 1)
            set_help(widget, help_key)
            r += 1
            return lbl

        self.f_proto = QComboBox()
        for key in PROTOCOLS:
            self.f_proto.addItem(protocol_icon(key), PROTOCOL_LABELS[key], key)
        row("lbl.protocol", self.f_proto, "session_protocol")

        self.f_name = QLineEdit()
        self.f_name.setPlaceholderText(tr("ph.session_name"))
        row("lbl.name", self.f_name, "session_name")

        self.f_distro = QComboBox()
        self.f_distro.setEditable(True)
        self.f_distro.lineEdit().setPlaceholderText(tr("ph.wsl_default"))
        for d in list_distros():
            self.f_distro.addItem(d["name"] + (f"  ({tr('lbl.default')})" if d["default"] else ""), d["name"])
        self.lbl_distro = row("lbl.distro", self.f_distro, "session_distro")
        self.f_shell = QComboBox()
        for sh in local_shells():
            self.f_shell.addItem(sh["name"], sh["key"])
        self.lbl_shell = row("lbl.shell", self.f_shell, "session_shell")

        self.f_folder = QComboBox()
        self.f_folder.setEditable(True)
        self.f_folder.addItem("")
        self.f_folder.addItems(list(folders))
        self.f_folder.lineEdit().setPlaceholderText(tr("ph.session_folder"))
        row("lbl.folder", self.f_folder, "session_folder")

        host_row = QHBoxLayout()
        host_row.setSpacing(SP["sm"])
        self.f_host = QLineEdit()
        self.f_host.setPlaceholderText(tr("ph.host"))
        self.f_port = QSpinBox()
        self.f_port.setRange(1, 65535)
        self.f_port.setMinimumWidth(96)
        set_help(self.f_port, "session_port")
        host_row.addWidget(self.f_host, 1)
        host_row.addWidget(field_label(tr("lbl.port")))
        host_row.addWidget(self.f_port)
        host_w = QWidget()
        host_w.setLayout(host_row)
        host_row.setContentsMargins(0, 0, 0, 0)
        self.host_w = host_w
        self.lbl_host = row("lbl.host", host_w, "session_host")

        self.f_user = QLineEdit()
        self.f_user.setPlaceholderText(tr("ph.username"))
        self.lbl_user = row("lbl.username", self.f_user, "session_user")

        cred_row = QHBoxLayout()
        cred_row.setContentsMargins(0, 0, 0, 0)
        cred_row.setSpacing(SP["sm"])
        self.f_cred = QComboBox()
        self.f_cred.currentIndexChanged.connect(self._on_cred_picked)
        b_creds = make_button(tr("btn.manage_credentials"), "btnSecondary", "credentials", self._manage_credentials)
        cred_row.addWidget(self.f_cred, 1)
        cred_row.addWidget(b_creds)
        self.cred_w = QWidget()
        self.cred_w.setLayout(cred_row)
        self.lbl_cred = row("lbl.saved_credential", self.cred_w, "session_credential")

        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(SP["sm"])
        self.f_key = QLineEdit()
        self.f_key.setPlaceholderText(tr("ph.key_file"))
        b_key = make_button(tr("btn.browse"), None, "browse_key", self._browse_key)
        key_row.addWidget(self.f_key, 1)
        key_row.addWidget(b_key)
        self.key_w = QWidget()
        self.key_w.setLayout(key_row)
        self.lbl_key = row("lbl.key_file", self.key_w, "session_key")

        self.f_path = QLineEdit()
        self.f_path.setPlaceholderText(tr("ph.remote_path"))
        self.lbl_path = row("lbl.remote_path", self.f_path, "session_path")

        self.f_passive = QCheckBox(tr("lbl.ftp_passive"))
        set_help(self.f_passive, "session_passive")
        grid.addWidget(self.f_passive, r, 1)
        r += 1

        self.f_enc = QComboBox()
        self.f_enc.setEditable(True)
        self.f_enc.addItems(ENCODINGS)
        self.lbl_enc = row("lbl.encoding", self.f_enc, "session_encoding")

        self.f_notes = QPlainTextEdit()
        self.f_notes.setFixedHeight(64)
        row("lbl.notes", self.f_notes, "session_notes")
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

        hint = QLabel(tr("hint.passwords_vault"))
        hint.setObjectName("lblHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(make_button(tr("common.cancel"), None, None, self.reject))
        btns.addWidget(make_button(tr("btn.save"), "btnPrimary", "save_session", self._accept))
        root.addLayout(btns)

        s = clean_session(self.session) if self.session else clean_session({"protocol": "ssh"})
        idx = self.f_proto.findData(s["protocol"])
        self.f_proto.setCurrentIndex(max(0, idx))
        self.f_name.setText(self.session.get("name", ""))
        self.f_folder.setCurrentText(s["folder"])
        self.f_host.setText(s["host"])
        self.f_port.setValue(s["port"])
        self.f_user.setText(s["username"])
        self._fill_credentials(s.get("credential_id", ""))
        if s.get("distro"):
            i = self.f_distro.findData(s["distro"])
            (self.f_distro.setCurrentIndex(i) if i >= 0 else self.f_distro.setEditText(s["distro"]))
        else:
            self.f_distro.setCurrentIndex(-1)
        i = self.f_shell.findData(s.get("shell") or "powershell")
        self.f_shell.setCurrentIndex(max(0, i))
        self.f_key.setText(s["key_file"])
        self.f_path.setText(s["remote_path"])
        self.f_passive.setChecked(s["ftp_passive"])
        self.f_enc.setCurrentText(s["encoding"])
        self.f_notes.setPlainText(s["notes"])
        self._last_proto = s["protocol"]
        self.f_proto.currentIndexChanged.connect(self._on_proto)
        self._on_proto()

    def _on_proto(self, *_):
        proto = self.f_proto.currentData()
        if self.f_port.value() == PROTOCOLS.get(self._last_proto, {}).get("port") and PROTOCOLS[proto]["port"]:
            self.f_port.setValue(PROTOCOLS[proto]["port"])
        self._last_proto = proto
        local = proto in LOCAL_PROTOCOLS
        for w in (self.lbl_host, self.host_w):
            w.setVisible(not local)
        for w in (self.lbl_distro, self.f_distro):
            w.setVisible(proto == "wsl")
        for w in (self.lbl_shell, self.f_shell):
            w.setVisible(proto == "shell")
        ssh_like = proto in ("ssh", "sftp")
        for w in (self.lbl_key, self.key_w):
            w.setVisible(ssh_like)
        for w in (self.lbl_path, self.f_path):
            w.setVisible(proto in ("sftp", "ftp"))
        self.f_passive.setVisible(proto == "ftp")
        for w in (self.lbl_enc, self.f_enc):
            w.setVisible(proto in ("ssh", "telnet", "ftp"))
        for w in (self.lbl_user, self.f_user, self.lbl_cred, self.cred_w):
            w.setVisible(proto not in ("http", "https", "vnc") and not local)
        for w in (self.lbl_enc, self.f_enc):
            w.setVisible(proto in ("ssh", "telnet", "ftp"))

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("lbl.key_file"), os.path.expanduser("~/.ssh"))
        if path:
            self.f_key.setText(path)

    def _accept(self):
        proto = self.f_proto.currentData()
        host = self.f_host.text().strip()
        if proto in LOCAL_PROTOCOLS:
            distro = (self.f_distro.currentData() if self.f_distro.currentIndex() >= 0
                      and self.f_distro.currentText() == self.f_distro.itemText(self.f_distro.currentIndex())
                      else self.f_distro.currentText().strip())
            shell = self.f_shell.currentData() or "powershell"
            default_name = f"WSL {distro}".strip() if proto == "wsl" else self.f_shell.currentText()
            self.session.update({"protocol": proto, "name": self.f_name.text().strip() or default_name,
                                 "folder": self.f_folder.currentText().strip(), "host": "", "distro": distro or "",
                                 "shell": shell, "notes": self.f_notes.toPlainText()})
            self.accept()
            return
        if not host:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.host_required"))
            return
        self.session.update({
            "protocol": self.f_proto.currentData(), "name": self.f_name.text().strip() or host,
            "folder": self.f_folder.currentText().strip(), "host": host, "port": self.f_port.value(),
            "username": self.f_user.text().strip(), "key_file": self.f_key.text().strip(),
            "remote_path": self.f_path.text().strip(), "ftp_passive": self.f_passive.isChecked(),
            "encoding": self.f_enc.currentText().strip() or "utf-8", "notes": self.f_notes.toPlainText(),
            "credential_id": self.f_cred.currentData() or "",
        })
        self.accept()

    def _fill_credentials(self, selected: str = "") -> None:
        v = vault()
        self.f_cred.blockSignals(True)
        self.f_cred.clear()
        self.f_cred.addItem(tr("lbl.cred_auto"), "")
        for c in sorted(v.items, key=lambda c: (c.get("name") or "").lower()):
            self.f_cred.addItem(v.label(c), c["id"])
        idx = self.f_cred.findData(selected) if selected else 0
        self.f_cred.setCurrentIndex(max(0, idx))
        self.f_cred.blockSignals(False)

    def _on_cred_picked(self, *_):
        c = vault().get(self.f_cred.currentData() or "")
        if c is not None:
            self.f_user.setText(c.get("username", ""))

    def _manage_credentials(self):
        current = self.f_cred.currentData() or ""
        _exec(CredentialsManagerDialog(vault(), self))
        self._fill_credentials(current)


class CredentialsDialog(QDialog):
    """Usuario y contraseña al conectar. Ofrece las credenciales guardadas (autocompleta) y
    puede guardar la nueva en la bóveda cifrada."""

    def __init__(self, session: Dict, store: CredentialVault, parent=None, error: str = ""):
        super().__init__(parent)
        self.vault = store
        self.setWindowTitle(tr("dlg.credentials"))
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        root.setSpacing(SP["md"])
        title = QLabel(session["name"])
        title.setObjectName("lblTitle")
        root.addWidget(title)
        sub = QLabel(f"{PROTOCOL_LABELS[session['protocol']]}  ·  {session['host']}:{session['port']}")
        sub.setObjectName("lblSubtitle")
        root.addWidget(sub)
        if error:
            err = make_badge(error, "error")
            root.addWidget(err)

        grid = QGridLayout()
        grid.setHorizontalSpacing(SP["md"])
        grid.setVerticalSpacing(SP["sm"])
        self.f_saved = QComboBox()
        set_help(self.f_saved, "pick_credential")
        self.f_saved.addItem(tr("lbl.cred_new"), "")
        host_ids = [c["id"] for c in store.for_host(session["host"], session["port"])]
        ordered = [store.get(i) for i in host_ids] + [c for c in store.items if c["id"] not in host_ids]
        for c in ordered:
            self.f_saved.addItem(store.label(c), c["id"])
        self.f_user = QLineEdit(session.get("username", ""))
        self.f_user.setPlaceholderText(tr("ph.username"))
        set_help(self.f_user, "session_user")
        self.f_pass = QLineEdit()
        self.f_pass.setEchoMode(QLineEdit.Password)
        uses_key = bool(session.get("key_file"))
        self.f_pass.setPlaceholderText(tr("ph.passphrase") if uses_key else tr("ph.password"))
        set_help(self.f_pass, "session_passphrase" if uses_key else "session_password")
        self.btn_show = QPushButton(tr("btn.show"))
        self.btn_show.setCheckable(True)
        set_help(self.btn_show, "show_password")
        self.btn_show.toggled.connect(lambda on: self.f_pass.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        pass_row = QHBoxLayout()
        pass_row.setContentsMargins(0, 0, 0, 0)
        pass_row.setSpacing(SP["sm"])
        pass_row.addWidget(self.f_pass, 1)
        pass_row.addWidget(self.btn_show)
        rows = []
        if store.items:
            rows.append((tr("lbl.saved_credential"), self.f_saved))
        rows += [(tr("lbl.username"), self.f_user),
                 (tr("lbl.passphrase") if uses_key else tr("lbl.password"), pass_row)]
        for r, (label, w) in enumerate(rows):
            grid.addWidget(field_label(label), r, 0, Qt.AlignRight | Qt.AlignVCenter)
            if isinstance(w, QHBoxLayout):
                grid.addLayout(w, r, 1)
            else:
                grid.addWidget(w, r, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

        self.f_save = QCheckBox(tr("lbl.save_in_vault"))
        set_help(self.f_save, "save_in_vault")
        self.f_save.setChecked(store.policy != "never")
        self.f_save.setVisible(store.policy == "ask")
        root.addWidget(self.f_save)
        hint = QLabel(tr("hint.vault_policy_" + store.policy))
        hint.setObjectName("lblHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(make_button(tr("common.cancel"), None, None, self.reject))
        btn_ok = make_button(tr("btn.connect"), "btnConnect", "connect_session", self.accept)
        btn_ok.setDefault(True)
        btns.addWidget(btn_ok)
        root.addLayout(btns)
        self.f_saved.currentIndexChanged.connect(self._on_saved)
        if session.get("credential_id"):
            idx = self.f_saved.findData(session["credential_id"])
            if idx > 0:
                self.f_saved.setCurrentIndex(idx)
        (self.f_pass if self.f_user.text() else self.f_user).setFocus()

    def _on_saved(self, *_):
        c = self.vault.get(self.f_saved.currentData() or "")
        if c is None:
            self.f_pass.clear()
            return
        self.f_user.setText(c.get("username", ""))
        self.f_pass.setText(self.vault.password(c))

    def username(self) -> str:
        return self.f_user.text().strip()

    def password(self) -> str:
        return self.f_pass.text()

    def chosen_id(self) -> str:
        c = self.vault.get(self.f_saved.currentData() or "")
        # si el usuario cambió los datos de la credencial elegida, se trata como nueva
        if c and c.get("username") == self.username() and self.vault.password(c) == self.password():
            return c["id"]
        return ""

    def save_requested(self) -> bool:
        return self.vault.policy == "always" or (self.vault.policy == "ask" and self.f_save.isChecked())


class CredentialEditDialog(QDialog):
    def __init__(self, cred: Optional[Dict], store: CredentialVault, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg.credential_edit") if cred else tr("dlg.credential_new"))
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        root.setSpacing(SP["md"])
        title = QLabel(self.windowTitle())
        title.setObjectName("lblTitle")
        root.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(SP["md"])
        grid.setVerticalSpacing(SP["sm"])
        self.f_name = QLineEdit((cred or {}).get("name", ""))
        self.f_name.setPlaceholderText(tr("ph.credential_name"))
        set_help(self.f_name, "credential_name")
        self.f_user = QLineEdit((cred or {}).get("username", ""))
        self.f_user.setPlaceholderText(tr("ph.username"))
        set_help(self.f_user, "session_user")
        self.f_pass = QLineEdit()
        self.f_pass.setEchoMode(QLineEdit.Password)
        self.f_pass.setPlaceholderText(tr("ph.keep_password") if cred else tr("ph.password_vault"))
        set_help(self.f_pass, "credential_password")
        for r, (label, w) in enumerate(((tr("lbl.name"), self.f_name), (tr("lbl.username"), self.f_user),
                                        (tr("lbl.password"), self.f_pass))):
            grid.addWidget(field_label(label), r, 0, Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(w, r, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(make_button(tr("common.cancel"), None, None, self.reject))
        btns.addWidget(make_button(tr("btn.save"), "btnPrimary", "save_credential", self._accept))
        root.addLayout(btns)
        self.cred, self.store = cred, store

    def _accept(self):
        if not self.f_user.text().strip():
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.user_required"))
            return
        keep = bool(self.cred) and not self.f_pass.text()
        self.store.upsert(self.f_name.text(), self.f_user.text(), self.f_pass.text(),
                          cid=(self.cred or {}).get("id"), keep_password=keep)
        self.accept()


class CredentialsManagerDialog(QDialog):
    """Credenciales guardadas (como el "Credentials" de MobaXterm) y cuándo guardar contraseñas."""
    COLS = ["col.name", "col.username", "col.password", "col.hosts"]

    def __init__(self, store: CredentialVault, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(tr("dlg.credentials_manager"))
        self.setMinimumSize(720, 480)
        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        root.setSpacing(SP["md"])
        title = QLabel(self.windowTitle())
        title.setObjectName("lblTitle")
        root.addWidget(title)
        sub = QLabel(tr("dlg.credentials_manager_sub"))
        sub.setObjectName("lblSubtitle")
        sub.setWordWrap(True)
        root.addWidget(sub)

        card, lay = make_card(tr("section.save_passwords"))
        pol = QHBoxLayout()
        pol.setSpacing(SP["lg"])
        self.policy_btns = {}
        for key in ("ask", "always", "never"):
            rb = QRadioButton(tr(f"lbl.policy_{key}"))
            set_help(rb, f"policy_{key}")
            rb.setChecked(store.policy == key)
            rb.toggled.connect(lambda on, k=key: self._set_policy(k) if on else None)
            self.policy_btns[key] = rb
            pol.addWidget(rb)
        pol.addStretch(1)
        lay.addLayout(pol)
        root.addWidget(card)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in self.COLS])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda r, c: self._edit())
        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(make_empty_state(tr("empty.credentials"), "key"))
        root.addWidget(self.stack, 1)

        row = QHBoxLayout()
        row.setSpacing(SP["sm"])
        self.btn_show = QPushButton(tr("btn.show_passwords"))
        self.btn_show.setObjectName("btnSecondary")
        self.btn_show.setCheckable(True)
        set_help(self.btn_show, "show_passwords")
        self.btn_show.toggled.connect(self._toggle_show)
        row.addWidget(self.btn_show)
        row.addWidget(make_button(tr("btn.edit"), None, "credential_edit", self._edit))
        row.addWidget(make_button(tr("btn.delete"), "btnDanger", "credential_delete", self._delete))
        row.addWidget(make_button(tr("btn.delete_all"), "btnDanger", "credential_delete_all", self._delete_all))
        row.addStretch(1)
        row.addWidget(make_button(tr("btn.new"), None, "credential_new", self._new))
        row.addWidget(make_button(tr("common.close"), "btnPrimary", None, self.accept))
        root.addLayout(row)
        self._show = False
        self.reload()

    def _set_policy(self, key: str) -> None:
        self.store.policy = key
        self.store.save()

    def reload(self) -> None:
        items = sorted(self.store.items, key=lambda c: (c.get("name") or "").lower())
        self._rows = items
        self.table.setRowCount(len(items))
        for r, c in enumerate(items):
            pw = self.store.password(c) if self._show else ("•" * 10 if c.get("secret") else "")
            hosts = ", ".join(sorted(h.rsplit(":", 1)[0] for h in c.get("hosts", {}))) or "—"
            for col, val in enumerate((c.get("name"), c.get("username"), pw, hosts)):
                it = QTableWidgetItem(str(val or ""))
                if col == 1:
                    it.setForeground(QColor(THEME["ip"]))
                if col == 3:
                    it.setToolTip(hosts)
                self.table.setItem(r, col, it)
        self.stack.setCurrentIndex(0 if items else 1)

    def _selected(self) -> Optional[Dict]:
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def _toggle_show(self, on: bool) -> None:
        if on and QMessageBox.question(self, tr("btn.show_passwords"), tr("msg.show_passwords"),
                                       QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            self.btn_show.blockSignals(True)
            self.btn_show.setChecked(False)
            self.btn_show.blockSignals(False)
            return
        self._show = on
        self.reload()

    def _new(self) -> None:
        if _exec(CredentialEditDialog(None, self.store, self)) == QDialog.Accepted:
            self.reload()

    def _edit(self) -> None:
        c = self._selected()
        if c and _exec(CredentialEditDialog(c, self.store, self)) == QDialog.Accepted:
            self.reload()

    def _delete(self) -> None:
        c = self._selected()
        if c and QMessageBox.question(self, tr("msg.delete_title"), tr("msg.delete_credential", name=c.get("name")),
                                      QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.store.delete(c["id"])
            self.reload()

    def _delete_all(self) -> None:
        if self.store.items and QMessageBox.question(self, tr("msg.delete_title"), tr("msg.delete_all_credentials"),
                                                     QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.store.clear()
            self.reload()


class SessionsPanel(QFrame):
    """Árbol de sesiones agrupadas por carpeta, con búsqueda y menú contextual."""
    open_requested = Signal(dict)
    quick_connect = Signal(str)

    def __init__(self, store: SessionStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setObjectName("sidebar")
        self.setMinimumWidth(220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        lay.setSpacing(SP["sm"])

        head = QHBoxLayout()
        head.addWidget(make_section_label(tr("section.sessions")))
        head.addStretch(1)
        self.btn_more = QPushButton(tr("btn.more"))
        self.btn_more.setObjectName("btnSecondary")
        set_help(self.btn_more, "sessions_more")
        more = QMenu(self)
        a = more.addAction(tr("action.import_sessions")); set_help(a, "import_sessions")
        a.triggered.connect(self._import)
        a = more.addAction(tr("action.export_sessions")); set_help(a, "export_sessions")
        a.triggered.connect(self._export)
        attach_menu(self.btn_more, more)
        head.addWidget(self.btn_more)
        lay.addLayout(head)

        self.quick = QLineEdit()
        self.quick.setPlaceholderText(tr("ph.quick_connect"))
        set_help(self.quick, "quick_connect")
        self.quick.returnPressed.connect(self._on_quick)
        lay.addWidget(self.quick)

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("ph.search_sessions"))
        self.search.setClearButtonEnabled(True)
        add_search_icon(self.search)
        set_help(self.search, "search_sessions")
        self.search.textChanged.connect(self.reload)
        lay.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setObjectName("sessionTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.itemActivated.connect(self._on_double)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.stack = QStackedWidget()
        self.empty = make_empty_state(tr("empty.sessions"), "server")
        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.empty)
        lay.addWidget(self.stack, 1)

        self.btn_new = make_button(tr("btn.new_session"), "btnPrimary", "new_session", self.new_session,
                                   shortcut="Ctrl+N")
        lay.addWidget(self.btn_new)
        self.detected: list = []          # WSL y terminales locales encontradas en esta PC
        self.reload()
        self._detect_local()

    def _detect_local(self) -> None:
        """WSL y terminales locales en segundo plano (wsl.exe puede tardar unos segundos)."""
        from networktool.workers import FuncWorker

        def detect():
            out = [local_session("wsl", d["name"], f"WSL · {d['name']}") for d in list_distros()]
            out += [local_session("shell", sh["key"], sh["name"]) for sh in local_shells()]
            return out
        self._detector = FuncWorker(detect)
        self._detector.done.connect(self._on_detected)
        self._detector.start()

    def _on_detected(self, ok: bool, result) -> None:
        self.detected = result if ok and result else []
        self.reload()

    def _on_quick(self) -> None:
        text = self.quick.text().strip()
        if text:
            self.quick_connect.emit(text)
            self.quick.clear()

    # ── Árbol ──────────────────────────────────────────────────────────
    def reload(self, *_):
        text = self.search.text().strip().lower()
        self.tree.clear()
        folders: Dict[str, QTreeWidgetItem] = {}
        shown = 0
        for s in sorted(self.store.sessions, key=lambda x: (x["folder"].lower(), x["name"].lower())):
            hay = " ".join([s["name"], s["host"], s["username"], s["protocol"], s["folder"], s["notes"]]).lower()
            if text and not all(t in hay for t in text.split()):
                continue
            parent = self.tree.invisibleRootItem()
            if s["folder"]:
                if s["folder"] not in folders:
                    f = QTreeWidgetItem([s["folder"]])
                    f.setIcon(0, icon("folder", "ft_folder"))
                    f.setData(0, _ROLE, {"folder": s["folder"]})
                    font = f.font(0); font.setBold(True); f.setFont(0, font)
                    self.tree.addTopLevelItem(f)
                    f.setExpanded(True)
                    folders[s["folder"]] = f
                parent = folders[s["folder"]]
            item = QTreeWidgetItem([f"{s['name']}"])
            item.setData(0, _ROLE, {"id": s["id"]})
            item.setToolTip(0, f"<qt><b>{s['name']}</b><br>"
                               f"<span style='color:{THEME['text_secondary']};'>"
                               f"{PROTOCOL_LABELS[s['protocol']]} · "
                               f"{(s['username'] + '@') if s['username'] else ''}{s['host']}:{s['port']}"
                               f"</span></qt>")
            item.setStatusTip(0, tr("tip.session_item"))
            item.setIcon(0, protocol_icon(s["protocol"]))
            parent.addChild(item) if parent is not self.tree.invisibleRootItem() else self.tree.addTopLevelItem(item)
            shown += 1
        if self.detected and not text.startswith("@"):
            local = QTreeWidgetItem([tr("section.this_pc")])
            local.setData(0, _ROLE, {"folder": "", "auto_folder": True})
            font = local.font(0); font.setBold(True); local.setFont(0, font)
            local.setToolTip(0, tr("tip.this_pc"))
            local.setIcon(0, icon("laptop"))
            for s in self.detected:
                hay = f"{s['name']} {s['protocol']} {s.get('distro', '')}".lower()
                if text and not all(t in hay for t in text.split()):
                    continue
                child = QTreeWidgetItem([s["name"]])
                child.setIcon(0, protocol_icon(s["protocol"]))
                child.setData(0, _ROLE, {"auto": s})
                child.setToolTip(0, tr("tip.local_session"))
                local.addChild(child)
                shown += 1
            if local.childCount():
                self.tree.addTopLevelItem(local)
                local.setExpanded(True)
        self.stack.setCurrentWidget(self.tree if shown else self.empty)
        if not shown and text:
            self.empty.setText(tr("empty.sessions_filter"))
        elif not shown:
            self.empty.setText(tr("empty.sessions"))

    def _item_session(self, item) -> Optional[Dict]:
        data = item.data(0, _ROLE) if item else None
        if data and "auto" in data:
            return data["auto"]
        return self.store.get(data["id"]) if data and "id" in data else None

    def _on_double(self, item, *_):
        s = self._item_session(item)
        if s:
            self.open_requested.emit(s)

    # ── Acciones ───────────────────────────────────────────────────────
    def new_session(self, preset: Optional[Dict] = None) -> Optional[Dict]:
        dlg = SessionDialog(preset or {}, self.store.folders(), self)
        if _exec(dlg) == QDialog.Accepted:
            s = self.store.upsert(dlg.session)
            self.reload()
            return s
        return None

    def edit_session(self, s: Dict) -> None:
        dlg = SessionDialog(s, self.store.folders(), self)
        if _exec(dlg) == QDialog.Accepted:
            self.store.upsert(dlg.session)
            self.reload()

    def _delete(self, s: Dict) -> None:
        if QMessageBox.question(self, tr("msg.delete_title"), tr("msg.delete_session", name=s["name"]),
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.store.delete(s["id"])
            self.reload()

    def _rename_folder(self, folder: str) -> None:
        from networktool.qt_compat import QInputDialog
        new, ok = QInputDialog.getText(self, tr("action.rename_folder"), tr("lbl.folder"), QLineEdit.Normal, folder)
        if ok and new.strip() and new.strip() != folder:
            self.store.rename_folder(folder, new)
            self.reload()

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        s = self._item_session(item)
        menu = QMenu(self)
        if s and s["id"].startswith("auto-"):
            menu.addAction(tr("action.connect")).triggered.connect(lambda: self.open_requested.emit(s))
            menu.addAction(tr("action.save_as_session")).triggered.connect(
                lambda: self.new_session(dict(s, id="")))
        elif s:
            menu.addAction(tr("action.connect")).triggered.connect(lambda: self.open_requested.emit(s))
            menu.addAction(tr("action.edit")).triggered.connect(lambda: self.edit_session(s))
            menu.addAction(tr("action.duplicate")).triggered.connect(
                lambda: (self.store.duplicate(s["id"], tr("common.copy_suffix")), self.reload()))
            menu.addSeparator()
            menu.addAction(tr("action.delete")).triggered.connect(lambda: self._delete(s))
        elif item is not None and (item.data(0, _ROLE) or {}).get("folder"):
            folder = item.data(0, _ROLE)["folder"]
            menu.addAction(tr("action.new_in_folder")).triggered.connect(
                lambda: self.new_session({"folder": folder}))
            menu.addAction(tr("action.rename_folder")).triggered.connect(lambda: self._rename_folder(folder))
        else:
            menu.addAction(tr("btn.new_session")).triggered.connect(self.new_session)
        _exec_menu(menu, self.tree.viewport().mapToGlobal(pos))

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("action.import_sessions"), "", tr("filter.json"))
        if not path:
            return
        try:
            n = self.store.import_from(path)
        except Exception as e:
            QMessageBox.warning(self, tr("msg.error_title"), tr("msg.import_failed", detail=e))
            return
        self.reload()
        QMessageBox.information(self, tr("action.import_sessions"), tr("msg.sessions_imported", n=n))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("action.export_sessions"), "sessions_networktool.json",
                                              tr("filter.json"))
        if path:
            try:
                self.store.export_to(path)
            except Exception as e:
                QMessageBox.warning(self, tr("msg.error_title"), tr("msg.export_failed", detail=e))
