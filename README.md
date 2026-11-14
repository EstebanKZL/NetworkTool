# NetworkTool

Escáner de red, configuración IP rápida y sesiones remotas en un solo programa de
escritorio: encontrá los equipos de tu red, cambiá la IP del adaptador en un clic y
abrí SSH, SFTP, Telnet o FTP en pestañas, sin otra herramienta.

## Qué hace

- **Escanea la red**: IP, MAC, fabricante, nombre, puertos abiertos y tipo de equipo
  (cámaras, servidores, impresoras…). Monitor periódico y comparación con el escaneo anterior.
- **Configura la IP** del adaptador: DHCP, IP manual, IPs secundarias y perfiles propios,
  con historial y vuelta atrás automática si algo falla.
- **Sesiones remotas integradas**: SSH con explorador SFTP al lado, Telnet, FTP, y las
  terminales locales y distribuciones WSL de la PC. RDP, VNC y web abren con el cliente del sistema.
- **Credenciales cifradas** (DPAPI en Windows, Fernet en Linux/macOS): se completan solas
  al reconectar.
- **Explorador de archivos remoto**: subir, bajar, arrastrar y soltar, permisos, editar y
  "abrir con" con subida automática de los cambios.
- **Herramientas**: ping, traceroute, Wake-on-LAN, DNS, calculadora de subredes,
  inventario y reportes en Excel y PDF.
- Interfaz en **español e inglés**, tema **oscuro** (Grafito) o **claro** (Papel).

## Instalar y usar

- Descargá la última versión desde [Releases](../../releases): portable (`.zip`) o
  instalador (`setup.exe`) para Windows 10/11 (`win`) o Windows 7 a 11 en 64 y 32 bits
  (`win7`), y AppImage para Linux. Cuál elegir: [Install.md](Install.md).
- Guía de uso: [Usage.md](Usage.md). Cambios por versión: [CHANGELOG.md](CHANGELOG.md).

Desde el código (Python 3.8 o más nuevo):

```bash
pip install -r requirements.txt
python src/main.py
```

## Problemas y sugerencias

Abrí un *issue* en este repositorio. Para reportar una vulnerabilidad: [SECURITY.md](SECURITY.md).
Para colaborar: [CONTRIBUTING.md](CONTRIBUTING.md).

## Licencia

[GPL-3.0](LICENSE) © EstebanKZL. Componentes de terceros: [THIRD-PARTY.md](THIRD-PARTY.md).
