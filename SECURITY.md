# Seguridad

## Versiones con soporte

Solo la última versión publicada en [Releases](../../releases) recibe correcciones.

## Cómo reportar una vulnerabilidad

No abras un *issue* público. Usá **Security → Report a vulnerability** (aviso privado
de GitHub) en este repositorio, o escribí a
`89585806+EstebanKZL@users.noreply.github.com`.

Incluí la versión, el sistema operativo, los pasos para reproducirlo y el impacto que
ves. La respuesta inicial llega dentro de los 7 días.

## Cómo protege tus datos NetworkTool

- **Contraseñas**: solo en `vault.json`, cifradas con DPAPI (Windows, ligadas a tu usuario)
  o Fernet (Linux/macOS). Nunca en `sessions.json` ni en el registro.
- **SSH**: las claves de host desconocidas se muestran para confirmar; las aceptadas se
  guardan en `known_hosts` de la carpeta de datos y un cambio de clave se rechaza.
- **Red**: el programa no envía datos a servidores propios. Las consultas a internet
  son la descarga de la base de fabricantes y, para MACs que no están en ella, la
  consulta a api.macvendors.com (que recibe esa MAC).
  Los certificados se verifican siempre, salvo al leer páginas de equipos de la red local
  (cámaras, routers) que usan certificados propios.
- **Permisos**: abre como usuario normal; pide Administrador solo para cambiar la IP.
