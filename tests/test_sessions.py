"""Tests de preferencias, sesiones guardadas y transportes de las sesiones integradas
(Telnet, SSH y SFTP contra servidores locales de prueba; no salen de 127.0.0.1).

    python -m unittest discover -s tests -v
"""

import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from networktool import i18n  # noqa: E402
i18n.LANG = "es"

from networktool.data.sessions import SessionStore, clean_session, parse_quick_connect  # noqa: E402
from networktool.data.vault import CredentialVault  # noqa: E402
from networktool.settings import Settings, format_port_spec, parse_port_spec  # noqa: E402
from networktool.strings import STRINGS  # noqa: E402
from networktool.qt_compat import QApplication  # noqa: E402
from networktool.ui import filebrowser, terminal  # noqa: E402

try:
    import paramiko
except ImportError:
    paramiko = None


class TestPortSpec(unittest.TestCase):
    def test_parse_and_format(self):
        self.assertEqual(parse_port_spec("22, 80-82 443;8080"), [22, 80, 81, 82, 443, 8080])
        self.assertEqual(parse_port_spec("90-88"), [88, 89, 90])
        self.assertEqual(format_port_spec([21, 22, 23, 80, 443, 444]), "21-23,80,443-444")
        for bad in ("", "0", "70000", "a-b", "80-", "http"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_port_spec(bad)

    def test_settings_roundtrip_and_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Settings(Path(tmp) / "s.json")
            self.assertIn(554, cfg.scan_ports())          # lista recomendada por defecto
            cfg.set("scan_ports", "22,8000-8002")
            cfg.set("scan_workers", 999)
            cfg.save()
            again = Settings(Path(tmp) / "s.json")
            self.assertEqual(again.scan_ports(), [22, 8000, 8001, 8002])
            self.assertEqual(again.int_value("scan_workers", 1, 256), 256)
            again.set("detail_ports", "basura")
            self.assertEqual(len(again.detail_ports()), 1024)


class TestSessions(unittest.TestCase):
    def test_clean_defaults(self):
        s = clean_session({"protocol": "SFTP", "host": " 10.0.0.1 ", "port": "x"})
        self.assertEqual((s["protocol"], s["host"], s["port"], s["name"]), ("sftp", "10.0.0.1", 22, "10.0.0.1"))
        self.assertEqual(clean_session({"protocol": "raro"})["protocol"], "ssh")
        self.assertNotIn("password", s)                   # las contraseñas nunca se guardan

    def test_store_roundtrip_import_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(Path(tmp) / "s.json")
            a = store.upsert({"name": "Router", "folder": "Oficina", "protocol": "ssh", "host": "10.0.0.1",
                              "password": "no-se-guarda"})
            store.upsert({"protocol": "rdp", "host": "10.0.0.2"})
            store.duplicate(a["id"], "(copia)")
            self.assertEqual(len(store.sessions), 3)
            self.assertEqual(store.folders(), ["Oficina"])
            self.assertNotIn("no-se-guarda", (Path(tmp) / "s.json").read_text(encoding="utf-8"))
            store.rename_folder("Oficina", "Casa")
            exp = Path(tmp) / "exp.json"
            store.export_to(str(exp))
            other = SessionStore(Path(tmp) / "o.json")
            self.assertEqual(other.import_from(str(exp)), 3)
            self.assertEqual(other.import_from(str(exp)), 3)   # ids repetidos → ids nuevos
            self.assertEqual(len({s["id"] for s in other.sessions}), 6)
            store.delete(a["id"])
            self.assertEqual(len(SessionStore(Path(tmp) / "s.json").sessions), 2)


class TestQuickConnect(unittest.TestCase):
    def test_formats(self):
        cases = {
            "192.168.0.6": ("ssh", "", "192.168.0.6", 22),
            "root@192.168.0.6:2222": ("ssh", "root", "192.168.0.6", 2222),
            "sftp://pi@nas": ("sftp", "pi", "nas", 22),
            "telnet 10.0.0.1 2323": ("telnet", "", "10.0.0.1", 2323),
            "rdp 10.0.0.5": ("rdp", "", "10.0.0.5", 3389),
            "ftp://anon@ftp.example.com:2121/": ("ftp", "anon", "ftp.example.com", 2121),
        }
        for text, want in cases.items():
            s = parse_quick_connect(text)
            self.assertEqual((s["protocol"], s["username"], s["host"], s["port"]), want, text)
        for bad in ("", "a b c", "ftp://h:99999", "gopher://x", "ssh://"):
            self.assertIsNone(parse_quick_connect(bad), bad)


class TestVault(unittest.TestCase):
    def test_encrypted_and_found_by_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = CredentialVault(Path(tmp) / "v.json")
            self.assertEqual(v.policy, "ask")
            c = v.remember("192.168.0.6", 22, "root", "Sup3r-secreta")
            raw = (Path(tmp) / "v.json").read_text(encoding="utf-8")
            self.assertNotIn("Sup3r-secreta", raw)                    # nunca en claro
            again = CredentialVault(Path(tmp) / "v.json")
            self.assertEqual(again.password(again.get(c["id"])), "Sup3r-secreta")
            self.assertEqual(again.for_host("192.168.0.6", 22)[0]["id"], c["id"])
            self.assertEqual(again.for_host("192.168.0.6", 2222), [])
            # la misma credencial usada en otro equipo no se duplica
            again.remember("10.0.0.1", 22, "root", "Sup3r-secreta")
            self.assertEqual(len(again.items), 1)
            self.assertEqual(len(again.items[0]["hosts"]), 2)
            # editar sin escribir contraseña la conserva
            again.upsert("Raspberry", "root", "", cid=c["id"], keep_password=True)
            self.assertEqual(again.password(again.get(c["id"])), "Sup3r-secreta")
            again.policy = "never"
            again.save()
            self.assertEqual(CredentialVault(Path(tmp) / "v.json").policy, "never")
            again.delete(c["id"])
            self.assertEqual(CredentialVault(Path(tmp) / "v.json").items, [])

    def test_corrupt_secret_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = CredentialVault(Path(tmp) / "v.json")
            c = v.upsert("x", "u", "p")
            c["secret"] = "dpapi:AAAA"
            self.assertEqual(v.password(c), "")


class TestRemoteNames(unittest.TestCase):
    """Un servidor SFTP/FTP malicioso no puede hacer escribir fuera de la carpeta de descarga."""

    def test_listing_drops_traversal_names(self):
        entries = [{"name": n} for n in ("..", ".", "a/b", "x\x00y", "", "ok.txt")]
        self.assertEqual([e["name"] for e in filebrowser._only_valid(entries)], ["ok.txt"])

    def test_local_child_stays_inside(self):
        base = tempfile.mkdtemp()
        self.assertEqual(filebrowser._local_child(base, "ok.txt"), os.path.join(base, "ok.txt"))
        bad = ["..", "../x", "..\\x", "sub\\f"]
        if os.name == "nt":
            bad += ["a:b", "con "]
        for name in bad:
            with self.assertRaises(ValueError, msg=name):
                filebrowser._local_child(base, name)


class TestStrings(unittest.TestCase):
    def test_same_keys_in_both_languages(self):
        self.assertEqual(set(STRINGS["es"]), set(STRINGS["en"]))


# ══════════════════════════════════════════════════════════════════════════
#  TRANSPORTES — servidores de prueba locales
# ══════════════════════════════════════════════════════════════════════════
def _run_backend(backend, until, timeout=10):
    """Arranca el transporte y procesa los eventos Qt (las señales llegan encoladas al hilo principal)."""
    app = QApplication.instance() or QApplication([])
    backend.start()
    end = time.time() + timeout
    while time.time() < end and not until():
        app.processEvents()
        time.sleep(0.02)
    backend.wait(3000)
    app.processEvents()
    return backend


class TestTelnetBackend(unittest.TestCase):
    def test_negotiation_and_echo(self):
        IAC, DO, WILL, SB, SE = 255, 253, 251, 250, 240
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        received = bytearray()

        def server():
            conn, _ = srv.accept()
            conn.sendall(bytes([IAC, DO, 31, IAC, WILL, 1]) + b"login: ")
            conn.settimeout(3)
            try:
                while b"hi\r" not in received:
                    received.extend(conn.recv(1024))
                conn.sendall(b"hi\r\nbye\r\n")
            finally:
                time.sleep(0.2)
                conn.close()
                srv.close()
        threading.Thread(target=server, daemon=True).start()

        b = terminal.TelnetBackend({"host": "127.0.0.1", "port": port}, 100, 30)
        out, closed = bytearray(), []
        b.data.connect(lambda d: out.extend(d))
        b.connected.connect(lambda: b.send(b"hi\r"))
        b.closed.connect(lambda r: closed.append(r))
        _run_backend(b, lambda: closed)
        self.assertEqual(closed, [""])
        self.assertIn(b"login: ", bytes(out))
        self.assertIn(b"bye", bytes(out))
        self.assertNotIn(bytes([IAC]), bytes(out))                      # IAC no llega a la pantalla
        self.assertIn(bytes([IAC, WILL, 31, IAC, SB, 31, 0, 100, 0, 30, IAC, SE]), bytes(received))   # NAWS
        self.assertIn(bytes([IAC, DO, 1]), bytes(received))            # acepta ECHO del servidor


@unittest.skipIf(paramiko is None, "paramiko no instalado")
class TestSSHAndSFTP(unittest.TestCase):
    """Servidor SSH mínimo con shell de eco y subsistema SFTP sobre una carpeta temporal."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "remote"
        cls.root.mkdir()
        (cls.root / "hola.txt").write_text("contenido", encoding="utf-8")
        cls.host_key = paramiko.RSAKey.generate(1024)
        cls.known = Path(cls.tmp.name) / "known_hosts"
        cls.known.touch()
        cls._orig_known = terminal.known_hosts_path
        terminal.known_hosts_path = lambda: str(cls.known)
        cls.srv = socket.socket()
        cls.srv.bind(("127.0.0.1", 0))
        cls.srv.listen(5)
        cls.port = cls.srv.getsockname()[1]
        threading.Thread(target=cls._serve, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        terminal.known_hosts_path = cls._orig_known
        cls.srv.close()
        cls.tmp.cleanup()

    @classmethod
    def _serve(cls):
        root = cls.root

        class Server(paramiko.ServerInterface):
            def check_auth_password(self, username, password):
                ok = (username, password) == ("admin", "secreto")
                return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

            def check_auth_interactive(self, username, submethods):
                if username != "kbi":
                    return paramiko.AUTH_FAILED
                return paramiko.InteractiveQuery("", "", ("Password: ", False))

            def check_auth_interactive_response(self, responses):
                return paramiko.AUTH_SUCCESSFUL if list(responses) == ["secreto"] else paramiko.AUTH_FAILED

            def get_allowed_auths(self, username):
                return "keyboard-interactive" if username == "kbi" else "password"

            def check_channel_request(self, kind, chanid):
                return (paramiko.OPEN_SUCCEEDED if kind == "session"
                        else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED)

            def check_channel_pty_request(self, *a):
                return True

            def check_channel_window_change_request(self, *a):
                return True

            def check_channel_shell_request(self, channel):
                def shell():
                    channel.sendall(b"Bienvenido\r\n$ ")
                    data = b""
                    while b"\r" not in data:
                        chunk = channel.recv(1024)
                        if not chunk:
                            return
                        data += chunk
                    channel.sendall(b"eco:" + data.strip() + b"\r\n")
                    channel.send_exit_status(0)
                    channel.close()
                threading.Thread(target=shell, daemon=True).start()
                return True

        class Handle(paramiko.SFTPHandle):
            def stat(self):
                return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))

        class SFTP(paramiko.SFTPServerInterface):
            def _real(self, path):
                return str(root / path.lstrip("/"))

            def canonicalize(self, path):
                norm = os.path.normpath("/" + path).replace("\\", "/")
                return "/" + norm.lstrip("/")

            def list_folder(self, path):
                out = []
                for name in os.listdir(self._real(path)):
                    attr = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(self._real(path), name)))
                    attr.filename = name
                    out.append(attr)
                return out

            def stat(self, path):
                return paramiko.SFTPAttributes.from_stat(os.stat(self._real(path)))

            lstat = stat

            def open(self, path, flags, attr):
                mode = "wb" if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT) else "rb"
                f = open(self._real(path), mode)
                h = Handle(flags)
                h.filename = self._real(path)
                h.readfile = h.writefile = f
                return h

            def mkdir(self, path, attr):
                os.mkdir(self._real(path))
                return paramiko.SFTP_OK

            def rmdir(self, path):
                try:
                    os.rmdir(self._real(path))
                except OSError:
                    return paramiko.SFTP_FAILURE          # carpeta no vacía: como un servidor real
                return paramiko.SFTP_OK

            def chattr(self, path, attr):
                if attr.st_mode is not None:
                    os.chmod(self._real(path), attr.st_mode)
                return paramiko.SFTP_OK

            def remove(self, path):
                os.remove(self._real(path))
                return paramiko.SFTP_OK

            def rename(self, old, new):
                os.rename(self._real(old), self._real(new))
                return paramiko.SFTP_OK

        while True:
            try:
                conn, _ = cls.srv.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(cls.host_key)
            t.set_subsystem_handler("sftp", paramiko.SFTPServer, SFTP)
            t.start_server(server=Server())

    def _cred(self, **kw):
        return dict({"host": "127.0.0.1", "port": self.port, "username": "admin", "password": "secreto",
                     "key_file": ""}, **kw)

    def test_shell_echo_and_hostkey_saved(self):
        b = terminal.SSHBackend(self._cred(), 80, 24)
        out, closed, asked = bytearray(), [], []
        b.data.connect(lambda d: out.extend(d))
        b.host_key.connect(lambda h, fp: (asked.append(fp), b.answer_host_key(True)))
        b.connected.connect(lambda: b.send(b"ls\r"))
        b.closed.connect(lambda r: closed.append(r))
        _run_backend(b, lambda: closed, timeout=20)
        self.assertLessEqual(len(asked), 1)
        self.assertIn(b"Bienvenido", bytes(out))
        self.assertIn(b"eco:ls", bytes(out))
        self.assertIn("127.0.0.1", self.known.read_text())

    def test_wrong_password(self):
        b = terminal.SSHBackend(self._cred(password="mal"), 80, 24)
        closed = []
        b.host_key.connect(lambda h, fp: b.answer_host_key(True))
        b.closed.connect(lambda r: closed.append(r))
        _run_backend(b, lambda: closed, timeout=20)
        self.assertTrue(closed and closed[0])          # cierra con un motivo de error

    def test_keyboard_interactive_only_server(self):
        asker = terminal._Backend()
        asker.host_key.connect(lambda h, fp: asker.answer_host_key(True))
        client = terminal.open_ssh_client(asker, self._cred(username="kbi"))
        try:
            self.assertTrue(client.get_transport().is_authenticated())
        finally:
            client.close()

    def test_auth_error_is_flagged(self):
        b = terminal.SSHBackend(self._cred(password="mal"), 80, 24)
        closed = []
        b.host_key.connect(lambda h, fp: b.answer_host_key(True))
        b.closed.connect(lambda r: closed.append(r))
        _run_backend(b, lambda: closed, timeout=20)
        self.assertTrue(b.auth_failed)

    def test_sftp_over_terminal_connection(self):
        """SSH + SFTP juntos: el panel SFTP usa la conexión de la terminal y no la cierra."""
        asker = terminal._Backend()
        asker.host_key.connect(lambda h, fp: asker.answer_host_key(True))
        client = terminal.open_ssh_client(asker, self._cred())
        try:
            fs = filebrowser.SFTPFS.from_client(client, "/")
            self.assertEqual(fs.open_on_client(), "/")
            self.assertIn("hola.txt", {e["name"] for e in fs.listdir("/")})
            fs.close()                                         # solo el canal SFTP
            self.assertTrue(client.get_transport().is_active())
            chan = client.invoke_shell()                       # la terminal sigue funcionando
            self.assertIn(b"Bienvenido", chan.recv(100))
        finally:
            client.close()

    def test_sftp_operations(self):
        asker = terminal._Backend()
        asker.host_key.connect(lambda h, fp: asker.answer_host_key(True))
        fs = filebrowser.SFTPFS(self._cred(remote_path="/"), asker)
        try:
            self.assertEqual(fs.connect(), "/")
            names = {e["name"]: e for e in fs.listdir("/")}
            self.assertFalse(names["hola.txt"]["is_dir"])
            local = Path(self.tmp.name) / "bajado.txt"
            progress = []
            fs.download("/hola.txt", str(local), progress.append)
            self.assertEqual(local.read_text(encoding="utf-8"), "contenido")
            self.assertEqual(progress[-1], 100)
            fs.mkdir("/nueva")
            fs.upload(str(local), "/nueva/subido.txt", lambda p: None)
            self.assertTrue((self.root / "nueva" / "subido.txt").exists())
            fs.rename("/nueva/subido.txt", "/nueva/renombrado.txt")
            fs.remove("/nueva/renombrado.txt", False)
            self.assertEqual(fs.listdir("/nueva"), [])
        finally:
            fs.close()


class TestTerminalTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_osc7_cwd_tracking_split_packets(self):
        view = terminal.TerminalView()
        seen = []
        view.cwd_changed.connect(seen.append)
        view.feed(b"prompt\x1b]7;/home/p")              # secuencia partida en dos paquetes
        view.feed(b"i\x07$ ")
        view.feed(b"\x1b]7;file://host/var/log\x1b\\")
        self.app.processEvents()
        self.assertEqual(seen, ["/home/pi", "/var/log"])
        text = "".join(c.data for c in view._line_at(len(view.screen.history)))
        self.assertNotIn("]7;", text)                     # la secuencia no se dibuja

    def test_telnet_autologin(self):
        tab = terminal.TerminalTab({"protocol": "telnet", "name": "r", "encoding": "utf-8"},
                                   {"host": "10.0.0.1", "port": 23, "username": "admin", "password": "clave"})
        sent = []
        tab.send = sent.append
        tab.view.feed(b"\x1b[1mRouter\x1b[0m\r\nlogin: ")
        tab.view.feed(b"admin\r\nPassword: ")
        tab.view.feed(b"\r\nRouter> login: ")              # no vuelve a responder
        self.app.processEvents()
        self.assertEqual(sent, [b"admin\r", b"clave\r"])
        tab.shutdown()


class TestSFTPExplorer(unittest.TestCase):
    """Operaciones nuevas del explorador contra el servidor SFTP de prueba."""

    @classmethod
    def setUpClass(cls):
        TestSSHAndSFTP.setUpClass()
        cls.srv = TestSSHAndSFTP

    @classmethod
    def tearDownClass(cls):
        TestSSHAndSFTP.tearDownClass()

    def setUp(self):
        asker = terminal._Backend()
        asker.host_key.connect(lambda h, fp: asker.answer_host_key(True))
        cred = {"host": "127.0.0.1", "port": self.srv.port, "username": "admin", "password": "secreto",
                "key_file": "", "remote_path": "/"}
        self.fs = filebrowser.SFTPFS(cred, asker)
        self.fs.connect()

    def tearDown(self):
        self.fs.close()

    def test_delete_full_folder_recursively(self):
        root = self.srv.root / "llena" / "sub"
        root.mkdir(parents=True)
        (root / "a.txt").write_text("x")
        (self.srv.root / "llena" / "b.txt").write_text("y")
        with self.assertRaises(IOError) as ctx:          # rmdir solo: "Failure" (lo que veías)
            self.fs.remove("/llena", True)
        self.assertEqual(filebrowser.friendly_error(ctx.exception), i18n.tr("fb.err_failure"))
        self.fs.remove_tree("/llena")
        self.assertFalse((self.srv.root / "llena").exists())

    def test_touch_stat_chmod_owner(self):
        self.fs.touch("/nuevo.txt")
        self.assertTrue((self.srv.root / "nuevo.txt").exists())
        e = {x["name"]: x for x in self.fs.listdir("/")}["nuevo.txt"]
        self.assertTrue(e["owner"] and e["group"])          # el servidor de prueba manda uid/gid
        self.assertEqual(filebrowser._parse_longname("-rw-r--r--  1 pi  staff  5452 Nov  3 16:14 a.db"),
                         ("pi", "staff"))
        self.fs.chmod("/nuevo.txt", 0o600)
        self.assertEqual(self.fs.stat("/nuevo.txt")["name"], "nuevo.txt")
        self.fs.remove("/nuevo.txt", False)

    def test_folder_download_and_upload(self):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "subir"
        (src / "x").mkdir(parents=True)
        (src / "x" / "1.txt").write_text("uno")
        (src / "2.txt").write_text("dos")
        self.assertEqual(self.fs.upload_tree(str(src), "/subida", lambda p: None), 2)
        self.assertEqual((self.srv.root / "subida" / "x" / "1.txt").read_text(), "uno")
        self.assertEqual(self.fs.download_tree("/subida", str(tmp / "bajada"), lambda p: None), 2)
        self.assertEqual((tmp / "bajada" / "2.txt").read_text(), "dos")
        self.fs.remove_tree("/subida")


class TestLocalFSAndWSL(unittest.TestCase):
    def test_localfs_posix_paths(self):
        root = Path(tempfile.mkdtemp())
        (root / "home" / "pi").mkdir(parents=True)
        (root / "home" / "pi" / ".bashrc").write_text("x")
        fs = filebrowser.LocalFS(str(root), start="~")
        self.assertEqual(fs.connect(), "/home/pi")
        names = {e["name"] for e in fs.listdir("/home/pi")}
        self.assertEqual(names, {".bashrc"})
        fs.mkdir("/home/pi/d")
        fs.touch("/home/pi/d/f")
        fs.rename("/home/pi/d/f", "/home/pi/d/g")
        fs.remove_tree("/home/pi/d")
        self.assertFalse((root / "home" / "pi" / "d").exists())

    def test_parse_wsl_list(self):
        from networktool.net import wsl
        raw = "Ubuntu\r\nDebian\r\n".encode("utf-16-le")
        self.assertEqual(wsl.parse_wsl_list(wsl._decode_wsl_output(raw)), ["Ubuntu", "Debian"])
        not_installed = "El Subsistema de Windows para Linux no está instalado.".encode("utf-16-le")
        self.assertEqual(wsl.parse_wsl_list(wsl._decode_wsl_output(not_installed)), [])
        self.assertEqual(wsl.wsl_command("Ubuntu"), ["wsl.exe", "-d", "Ubuntu", "--cd", "~"])

    def test_quick_connect_local(self):
        s = parse_quick_connect("wsl Ubuntu")
        self.assertEqual((s["protocol"], s["distro"], s["port"]), ("wsl", "Ubuntu", 0))
        self.assertEqual(parse_quick_connect("powershell")["shell"], "powershell")

    @unittest.skipUnless(sys.platform == "win32", "solo Windows")
    def test_local_pty_backend_cmd(self):
        try:
            __import__("winpty")  # solo comprueba que esté instalado
        except ImportError:
            self.skipTest("pywinpty no instalado")
        b = terminal.LocalPtyBackend({"command": ["cmd.exe"]}, 100, 30)
        out, closed = bytearray(), []
        b.data.connect(lambda d: out.extend(d))
        b.connected.connect(lambda: b.send(b"echo pty-ok-123\r\nexit\r\n"))
        b.closed.connect(lambda r: closed.append(r))
        _run_backend(b, lambda: closed, timeout=20)
        self.assertIn(b"pty-ok-123", bytes(out))


class TestFTPListFallback(unittest.TestCase):
    def test_unix_list_parsing(self):
        fs = filebrowser.FTPFS({})

        class FakeFTP:
            def retrlines(self, cmd, cb):
                for line in ("drwxr-xr-x  2 user group  4096 Jan 01 10:00 carpeta",
                             "-rw-r--r--  1 user group  1234 Jan 01 10:00 archivo con espacios.txt",
                             "lrwxrwxrwx  1 user group     7 Jan 01 10:00 enlace -> destino"):
                    cb(line)
        fs.ftp = FakeFTP()
        entries = {e["name"]: e for e in fs._list_fallback("/")}
        self.assertTrue(entries["carpeta"]["is_dir"])
        self.assertEqual(entries["archivo con espacios.txt"]["size"], 1234)
        self.assertIn("enlace", entries)

    def test_human_size(self):
        self.assertEqual(filebrowser.human_size(512), "512 B")
        self.assertEqual(filebrowser.human_size(1536), "1.5 KB")
        self.assertEqual(filebrowser.human_size(None), "")


if __name__ == "__main__":
    unittest.main()
