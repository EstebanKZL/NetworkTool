"""Idioma de la interfaz: español / inglés.

Todo texto visible pasa por tr("clave"). El idioma se elige en Ver → Idioma, se guarda
con QSettings y se aplica en el próximo inicio (nunca en caliente).
Los textos viven en networktool/strings.py.
"""

from networktool.common import APP_NAME, APP_ORG
from networktool.qt_compat import QLibraryInfo, QLocale, QSettings, QTranslator
from networktool.strings import STRINGS

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶  IDIOMA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LANGUAGES = {"es": "Español", "en": "English"}



def get_lang_code() -> str:
    """Idioma guardado; en el primer inicio, el del sistema (fallback: español)."""
    code = QSettings(APP_ORG, APP_NAME).value("language", "")
    if code not in LANGUAGES:
        code = QLocale.system().name()[:2].lower()
    return code if code in LANGUAGES else "es"


def set_lang_code(code: str) -> None:
    """Guarda el idioma elegido. No se aplica hasta el próximo inicio."""
    QSettings(APP_ORG, APP_NAME).setValue("language", code)


LANG = get_lang_code()


def tr(key: str, **kwargs) -> str:
    """Texto traducido. Si falta en el idioma activo usa español; si falta en ambos,
    muestra la clave (así se nota enseguida en pantalla)."""
    text = STRINGS.get(LANG, {}).get(key) or STRINGS["es"].get(key) or key
    return text.format(**kwargs) if kwargs else text


def tr_opt(key: str) -> str:
    """Como tr(), pero devuelve '' si la clave no existe (para textos opcionales)."""
    return STRINGS.get(LANG, {}).get(key) or STRINGS["es"].get(key) or ""


# Valores internos que devuelven los módulos de red (fijos, en español) → texto visible
_OS_VALUES = {"Conectado": "status.connected", "Desconectado": "status.disconnected",
              "Desconocido": "common.unknown", "Habilitado": "common.yes", "Deshabilitado": "common.no",
              "Sin IP": "common.none", "Sin Máscara": "common.none", "Sin gateway": "common.none"}


def tr_value(value: str) -> str:
    """Traduce un valor interno de los módulos de red; cualquier otro se devuelve igual."""
    key = _OS_VALUES.get(str(value))
    return tr(key) if key else str(value)


def check_translations() -> None:
    """Solo en desarrollo: avisa por consola qué claves faltan en algún idioma."""
    keys = {code: set(d) for code, d in STRINGS.items()}
    all_keys = set().union(*keys.values())
    for code, ks in keys.items():
        for k in sorted(all_keys - ks):
            print(f"[i18n] Falta '{k}' en '{code}'")


def install_qt_translations(app) -> None:
    """Carga las traducciones propias de Qt (botones estándar, diálogos de archivo, menú copiar/pegar)."""
    if LANG == "en":
        return
    try:
        path = (QLibraryInfo.path(QLibraryInfo.TranslationsPath)            # PySide6
                if hasattr(QLibraryInfo, "path")
                else QLibraryInfo.location(QLibraryInfo.TranslationsPath))  # PySide2
        app._qt_translators = []
        for base in ("qtbase", "qt"):
            translator = QTranslator(app)
            if translator.load(f"{base}_{LANG}", path):
                app.installTranslator(translator)
                app._qt_translators.append(translator)
    except Exception as e:
        print(f"[{APP_NAME}] Traducciones de Qt no disponibles: {e}")
