# Cómo colaborar

Gracias por querer mejorar NetworkTool. Antes de un cambio grande, abrí un *issue* para
conversarlo.

## Preparar el entorno

```bash
pip install -r requirements-dev.txt
```

```bash
python src/main.py --debug
```

Python 3.9+ con PySide6. La línea de Windows 7 usa Python 3.8 con PySide2: el código
tiene que seguir funcionando ahí (sin sintaxis ni funciones de 3.9+).

## Antes de abrir un Pull Request

```bash
python -m unittest discover -s tests
```

```bash
python -m pyflakes src tests
```

```bash
QT_QPA_PLATFORM=offscreen python tests/smoke_ui.py
```

Los tests no tocan la red real ni la configuración IP: levantan servidores SSH, SFTP y
Telnet locales. El CI los corre con PySide6 y con PySide2 (Python 3.8, 32 bits).

## Estructura

```
src/main.py                  punto de entrada
src/networktool/
  app.py                     arranque, instancia única, --selftest
  common.py                  nombre, versión (lee VERSION), registro, rutas de datos, HTTP
  qt_compat.py               capa PySide6 / PySide2: el ÚNICO lugar que importa Qt
  i18n.py, strings.py        tr("clave") y todos los textos en español e inglés
  settings.py                preferencias (puertos, hilos, tiempos)
  system.py                  comandos del sistema, permisos, clientes externos
  workers.py                 hilos del escaneo, ping, traceroute
  net/                       adaptadores, configuración IP, ARP, servicios, WSL
  data/                      perfiles, sesiones, bóveda de credenciales, inventario
  reports.py, tools.py       informes Excel/PDF, subredes, Wake-on-LAN
  ui/theme.py                sistema de diseño: temas, íconos SVG, stylesheet, componentes
  ui/main_window.py          ventana principal y escáner
  ui/sessions.py             panel de sesiones, editor, credenciales
  ui/terminal.py             terminal (pyte) + SSH (paramiko), Telnet y local (pywinpty)
  ui/filebrowser.py          explorador SFTP / FTP / WSL
  ui/dialogs.py, ui/tools_window.py, ui/widgets.py
tests/                       tests unitarios y prueba de humo de la interfaz
build/                       compilación con Nuitka, instalador (Inno Setup) y AppImage
```

## Reglas de la interfaz

- **Qt solo a través de `networktool.qt_compat`.** Si falta una clase, agregala a
  `_QT_NAMES`. Usar `_exec()`, `_exec_menu()`, `_global_pos()` y `Signal`.
- **Sin colores sueltos:** todo color sale de `THEME["clave"]` (`ui/theme.py`); los dos
  temas tienen las mismas claves. Estilos por `objectName` en el stylesheet global.
- **Espaciado** de la escala `SP` (4/8/12/16/24); íconos de `ICON_SIZE` (16/20/24/40).
- **Botones:** `btnPrimary` (uno por zona), `btnStart` / `btnStop`, `btnSecondary`,
  `btnDanger`, `btnChip` dentro de tablas. Sin emojis ni íconos de `QStyle`: usar
  `icon("nombre")` del catálogo SVG.
- Toda lista o tabla vacía muestra `make_empty_state(texto, ícono)`.
- **Ayuda contextual obligatoria:** todo control interactivo lleva
  `set_help(widget, "clave")` (texto en `tip.clave`).
- Tema e idioma se aplican al reiniciar, nunca en caliente.

## Textos (español / inglés)

- Ningún texto visible escrito en el código: todo pasa por `tr("clave", **params)`.
- Cada clave nueva va en `strings.py` en los **dos** idiomas, con los mismos `{params}`.
- Frases con datos: parámetros con nombre (`tr("log.connected", host=ip)`), nunca
  concatenando pedazos.

## Seguridad y privacidad

- Contraseñas: solo a través de `data/vault.py` (cifradas). Nunca en `sessions.json`,
  en archivos de prueba ni en el registro (`logger.*`).
- Nada de red en el hilo de la interfaz: usar los `QThread` existentes.
- No cambiar la IP sin pasar por `apply_ip_config_async` (pide Administrador, guarda
  historial y revierte si falla).
- No agregar datos personales, de clientes ni funciones de una empresa en particular.

## Versiones y publicación

La versión está **solo** en el archivo `VERSION`. Para publicar: actualizar `VERSION` y
`CHANGELOG.md`, y subir el tag `vX.Y.Z`; GitHub Actions compila todas las plataformas,
prueba cada ejecutable y crea el release con `SHA256SUMS.txt`.
