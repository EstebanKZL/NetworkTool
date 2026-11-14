"""Tests de los parsers y cálculos de NetworkTool (no tocan la configuración de red).

Ejecutar desde la carpeta del proyecto:
    python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from networktool import i18n  # noqa: E402
i18n.LANG = "es"   # los textos esperados de estos tests están en español

from networktool import common  # noqa: E402
from networktool.data import inventory as inv_mod  # noqa: E402
from networktool.data.profiles import ProfileStore  # noqa: E402
from networktool.net import adapters, discovery, ipconfig, services  # noqa: E402
from networktool import tools  # noqa: E402

NETSH_ES_STATIC = """
Configuración para la interfaz "Conexión de área local"
    DHCP habilitado:                          No
    Dirección IP:                           192.168.1.10
    Prefijo de subred:                    192.168.1.0/24 (máscara 255.255.255.0)
    Dirección IP:                           172.19.101.10
    Prefijo de subred:                    172.19.101.0/24 (máscara 255.255.255.0)
    Puerta de enlace predeterminada:      192.168.1.1
    Métrica de puerta de enlace:          1
    Métrica de interfaz:                  25
    Servidores DNS configurados estáticamente:    8.8.8.8
    Registrar con sufijo:           Solo principal
    Servidores WINS configurados estáticamente:   Ninguno
"""

NETSH_EN_DHCP = """
Configuration for interface "Wi-Fi"
    DHCP enabled:                         Yes
    IP Address:                           192.168.0.48
    Subnet Prefix:                        192.168.0.0/24 (mask 255.255.255.0)
    Default Gateway:                      192.168.0.1
    Gateway Metric:                       0
    InterfaceMetric:                      35
    DNS servers configured through DHCP:  192.168.0.1
"""

NETSH_ES_DHCP_NO_LEASE = """
Configuración para la interfaz "Ethernet 2"
    DHCP habilitado:                          Sí
    Métrica de interfaz:                  25
    Servidores DNS configurados a través de DHCP:  Ninguno
"""

ARP_WINDOWS_ES = """
Interfaz: 192.168.0.48 --- 0x13
  Dirección de Internet          Dirección física      Tipo
  192.168.0.1           ac-c6-62-c1-b1-1e     dinámico
  192.168.0.5           ec-08-6b-29-57-52     dinámico
  192.168.0.255         ff-ff-ff-ff-ff-ff     estático
  224.0.0.22            01-00-5e-00-00-16     estático
"""

ARP_MACOS = """
? (192.168.0.1) at ac:c6:62:c1:b1:1e on en0 ifscope [ethernet]
? (192.168.0.20) at b4:ad:a3:4b:94:d on en0 ifscope [ethernet]
? (192.168.0.99) at (incomplete) on en0 ifscope [ethernet]
"""

INTERFACES_NETSH = """
Idx     Met         MTU          Estado                Nombre
---  ----------  ----------  ------------  ---------------------------
  1          75  4294967295  connected     Loopback Pseudo-Interface 1
 19          25        1500  connected     Ethernet
 10          35        1500  disconnected  Wi-Fi
 23          25        1500  disconnected  Conexión de área local 2
"""


class TestMasks(unittest.TestCase):
    def test_normalize_mask(self):
        self.assertEqual(common._normalize_mask("24"), "255.255.255.0")
        self.assertEqual(common._normalize_mask("/16"), "255.255.0.0")
        self.assertEqual(common._normalize_mask("255.255.255.128"), "255.255.255.128")
        for bad in ("255.0.255.0", "33", "0", "abc"):
            with self.assertRaises(ValueError):
                common._normalize_mask(bad)

    def test_mask_to_cidr(self):
        self.assertEqual(common.mask_to_cidr("255.255.254.0"), 23)
        self.assertEqual(common.mask_to_cidr("invalida"), 24)   # valor por defecto histórico

    def test_normalize_mac(self):
        self.assertEqual(common._normalize_mac("ac-c6-62-c1-b1-1e"), "AC:C6:62:C1:B1:1E")
        self.assertEqual(common._normalize_mac("b4:ad:a3:4b:94:d"), "B4:AD:A3:4B:94:0D")
        for bad in ("ff-ff-ff-ff-ff-ff", "00:00:00:00:00:00", "01-00-5e-00-00-16", "zz", "", None):
            self.assertIsNone(common._normalize_mac(bad))


class TestNetshParsing(unittest.TestCase):
    def _read(self, text):
        with mock.patch.object(adapters, "run_command", return_value=text), \
             mock.patch.object(adapters, "_netsh_name", return_value="19"):
            return adapters._win_read_config("Ethernet")

    def test_static_spanish_two_ips(self):
        cfg = self._read(NETSH_ES_STATIC)
        self.assertIs(cfg["dhcp"], False)
        self.assertEqual(cfg["ips"], [("192.168.1.10", "255.255.255.0"), ("172.19.101.10", "255.255.255.0")])
        self.assertEqual(cfg["gateway"], "192.168.1.1")

    def test_dhcp_english(self):
        cfg = self._read(NETSH_EN_DHCP)
        self.assertIs(cfg["dhcp"], True)
        self.assertEqual(cfg["ips"], [("192.168.0.48", "255.255.255.0")])
        self.assertEqual(cfg["gateway"], "192.168.0.1")

    def test_dhcp_without_lease(self):
        cfg = self._read(NETSH_ES_DHCP_NO_LEASE)
        self.assertIs(cfg["dhcp"], True)
        self.assertEqual(cfg["ips"], [])
        self.assertIsNone(cfg["gateway"])

    def test_interface_indexes(self):
        with mock.patch.object(adapters, "run_command", return_value=INTERFACES_NETSH):
            idx = adapters._win_interface_indexes()
        self.assertEqual(idx["Ethernet"], 19)
        self.assertEqual(idx["Conexión de área local 2"], 23)
        self.assertEqual(idx["Wi-Fi"], 10)

    def test_virtual_adapter_filter_keeps_local_area_connection(self):
        with mock.patch.object(adapters, "IS_WINDOWS", True):
            self.assertFalse(adapters._is_virtual_adapter("Conexión de área local"))
            self.assertFalse(adapters._is_virtual_adapter("Ethernet 2"))
            self.assertTrue(adapters._is_virtual_adapter("vEthernet (WSL)"))
            self.assertTrue(adapters._is_virtual_adapter("VMware Network Adapter VMnet8"))


class TestValidation(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(ipconfig._validate_static("169.254.147.10", "24", "169.254.147.1", ""),
                         ("169.254.147.10", "255.255.255.0", "169.254.147.1", []))
        self.assertEqual(ipconfig._validate_static("10.0.0.5", "255.255.255.0", "", "8.8.8.8, 1.1.1.1")[3],
                         ["8.8.8.8", "1.1.1.1"])

    def test_invalid(self):
        cases = [("192.168.1.0", "24", "", ""),          # dirección de red
                 ("192.168.1.255", "24", "", ""),        # broadcast
                 ("10.0.0.5", "24", "10.0.1.1", ""),     # gateway fuera de la red
                 ("10.0.0.5", "24", "10.0.0.5", ""),     # gateway = IP
                 ("300.1.1.1", "24", "", ""),
                 ("10.0.0.5", "24", "", "8.8.8")]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                ipconfig._validate_static(*case)

    def test_extra_ips(self):
        self.assertEqual(ipconfig._parse_extra_ips(["172.19.101.10/24", "10.0.0.5", "10.0.0.5/16", "1.1.1.1"],
                                                   "255.255.255.0", "1.1.1.1"),
                         [("172.19.101.10", "255.255.255.0"), ("10.0.0.5", "255.255.255.0")])
        with self.assertRaises(ValueError):
            ipconfig._parse_extra_ips(["999.1.1.1"], "24")


class TestArpTable(unittest.TestCase):
    def test_windows_spanish(self):
        with mock.patch.object(discovery, "IS_LINUX", False), \
             mock.patch.object(discovery, "run_command", return_value=ARP_WINDOWS_ES):
            table = discovery.read_arp_table()
        self.assertEqual(table, {"192.168.0.1": "AC:C6:62:C1:B1:1E", "192.168.0.5": "EC:08:6B:29:57:52"})

    def test_macos_short_octets(self):
        with mock.patch.object(discovery, "IS_LINUX", False), \
             mock.patch.object(discovery, "run_command", return_value=ARP_MACOS):
            table = discovery.read_arp_table()
        self.assertEqual(table["192.168.0.20"], "B4:AD:A3:4B:94:0D")
        self.assertNotIn("192.168.0.99", table)


class TestPing(unittest.TestCase):
    def _latency(self, output):
        with mock.patch.object(tools, "_run_command", return_value=(output, "", 0)):
            return tools.ping_latency("192.168.0.1")

    def test_formats(self):
        self.assertEqual(self._latency("Respuesta desde 192.168.0.1: bytes=32 tiempo=12ms TTL=64"), 12.0)
        self.assertEqual(self._latency("Respuesta desde 192.168.0.1: bytes=32 tiempo<1m TTL=64"), 1.0)
        self.assertEqual(self._latency("Reply from 192.168.0.1: bytes=32 time=3ms TTL=64"), 3.0)
        self.assertAlmostEqual(self._latency("64 bytes from 192.168.0.1: icmp_seq=1 ttl=64 time=0.412 ms"), 0.412)
        self.assertIsNone(self._latency("Respuesta desde 192.168.0.48: Host de destino inaccesible."))
        self.assertIsNone(self._latency("Tiempo de espera agotado para esta solicitud."))


class TestTools(unittest.TestCase):
    def test_subnet_info(self):
        info = dict(tools.subnet_info("172.19.101.10/23"))
        self.assertEqual(info["Red"], "172.19.100.0/23")
        self.assertEqual(info["Broadcast"], "172.19.101.255")
        self.assertEqual(info["Hosts utilizables"], "510")
        self.assertEqual(dict(tools.subnet_info("169.254.147.10", "24"))["Tipo"], "Link-local / APIPA (169.254.x.x)")

    def test_split(self):
        subs = tools.split_subnet("192.168.1.0/24", 26)
        self.assertEqual(len(subs), 4)
        self.assertTrue(subs[1].startswith("192.168.1.64/26"))
        with self.assertRaises(ValueError):
            tools.split_subnet("192.168.1.0/24", 20)

    def test_magic_packet(self):
        sent = []
        class FakeSocket:
            def __init__(self, *a): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def setsockopt(self, *a): pass
            def sendto(self, data, addr): sent.append((data, addr))
        with mock.patch.object(tools.socket, "socket", FakeSocket):
            tools.send_magic_packet("02-00-00-00-00-01", "192.168.0.255", 9)
        data, addr = sent[0]
        self.assertEqual(len(data), 102)
        self.assertEqual(data[:6], b"\xff" * 6)
        self.assertEqual(data[6:12], bytes.fromhex("020000000001"))
        self.assertEqual({a for _, a in sent}, {("192.168.0.255", 9), ("255.255.255.255", 9)})


class TestOui(unittest.TestCase):
    MANUF = ("# comentario\n"
             "AC:C6:62\tMitraSta\tMitraStar Technology Corp.\n"
             "00:55:DA:00:00:00/28\tShinkoTe\tShinko Technos co.,ltd.\n"
             "00:1B:C5:00:00:00/36\tConvergi\tConverging Systems Inc.\n")

    def test_parse_and_lookup(self):
        rows = services._parse_wireshark_manuf(self.MANUF)
        self.assertEqual(rows[0], ("ACC662", 24, "MitraStar Technology Corp."))
        self.assertEqual(rows[1], ("0055DA0", 28, "Shinko Technos co.,ltd."))
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oui_db.tsv"
            db.write_text("\n".join(f"{h}\t{b}\t{v}" for h, b, v in rows), encoding="utf-8")
            with mock.patch.object(services, "oui_db_path", return_value=db), \
                 mock.patch.object(services, "_oui_db", None):
                self.assertEqual(services.oui_lookup("AC:C6:62:C1:B1:1E"), "MitraStar Technology Corp.")
                self.assertEqual(services.oui_lookup("00:55:DA:01:02:03"), "Shinko Technos co.,ltd.")
                self.assertEqual(services.oui_lookup("00:1B:C5:00:00:42"), "Converging Systems Inc.")
                self.assertIsNone(services.oui_lookup("12:34:56:78:9A:BC"))

    def test_ieee_csv(self):
        csv_text = 'Registry,Assignment,Organization Name,Organization Address\nMA-L,ACC662,"MitraStar Technology Corp.","Taiwan"\n'
        self.assertEqual(services._parse_ieee_csv(csv_text), [("ACC662", 24, "MitraStar Technology Corp.")])


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inv = inv_mod.Inventory(Path(self.tmp.name) / "inv.db")

    def tearDown(self):
        self.inv.close()
        self.tmp.cleanup()

    def test_shared_mac_gets_one_device_per_ip(self):
        results = [{"ip": "192.168.0.58", "mac": "F8:16:0C:7C:31:BC"}, {"ip": "192.168.0.59", "mac": "F8:16:0C:7C:31:BC"},
                   {"ip": "192.168.0.1", "mac": "AC:C6:62:C1:B1:1E"}]
        self.assertEqual(inv_mod.shared_macs(results), {"F8:16:0C:7C:31:BC"})
        self.assertEqual(inv_mod.device_key("192.168.0.58", "F8:16:0C:7C:31:BC", True), "F8:16:0C:7C:31:BC@192.168.0.58")
        self.assertEqual(inv_mod.device_key("192.168.0.9", "Unknown"), "ip:192.168.0.9")

    def test_alias_survives_ip_change_and_compare(self):
        dev = self.inv.upsert_device({"ip": "10.0.0.5", "mac": "AA:BB:CC:00:00:01", "host": "cam", "dev": "RTSP Camera"}, "10.0.0.0/24")
        self.inv.set_meta(dev["key"], "Cámara andén 2", "nota")
        s1 = self.inv.record_scan("Ethernet", "10.0.0.0/24", "t1", [
            {"ip": "10.0.0.5", "mac": "AA:BB:CC:00:00:01"}, {"ip": "10.0.0.7", "mac": "AA:BB:CC:00:00:07"}])
        moved = self.inv.upsert_device({"ip": "10.0.0.6", "mac": "AA:BB:CC:00:00:01", "dev": "RTSP Camera"}, "10.0.0.0/24")
        self.assertEqual(moved["alias"], "Cámara andén 2")
        self.assertEqual({h["ip"] for h in self.inv.ip_history(moved["key"])}, {"10.0.0.5", "10.0.0.6"})
        s2 = self.inv.record_scan("Ethernet", "10.0.0.0/24", "t2", [
            {"ip": "10.0.0.6", "mac": "AA:BB:CC:00:00:01"}, {"ip": "10.0.0.8", "mac": "AA:BB:CC:00:00:08"}])
        self.assertEqual(self.inv.previous_scan("10.0.0.0/24", s2)["id"], s1)
        cmp = self.inv.compare_scans(s1, s2)
        self.assertEqual([h["ip"] for h in cmp["new"]], ["10.0.0.8"])
        self.assertEqual([h["ip"] for h in cmp["missing"]], ["10.0.0.7"])
        self.assertEqual([(a["ip"], b["ip"]) for a, b in cmp["ip_changed"]], [("10.0.0.5", "10.0.0.6")])


class TestProfiles(unittest.TestCase):
    def test_defaults_history_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp) / "p.json")
            self.assertEqual(store.profiles, [])          # sin perfiles de fábrica
            store.profiles.append({"name": "Oficina", "group": "", "ip": "10.0.0.10", "mask": "255.255.255.0",
                                   "gateway": "10.0.0.1", "dns": "", "extra_ips": []})
            store.save()
            store.push_history("Ethernet", {"dhcp": True, "ip": None, "mask": "", "gateway": "", "extra": []})
            store.push_history("Ethernet", {"dhcp": False, "ip": "169.254.147.10", "mask": "255.255.255.0", "gateway": "", "extra": []})
            self.assertEqual(store.pop_last_for("Ethernet")["ip"], "169.254.147.10")
            self.assertTrue(store.last_for("Ethernet")["dhcp"])
            exported = Path(tmp) / "exp.json"
            store.export_to(str(exported))
            other = ProfileStore(Path(tmp) / "q.json")
            other.profiles = []
            self.assertEqual(other.import_from(str(exported), replace=True), len(store.profiles))
            self.assertEqual(ProfileStore(Path(tmp) / "q.json").profiles, store.profiles)


@unittest.skipUnless(common.IS_WINDOWS, "solo Windows")
class TestLiveWindows(unittest.TestCase):
    """Lectura real (solo lectura) de la configuración de este equipo."""

    def test_adapters_have_index_and_dhcp_state(self):
        names = adapters.get_adapters()
        self.assertTrue(names)
        for name in names:
            ip, mask, gw, dhcp = adapters.get_ip_info(name)
            self.assertIn(dhcp, ("Habilitado", "Deshabilitado", "Desconocido"))
        self.assertNotIn("Desconocido", {adapters.get_ip_info(n)[3] for n in names if adapters._adapter_index(n) is not None})


if __name__ == "__main__":
    unittest.main()
