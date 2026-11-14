# Componentes de terceros

NetworkTool incluye o se apoya en los siguientes proyectos, cuyos autores se
reconocen y cuyas licencias se respetan. Las bibliotecas LGPL se distribuyen como
módulos separados dentro de la carpeta del programa y pueden reemplazarse.

## Incluidos en los ejecutables

| Proyecto | Autor / Origen | Licencia | Texto |
|----------|----------------|----------|-------|
| Qt for Python (PySide6 / PySide2, Shiboken) y Qt | The Qt Company | LGPL-3.0 | [LGPL-3.0.txt](licenses/LGPL-3.0.txt) |
| Python | Python Software Foundation | PSF-2.0 | [Python-PSF-2.0.txt](licenses/Python-PSF-2.0.txt) |
| Nuitka (runtime del compilado) | Kay Hayen y colaboradores | Apache-2.0 | [Apache-2.0.txt](licenses/Apache-2.0.txt) |
| paramiko | Jeff Forcier y colaboradores | LGPL-2.1 | [paramiko-LGPL-2.1.txt](licenses/paramiko-LGPL-2.1.txt) |
| pyte | Sergei Lebedev y colaboradores | LGPL-3.0 | [pyte-LGPL-3.0.txt](licenses/pyte-LGPL-3.0.txt) |
| wcwidth | Jeff Quast | MIT | [wcwidth-MIT.txt](licenses/wcwidth-MIT.txt) |
| cryptography | The Python Cryptographic Authority | Apache-2.0 o BSD-3-Clause | [cryptography-BSD-3-Clause.txt](licenses/cryptography-BSD-3-Clause.txt) |
| bcrypt | The Python Cryptographic Authority | Apache-2.0 | [bcrypt-Apache-2.0.txt](licenses/bcrypt-Apache-2.0.txt) |
| PyNaCl (incluye libsodium, ISC) | The Python Cryptographic Authority | Apache-2.0 | [pynacl-Apache-2.0.txt](licenses/pynacl-Apache-2.0.txt) |
| cffi | Armin Rigo, Maciej Fijalkowski | MIT-0 | [cffi-MIT-0.txt](licenses/cffi-MIT-0.txt) |
| invoke (dependencia de paramiko) | Jeff Forcier | BSD-2-Clause | [invoke-BSD-2-Clause.txt](licenses/invoke-BSD-2-Clause.txt) |
| typing_extensions (solo línea win7) | Python Software Foundation | PSF-2.0 | [Python-PSF-2.0.txt](licenses/Python-PSF-2.0.txt) |
| psutil | Giampaolo Rodolà y colaboradores | BSD-3-Clause | [psutil-BSD-3-Clause.txt](licenses/psutil-BSD-3-Clause.txt) |
| openpyxl | Eric Gazoni, Charlie Clark | MIT | [openpyxl-MIT.txt](licenses/openpyxl-MIT.txt) |
| et_xmlfile | Eric Gazoni, Charlie Clark | MIT | [et_xmlfile-MIT.txt](licenses/et_xmlfile-MIT.txt) |
| pywinpty (solo Windows 10/11) | Spyder IDE | MIT | [pywinpty-MIT.txt](licenses/pywinpty-MIT.txt) |

La GPL-3.0, que la LGPL-3.0 complementa, es el archivo [`LICENSE`](LICENSE) de este proyecto.

## Programas externos que la app puede abrir (no se incluyen)

Escritorio remoto (`mstsc`), visores VNC, VLC, nmap y el navegador web se abren
solo si están instalados en el equipo; NetworkTool no los distribuye.

La base de fabricantes de placas de red (OUI) se descarga, cuando el usuario la actualiza,
de la lista pública de Wireshark o del registro de la IEEE. Si una MAC no está en la base
local, se consulta el servicio público api.macvendors.com.
