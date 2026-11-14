# Instalación

## Qué descargar

Desde la pestaña **Releases** del repositorio:

| Sistema | Archivo | Cómo se usa |
|---------|---------|-------------|
| Windows 10/11 (64 bits) | `NetworkTool-<versión>-win-x64-portable.zip` | Descomprimir y abrir `NetworkTool.exe`; no se instala nada. |
| Windows 10/11 (64 bits) | `NetworkTool-<versión>-win-x64-setup.exe` | Instalador con acceso directo y desinstalador. |
| Windows 7, 8, 10 y 11 (64 bits) | `NetworkTool-<versión>-win7-x64-portable.zip` / `-setup.exe` | Igual que las de arriba. |
| Windows 7, 8, 10 y 11 (32 bits) | `NetworkTool-<versión>-win7-x86-portable.zip` / `-setup.exe` | También es la versión para Windows 10/11 de 32 bits. |
| Linux 64 bits | `NetworkTool-<versión>-linux-x86_64.AppImage` | `chmod +x` y doble clic (distros de 2022 en adelante). |

El portable es una carpeta comprimida y no un único `.exe`: abre más rápido y los
antivirus lo marcan mucho menos como falso positivo.

¿Cuál elegir en Windows? Si tu Windows es 10 u 11 de 64 bits (casi todas las PCs
actuales), la `win`. Para Windows 7/8, o cualquier Windows de 32 bits, la `win7` de tu
arquitectura. En la `win7` la terminal local y WSL integradas no están disponibles
(Windows 7 no tiene ConPTY); SSH, Telnet, SFTP, FTP y el escáner funcionan igual.

Para comprobar que un archivo no fue alterado, compará su hash con el de
`SHA256SUMS.txt` del mismo release:

```bash
sha256sum -c SHA256SUMS.txt --ignore-missing
```

```bash
certutil -hashfile NetworkTool-7.4.0-win-x64-portable.zip SHA256
```

Los ejecutables no están firmados digitalmente: Windows puede mostrar el aviso de
"editor desconocido" (SmartScreen). Elegí **Más información → Ejecutar de todas formas**.

## Permisos

El programa abre como usuario normal. Para **cambiar la configuración IP** del
adaptador hace falta ser Administrador: la app lo pide en ese momento y se reinicia
con permisos elevados. Escanear, abrir sesiones y el resto de las herramientas no lo
necesitan.

En Linux, cambiar la IP usa `nmcli` (NetworkManager).

## Dónde guarda los datos

| Sistema | Carpeta |
|---------|---------|
| Windows | `%APPDATA%\NetworkTool` |
| Linux / macOS | `~/.config/networktool` |

Ahí quedan las sesiones, los perfiles de IP, el inventario, las preferencias, las
claves de host SSH conocidas y el registro. Las contraseñas se guardan **cifradas**
(`vault.json`): en Windows con DPAPI, ligadas a tu usuario; en Linux/macOS con una clave
local propia. El tema y el idioma se guardan en la configuración del usuario de Qt.

Para desinstalar sin dejar rastros, borrá también esa carpeta.

## Desde el código fuente

Requiere Python 3.8 o más nuevo (3.8 solo para Windows 7, con PySide2):

```bash
pip install -r requirements.txt
```

```bash
python src/main.py
```

Opciones: `--debug` (registro detallado) y `--selftest informe.json` (autodiagnóstico sin
interfaz).
