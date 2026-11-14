# Guía de uso

Todo control tiene ayuda: dejá el mouse encima y aparece qué hace y su atajo.

## Escáner de red

1. Elegí el **adaptador**: la red y el rango se completan solos (podés cambiarlos).
2. **Iniciar escaneo** (Ctrl+E). Cada equipo aparece con IP, MAC, fabricante, nombre,
   puertos abiertos y tipo.
3. En la columna **Conectar** hay un botón por servicio encontrado (SSH, web, RDP…).
   Clic derecho sobre una fila: re-escanear puertos, alias, guardar como sesión,
   herramientas.
4. **Monitor**: repite el escaneo cada cierto tiempo y avisa de equipos nuevos o caídos.
5. **Exportar**: CSV, Excel con resumen o informe PDF. **Inventario** guarda los equipos
   con su historial.

Qué puertos se analizan, cuántos equipos en paralelo y los tiempos de espera se
configuran en **Archivo → Configuración → Escaneo**.

## Configuración IP

En la tarjeta **Red**: DHCP, IP manual, IPs del adaptador (secundarias) y
**Perfiles** (tus configuraciones guardadas). "Config. anterior" vuelve a la última
configuración. Si un cambio falla, se revierte solo. Requiere Administrador.

## Sesiones

- **Nueva sesión**: protocolo (SSH, SFTP, Telnet, FTP, RDP, VNC, HTTP/HTTPS), equipo,
  puerto, usuario y carpeta. Doble clic en el panel izquierdo la abre.
- **Conexión rápida**: escribí `usuario@equipo:puerto` o `ssh://equipo` y Enter.
- **En esta PC**: PowerShell, CMD, Git Bash y tus distribuciones WSL, detectadas solas.
- **SSH + SFTP**: la pestaña SSH trae el explorador de archivos al lado, sobre la misma
  conexión; podés trabajar en los dos a la vez.
- **MultiExec**: lo que escribís en una terminal con MultiExec activo se envía a todas las
  que lo tengan activo.

### Credenciales

La primera vez se pide usuario y contraseña. Si la conexión funciona, se guardan
cifradas y la próxima vez se completan solas (también para otras sesiones al mismo
equipo). Si la contraseña cambió, se vuelve a pedir y se actualiza. Se administran en
**Archivo → Credenciales guardadas** (Ctrl+K), donde también elegís si guardar siempre,
preguntar o nunca.

Las claves de host SSH desconocidas se muestran para confirmar antes de conectar.

## Explorador de archivos (SFTP / FTP / WSL)

- Doble clic entra a una carpeta; `..` sube un nivel. La barra de ruta acepta pegar rutas.
- Arrastrá archivos desde el explorador del sistema para subirlos.
- Clic derecho: descargar, abrir, abrir con…, editar, renombrar, permisos (chmod,
  también recursivo), copiar ruta, nueva carpeta, eliminar.
- **Abrir** descarga a una carpeta temporal y vigila el archivo: al guardarlo en tu
  editor, se sube solo.

## Herramientas

Menú **Herramientas**: ping con gráfico, traceroute, Wake-on-LAN, consulta DNS y
calculadora de subredes.

## Atajos

| Acción | Atajo |
|--------|-------|
| Iniciar escaneo | Ctrl+E |
| Nueva sesión | Ctrl+N |
| Terminal local | Ctrl+Shift+T |
| Credenciales guardadas | Ctrl+K |
| Configuración | Ctrl+, |
| Panel de sesiones | F9 |
| Registro de actividad | Ctrl+L |
| Inventario | Ctrl+I |
| Acerca de | F1 |
| Salir | Ctrl+Q |

## Privacidad

NetworkTool no envía datos a ningún servidor propio. Solo sale a internet para
actualizar la base de fabricantes (Wireshark / IEEE) y, si una MAC no está en la base
local, para consultar su fabricante en api.macvendors.com.
