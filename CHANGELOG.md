# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) · Versionado: [SemVer](https://semver.org/lang/es/).

## [7.4.0] - 2026-11-14

Primera versión publicada en GitHub.

### Agregado
- Sesiones remotas integradas en pestañas, al estilo de los clientes de terminal
  profesionales: SSH, Telnet, SFTP y FTP; RDP, VNC y web abren con el cliente del sistema.
- SSH y SFTP en la misma pestaña, sobre la misma conexión, para trabajar en los dos a la vez.
- Terminales locales (PowerShell, CMD, Git Bash) y distribuciones WSL detectadas solas.
- Bóveda de credenciales cifrada (DPAPI en Windows, Fernet en Linux/macOS) con
  autocompletado por sesión o por equipo; política guardar siempre / preguntar / nunca.
- Explorador de archivos remoto: íconos por tipo de archivo, `..`, arrastrar y soltar,
  permisos recursivos, copiar ruta, editar, abrir y "abrir con" con subida automática.
- Conexión rápida (`usuario@equipo:puerto`), MultiExec y botones "Conectar" por servicio
  en la tabla del escáner.
- Puertos a analizar, equipos en paralelo y tiempos de espera configurables.
- Configuración con navegación lateral (General y Escaneo); tema e idioma se eligen ahí.
- Íconos propios en SVG para protocolos, tipos de archivo y estados vacíos.
- Interfaz completa en español e inglés; temas Grafito (oscuro) y Papel (claro).
- Guardado del tamaño de la ventana, divisores y columnas; registro rotativo y captura
  de errores no controlados con detalles.
- Autodiagnóstico sin interfaz: `--selftest informe.json`.

### Cambiado
- Diseño actualizado al sistema de diseño v6.3.
- Los perfiles de IP los crea cada usuario; ya no hay perfiles de fábrica.
- El descubrimiento ARP usa la tabla del sistema y SendARP en Windows: ya no hace falta
  instalar Npcap.
- Sin dependencias de scapy ni requests (HTTP con la biblioteca estándar).

### Quitado
- Envío de correo y funciones específicas de una empresa.

### Versiones de la herramienta
- Compiladas con Nuitka en GitHub Actions, con el formato
  `NetworkTool-<versión>-<os>-<arq>-<variante>`:
  - `win-x64`: Windows 10/11 (Python 3.12 + PySide6).
  - `win7-x64` y `win7-x86`: Windows 7, 8, 10 y 11 (Python 3.8 + PySide2, con la
    Universal CRT incluida). La de 32 bits es también la de Windows 10/11 de 32 bits.
  - Windows: `portable.zip` (carpeta, sin instalar) y `setup.exe` (instalador).
  - Linux: `linux-x86_64.AppImage`.
- Cada ejecutable pasa una prueba de humo (`--selftest`) en GitHub antes de publicarse.
