"""
Descarga automática del Perfil de Carga (Excel) desde Optimum.SM (ANDE).

Flujo que replica:
  1. Login en http://10.1.0.126/optimum/login.php
  2. C&I > Perfil de Carga > Consulta Perfil (perfilGrafico.php?m=2)
  3. Clientes: clic en el ícono del grupito -> "Todos"
  4. Dispositivo: "Punto de Medida"
  5. Fecha desde: 1er día del mes actual / Fecha hasta: hoy
  6. Tipo: "Tabla"
  7. Punto de Medida: NIS
  8. Medidor: el que empieza con "EGM"
  9. Log: "Todos"
 10. Canal: "Sum Li Active Power + (QI+QIV) (last average 1)- 0 x"
 11. Aplicar -> ícono de Excel -> descarga

Requisitos (una sola vez):
    pip install playwright
    # Si usás el Chrome ya instalado (NAVEGADOR = "chrome") no hace falta nada más.
    # Si no tenés Chrome, usá NAVEGADOR = None y ejecutá:
    #   playwright install chromium

Uso:
    python descargar_perfil_carga.py

Credenciales: el usuario se configura en USUARIO (abajo). La contraseña se toma
del Administrador de credenciales de Windows (la misma que usa el script del MDC:
servicio "Automatismo_Telemedicion", clave "optimum"). Si todavía no existe, se
pide una sola vez en una ventanita y queda guardada.
Si cambiás la contraseña de Optimum, poné OLVIDAR_CLAVE = True una vez.

Requiere además: pip install keyring

Si algún paso falla, se guarda en la carpeta ./debug una captura (.png) y el
HTML de la página (.html) para poder ajustar los selectores.
"""

import asyncio
import getpass
import os
import re
import sys
import threading
import time
import traceback
from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

# =============================================================================
# CONFIGURACIÓN — editá esto
# =============================================================================
PUNTO_DE_MEDIDA = "1234567"          # <-- poné acá el NIS a probar

USUARIO = "asu06419"                 # usuario de Optimum

# Contraseña guardada en el Administrador de credenciales de Windows
# (los mismos nombres que el script del MDC, así se comparte la credencial)
SERVICIO_CREDENCIAL = "Automatismo_Telemedicion"
CLAVE_CREDENCIAL = "optimum"
OLVIDAR_CLAVE = False                # True = borra la guardada y la vuelve a pedir

BASE_URL = "http://10.1.0.126/optimum"
SERVIDOR = "LOCAL (LOCAL)"           # combo del login
EMPRESA = "ANDE"                     # último campo del login

DISPOSITIVO = "Punto de Medida"
TIPO = "Tabla"
MEDIDOR_PREFIJO = "EGM"
LOG = "Todos"
CANAL = "Sum Li Active Power + (QI+QIV) (last average 1)- 0 x"

CARPETA_DESCARGAS = Path(__file__).resolve().parent / "descargas"
CARPETA_DEBUG = Path(__file__).resolve().parent / "debug"

NAVEGADOR = "chrome"   # "chrome" usa el Chrome instalado; "msedge" para Edge; None = Chromium de Playwright
HEADLESS = False       # False = ves el navegador mientras trabaja (ideal para probar)
LENTITUD_MS = 150      # pausa entre acciones (ms); subilo si la página es lenta
TIMEOUT_MS = 30_000    # espera máxima por elemento
PAUSA_SI_FALLA_S = 60  # si algo falla, deja el navegador abierto este tiempo para mirar
# =============================================================================


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def normalizar(texto):
    """Minúsculas y espacios colapsados, para comparar textos de opciones."""
    return re.sub(r"\s+", " ", (texto or "")).strip().lower()


def guardar_debug(page, nombre):
    CARPETA_DEBUG.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    png = CARPETA_DEBUG / f"{stamp}_{nombre}.png"
    html = CARPETA_DEBUG / f"{stamp}_{nombre}.html"
    try:
        page.screenshot(path=str(png), full_page=True)
        html.write_text(page.content(), encoding="utf-8")
        log(f"   Debug guardado: {png.name} / {html.name}")
    except Exception as e:  # noqa: BLE001
        log(f"   No se pudo guardar debug: {e}")


# -----------------------------------------------------------------------------
# Localizadores por texto de etiqueta (no dependemos de ids que no conocemos)
# -----------------------------------------------------------------------------
def _xpath_etiqueta(texto):
    """Elemento cuyo texto propio empieza con `texto` (label, span, div, td...)."""
    return (
        "//*[self::label or self::span or self::div or self::td or self::th or self::b or self::strong]"
        f"[starts-with(normalize-space(text()), '{texto}')]"
    )


def control_despues_de(page, etiqueta, tag="select"):
    """Primer <select>/<input> que aparece después de la etiqueta visible."""
    etiquetas = page.locator(f"xpath={_xpath_etiqueta(etiqueta)}")
    etiquetas.first.wait_for(state="attached", timeout=TIMEOUT_MS)
    elegida = etiquetas.first
    for i in range(etiquetas.count()):
        if etiquetas.nth(i).is_visible():
            elegida = etiquetas.nth(i)
            break
    return elegida.locator(f"xpath=following::{tag}[1]")


def seleccionar(page, etiqueta, texto, modo="exacto"):
    """
    Selecciona una opción de un <select> ubicado tras `etiqueta`.
    modo: "exacto" | "empieza" | "contiene"
    Funciona aunque el select esté oculto por un plugin (select2/chosen/bootstrap-select).
    """
    sel = control_despues_de(page, etiqueta, "select")
    objetivo = normalizar(texto)

    def buscar():
        for op in sel.locator("option").all():
            t = normalizar(op.inner_text())
            if (modo == "exacto" and t == objetivo) or \
               (modo == "empieza" and t.startswith(objetivo)) or \
               (modo == "contiene" and objetivo in t):
                return op.evaluate("o => o.value"), op.inner_text().strip()
        return None, None

    # Las opciones pueden cargarse por AJAX: reintentamos hasta TIMEOUT_MS.
    limite = time.time() + TIMEOUT_MS / 1000
    valor, visible = buscar()
    while valor is None and time.time() < limite:
        time.sleep(0.5)
        valor, visible = buscar()
    if valor is None:
        opciones = [o.inner_text().strip() for o in sel.locator("option").all()]
        raise RuntimeError(f"No encontré '{texto}' en '{etiqueta}'. Opciones: {opciones}")

    try:
        sel.select_option(value=valor, timeout=3000)
    except Exception:  # select oculto por un plugin -> lo forzamos por JS
        sel.evaluate(
            """(el, v) => {
                el.value = v;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                if (window.jQuery) { window.jQuery(el).val(v).trigger('change'); }
            }""",
            valor,
        )
    log(f"   {etiqueta}: {visible}")
    page.wait_for_timeout(LENTITUD_MS * 3)


def poner_fecha(page, etiqueta, valor_iso):
    """Escribe una fecha YYYY-MM-DD (aunque el input sea readonly / datepicker)."""
    inp = control_despues_de(page, etiqueta, "input")
    inp.evaluate(
        """(el, v) => {
            el.removeAttribute('readonly');
            el.value = v;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            if (window.jQuery) {
                const $el = window.jQuery(el);
                try { if ($el.datepicker) $el.datepicker('update', v); } catch (e) {}
                $el.val(v).trigger('change');
            }
        }""",
        valor_iso,
    )
    page.keyboard.press("Escape")  # cierra el calendario si se abrió
    log(f"   {etiqueta}: {valor_iso}")


# -----------------------------------------------------------------------------
# Pasos
# -----------------------------------------------------------------------------
def login(page, usuario, clave):
    """Mismo método que el script del MDC (probado en el sitio real)."""
    log("1) Login")
    page.goto(f"{BASE_URL}/login.php", wait_until="domcontentloaded")

    combo = page.locator("select:visible").first
    if combo.count():
        try:
            combo.select_option(label=SERVIDOR, timeout=3000)
        except Exception:
            pass  # suele venir preseleccionado

    # Solo campos VISIBLES: el login tiene campos ocultos que confunden.
    textos = page.locator('input[type="text"]:visible, input:not([type]):visible')
    claves = page.locator('input[type="password"]:visible')
    if textos.count() < 2 or claves.count() < 1:
        raise RuntimeError(
            f"No encontré los campos del login (texto={textos.count()}, password={claves.count()})"
        )
    textos.nth(0).fill(usuario)      # 1er campo visible = usuario
    claves.first.fill(clave)         # contraseña
    textos.nth(1).fill(EMPRESA)      # 2do campo visible = empresa

    boton = page.get_by_text("Ingresar", exact=True)
    if boton.count() == 0:
        boton = page.locator('input[type="submit"]:visible')
    if boton.count() == 0:
        raise RuntimeError("No se encontró el botón Ingresar.")
    boton.first.click()

    try:
        page.wait_for_url(lambda url: "login.php" not in url, timeout=TIMEOUT_MS)
    except PWTimeout:
        raise RuntimeError(
            "Seguimos en login.php: ¿contraseña incorrecta? "
            "Si la cambiaste, poné OLVIDAR_CLAVE = True y ejecutá de nuevo."
        )
    page.wait_for_load_state("domcontentloaded")
    log(f"   Login OK ({page.url})")


def abrir_consulta_perfil(page):
    log("2) Abriendo Consulta Perfil")
    page.goto(f"{BASE_URL}/perfilGrafico.php?m=2", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")


def clientes_todos(page):
    log("3) Clientes -> Todos")
    etq = page.locator(f"xpath={_xpath_etiqueta('Clientes')}").first
    icono = etq.locator(
        "xpath=.//i | following-sibling::i[1] | .//span[contains(@class,'fa')]"
    ).first
    if not icono.count():
        icono = page.locator("i.fa-users, i.fa-group, .fa-users, .fa-group").first
    icono.click()
    page.wait_for_timeout(LENTITUD_MS * 4)

    inp = control_despues_de(page, "Clientes", "input")
    if "todos" not in normalizar(inp.input_value()):
        # Algunos sistemas abren un menú/modal con la opción "Todos"
        opcion = page.get_by_text(re.compile(r"^\s*Todos\s*$", re.I)).first
        if opcion.count() and opcion.is_visible():
            opcion.click()
            page.wait_for_timeout(LENTITUD_MS * 3)
    log(f"   Clientes: {inp.input_value() or '(vacío?)'}")


def ingresar_nis(page, nis):
    log(f"7) Punto de Medida: {nis}")
    inp = control_despues_de(page, "Punto de", "input")
    inp.click()
    inp.fill("")
    inp.type(str(nis), delay=80)  # tipeo lento para disparar el autocompletado

    # Si aparece una lista de sugerencias, elegimos la que contiene el NIS.
    sugerencias = page.locator(
        ".ui-autocomplete li:visible, .tt-menu .tt-suggestion:visible, "
        ".typeahead li:visible, .autocomplete-suggestion:visible, "
        ".select2-results li:visible, .easy-autocomplete-container li:visible"
    )
    try:
        sugerencias.first.wait_for(state="visible", timeout=4000)
        objetivo = sugerencias.filter(has_text=str(nis)).first
        (objetivo if objetivo.count() else sugerencias.first).click()
    except PWTimeout:
        inp.press("Enter")
        inp.press("Tab")
    page.wait_for_timeout(LENTITUD_MS * 4)


def aplicar(page):
    log("11) Aplicar")
    boton = page.get_by_role("button", name=re.compile(r"Aplicar|Graficar", re.I)).or_(
        page.locator("input[type=submit][value*='Aplicar' i], input[type=button][value*='Aplicar' i], "
                     "a:has-text('Aplicar')")
    ).first
    boton.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def descargar_excel(page, nis):
    log("12) Descargando Excel")
    # En orden de prioridad: el primero es el que funciona en la pantalla de Medidores.
    selectores = [
        '[title*="Exportar"]:visible',
        'a:has(img[src*="xls" i]):visible',
        'a:has(img[src*="excel" i]):visible',
        '[title*="Excel" i]:visible',
        '.buttons-excel:visible',
        'a:has(.fa-file-excel-o):visible, a:has(.fa-file-excel):visible, '
        'button:has(.fa-file-excel-o):visible, button:has(.fa-file-excel):visible',
        'img[src*="xls" i]:visible, img[src*="excel" i]:visible',
        '[onclick*="xls" i]:visible, [onclick*="excel" i]:visible',
    ]
    excel = None
    limite = time.time() + TIMEOUT_MS * 2 / 1000   # la tabla puede tardar en cargar
    while excel is None and time.time() < limite:
        for css in selectores:
            loc = page.locator(css)
            if loc.count():
                excel = loc.first
                log(f"   Botón Excel encontrado con: {css}")
                break
        else:
            time.sleep(1)
    if excel is None:
        raise RuntimeError("No encontré el botón de Exportar / Excel.")

    with page.expect_download(timeout=TIMEOUT_MS * 4) as info:
        excel.click()
    descarga = info.value

    CARPETA_DESCARGAS.mkdir(parents=True, exist_ok=True)
    original = descarga.suggested_filename or "perfil.xlsx"
    extension = Path(original).suffix or ".xlsx"
    destino = CARPETA_DESCARGAS / f"perfil_{nis}_{date.today():%Y%m%d}{extension}"
    descarga.save_as(str(destino))
    log(f"   Guardado en: {destino}")
    return destino


def abrir_navegador(p):
    """Prueba Chrome instalado, luego Edge (siempre está en Windows), luego Chromium de Playwright."""
    canales = []
    for c in (NAVEGADOR, "chrome", "msedge", None):
        if c not in canales:
            canales.append(c)
    errores = []
    for canal in canales:
        opciones = {"headless": HEADLESS, "slow_mo": LENTITUD_MS}
        if canal:
            opciones["channel"] = canal
        nombre = canal or "chromium (playwright)"
        try:
            log(f"   Abriendo navegador: {nombre}")
            return p.chromium.launch(**opciones)
        except Exception as e:  # noqa: BLE001
            primera_linea = str(e).strip().splitlines()[0] if str(e).strip() else repr(e)
            log(f"   No se pudo abrir {nombre}: {primera_linea}")
            errores.append(f"{nombre}: {primera_linea}")
    raise RuntimeError("No se pudo abrir ningún navegador:\n  " + "\n  ".join(errores))


def ejecutar_en_hilo(funcion, *args):
    """
    Spyder / Jupyter tienen un bucle asyncio corriendo, y la API sync de Playwright
    no funciona ahí. Ejecutarla en un hilo aparte lo evita (y también funciona
    normal desde la consola de Windows).
    """
    resultado = {}

    def objetivo():
        try:
            if sys.platform.startswith("win"):
                # Playwright necesita el bucle Proactor en Windows para lanzar el navegador.
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            resultado["ok"] = funcion(*args)
        except BaseException as e:  # noqa: BLE001
            resultado["error"] = e
            resultado["traza"] = traceback.format_exc()

    hilo = threading.Thread(target=objetivo, name="playwright", daemon=True)
    hilo.start()
    hilo.join()
    if "error" in resultado:
        print(resultado["traza"], file=sys.stderr, flush=True)
        raise resultado["error"]
    return resultado.get("ok")


def descargar_perfil(nis, usuario, clave):
    hoy = date.today()
    desde = hoy.replace(day=1).isoformat()
    hasta = hoy.isoformat()

    with sync_playwright() as p:
        navegador = abrir_navegador(p)
        contexto = navegador.new_context(accept_downloads=True, viewport={"width": 1600, "height": 900})
        page = contexto.new_page()
        page.set_default_timeout(TIMEOUT_MS)

        paso = "inicio"
        try:
            paso = "login";            login(page, usuario, clave)
            paso = "consulta_perfil";  abrir_consulta_perfil(page)
            paso = "clientes";         clientes_todos(page)
            paso = "dispositivo"
            log("4) Dispositivo");     seleccionar(page, "Dispositivo", DISPOSITIVO)
            paso = "fechas"
            log("5) Fechas")
            poner_fecha(page, "Fecha desde", desde)
            poner_fecha(page, "Fecha hasta", hasta)
            paso = "tipo"
            log("6) Tipo");            seleccionar(page, "Tipo", TIPO)
            paso = "nis";              ingresar_nis(page, nis)
            paso = "medidor"
            log("8) Medidor");         seleccionar(page, "Medidor", MEDIDOR_PREFIJO, modo="empieza")
            paso = "log"
            log("9) Log");             seleccionar(page, "Log", LOG)
            paso = "canal"
            log("10) Canal");          seleccionar(page, "Canal", CANAL, modo="contiene")
            paso = "aplicar";          aplicar(page)
            paso = "excel";            archivo = descargar_excel(page, nis)
            return archivo
        except Exception as e:
            log(f"ERROR en el paso '{paso}': {e}")
            guardar_debug(page, paso)
            if not HEADLESS and PAUSA_SI_FALLA_S:
                log(f"   El navegador queda abierto {PAUSA_SI_FALLA_S} s para que lo revises...")
                page.wait_for_timeout(PAUSA_SI_FALLA_S * 1000)
            raise
        finally:
            contexto.close()
            navegador.close()


def pedir_clave_ventana():
    """Ventanita Tkinter para la contraseña (igual que el script del MDC)."""
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    clave = simpledialog.askstring(
        "Perfil de Carga - optimum.SM",
        f"Usuario: {USUARIO}\n\nIngrese su contraseña:\n\n"
        "Se guardará en el Administrador de credenciales de Windows "
        "para las próximas ejecuciones.",
        show="*",
        parent=root,
    )
    root.destroy()
    return clave


def obtener_clave():
    """Variable OPTIMUM_PASS -> Credential Manager -> ventanita (y se guarda)."""
    if os.environ.get("OPTIMUM_PASS"):
        return os.environ["OPTIMUM_PASS"]

    try:
        import keyring
    except ImportError:
        keyring = None
        log("Aviso: falta 'keyring' (pip install keyring); la contraseña no se guardará.")

    if keyring and OLVIDAR_CLAVE:
        try:
            keyring.delete_password(SERVICIO_CREDENCIAL, CLAVE_CREDENCIAL)
            log("Credencial anterior borrada. Volvé a poner OLVIDAR_CLAVE = False.")
        except Exception:
            pass

    if keyring:
        clave = keyring.get_password(SERVICIO_CREDENCIAL, CLAVE_CREDENCIAL)
        if clave:
            log("✅ Contraseña recuperada del Administrador de credenciales de Windows.")
            return clave

    try:
        clave = pedir_clave_ventana()
    except Exception:  # sin entorno gráfico
        clave = getpass.getpass("Contraseña Optimum: ")
    if not clave:
        raise SystemExit("❌ Operación cancelada: no se ingresó contraseña.")

    if keyring:
        keyring.set_password(SERVICIO_CREDENCIAL, CLAVE_CREDENCIAL, clave)
        log("✅ Contraseña guardada en el Administrador de credenciales de Windows.")
    return clave


def main():
    usuario = USUARIO
    clave = obtener_clave()
    nis = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].strip() else PUNTO_DE_MEDIDA
    log(f"Iniciando descarga para el Punto de Medida {nis}")
    archivo = ejecutar_en_hilo(descargar_perfil, nis, usuario, clave)
    log(f"Listo: {archivo}")


if __name__ == "__main__":
    main()
