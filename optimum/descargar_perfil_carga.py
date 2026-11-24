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
     (Actaris ACE6000: "... (time integral 5) - 0", medidor por su número de
     serie o "Todos"; el orquestador toma prefijo y canal de cada suministro)
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
PUNTO_DE_MEDIDA = "1379190"          # NIS del suministro (factor y potencia: ver analisis_perfil.py)
ANALIZAR_AL_DESCARGAR = True         # genera la página web y revisa alertas al terminar

USUARIO = "asu06419"                 # usuario de Optimum

# Contraseña guardada en el Administrador de credenciales de Windows
# (los mismos nombres que el script del MDC, así se comparte la credencial)
SERVICIO_CREDENCIAL = "Automatismo_Telemedicion"
CLAVE_CREDENCIAL = "optimum"
OLVIDAR_CLAVE = False                # True = borra la guardada y la vuelve a pedir

BASE_URL = "http://10.1.0.126/optimum"
ORIGEN_SITIO = re.match(r"https?://[^/]+", BASE_URL).group(0)
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
ESPERA_ANTES_DE_ABRIR_COMBO_S = 6   # si un combo no trae la opción, a los N s se abre con clics
ESPERA_TABLA_S = 180   # máximo para que la tabla termine de cargar tras "Aplicar"
ESPERA_DESCARGA_S = 180  # máximo para que el Excel termine de descargarse
# =============================================================================


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def normalizar(texto):
    """Minúsculas y espacios colapsados, para comparar textos de opciones."""
    return re.sub(r"\s+", " ", (texto or "")).strip().lower()


def compacto(texto):
    """Sin espacios y en minúsculas: 'Power + (QI+QIV) (last average 1)- 0 x' == 'Power+(QI+QIV)(lastaverage1)-0x'."""
    return re.sub(r"\s+", "", (texto or "")).lower()


def regex_flexible(texto):
    """Regex que acepta el texto con cualquier cantidad de espacios entre caracteres."""
    return re.compile(r"\s*".join(re.escape(c) for c in compacto(texto)), re.I)


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
    try:
        log("   ---- Controles del formulario (pasame esto si falla) ----")
        controles = page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('select, input, textarea, button').forEach(el => {
                if (el.type === 'hidden') return;
                const vis = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                const grupo = el.closest('.form-group, .col, [class*="col-"], td, div');
                const etq = el.id && document.querySelector(`label[for="${el.id}"]`);
                const texto = (etq ? etq.innerText : (grupo ? grupo.innerText : '')).trim()
                                .split('\\n')[0].slice(0, 40);
                let det = `${el.tagName.toLowerCase()} id=${el.id || '-'} name=${el.name || '-'}`
                        + ` class=${(el.className || '-').toString().slice(0, 40)}`
                        + ` visible=${vis} etiqueta="${texto}"`;
                if (el.tagName === 'SELECT') {
                    det += ' opciones=' + JSON.stringify([...el.options].slice(0, 12).map(o => o.text.trim()));
                } else if (el.tagName === 'INPUT') {
                    det += ` type=${el.type} value="${(el.value || '').slice(0, 30)}"`;
                } else {
                    det += ` texto="${(el.innerText || el.value || '').trim().slice(0, 30)}"`;
                }
                out.push(det);
            });
            return out;
        }""")
        for c in controles:
            log("   " + c)
    except Exception as e:  # noqa: BLE001
        log(f"   No se pudo guardar debug: {e}")


# -----------------------------------------------------------------------------
# Localizadores por texto de etiqueta (no dependemos de ids que no conocemos)
# -----------------------------------------------------------------------------
def _xpath_etiqueta(texto):
    """
    Elemento (de cualquier tipo: label, p, h5, span...) cuyo texto propio empieza
    con `texto`. Se excluyen opciones de combos y el texto que dibujan los
    widgets select2 (p. ej. el "Punto de Medida" ya elegido en Dispositivo).
    """
    return (
        "//*[not(self::option) and not(self::select) and not(self::script) and not(self::style)"
        " and not(self::button) and not(self::a)"
        " and not(ancestor-or-self::*[contains(@class,'select2')])]"
        f"[text()[starts-with(normalize-space(.), '{texto}')]]"
    )


def control_despues_de(page, etiqueta, tag="select"):
    """Primer <select>/<input> que aparece después de la etiqueta visible."""
    # a) <label for="id"> bien armado -> lo más confiable
    for_ids = page.evaluate(
        """(t) => [...document.querySelectorAll('label[for]')]
                .filter(l => l.innerText.trim().toLowerCase().startsWith(t.toLowerCase()))
                .map(l => l.htmlFor)""",
        etiqueta,
    )
    for fid in for_ids:
        loc = page.locator(f'{tag}[id="{fid}"]')
        if loc.count():
            return loc.first
    # b) el primer control que aparece después del texto de la etiqueta
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
    sel.wait_for(state="attached", timeout=TIMEOUT_MS)
    objetivo = compacto(texto)
    ident = sel.evaluate("el => `${el.id || '-'} / ${el.name || '-'}`")

    def opciones():
        # textContent funciona aunque el select esté oculto (select2)
        return sel.evaluate("el => [...el.options].map(o => [o.value, o.textContent.trim()])")

    def buscar():
        for v, t in opciones():
            n = compacto(t)
            if (modo == "exacto" and n == objetivo) or \
               (modo == "empieza" and n.startswith(objetivo)) or \
               (modo == "contiene" and objetivo in n):
                return v, t
        return None, None

    # Las opciones pueden cargarse por AJAX: reintentamos hasta TIMEOUT_MS.
    # Si a los pocos segundos el <select> sigue sin la opción, probablemente el
    # combo carga sus opciones recién al abrirlo (select2 con AJAX, como Canal):
    # en ese caso lo abrimos y elegimos con clics, como lo haría una persona.
    inicio = time.time()
    limite = inicio + TIMEOUT_MS / 1000
    probado_ui = False
    valor, visible = buscar()
    while valor is None and time.time() < limite:
        if not probado_ui and time.time() - inicio > ESPERA_ANTES_DE_ABRIR_COMBO_S:
            probado_ui = True
            if seleccionar_con_clics(page, etiqueta, texto):
                return
        time.sleep(0.5)
        valor, visible = buscar()
    if valor is None and not probado_ui and seleccionar_con_clics(page, etiqueta, texto):
        return
    if valor is None:
        lista = [t for _, t in opciones()]
        raise RuntimeError(f"No encontré '{texto}' en '{etiqueta}' (select {ident}). Opciones: {lista}")

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


def etiqueta_visible(page, etiqueta):
    etiquetas = page.locator(f"xpath={_xpath_etiqueta(etiqueta)}")
    for i in range(etiquetas.count()):
        if etiquetas.nth(i).is_visible():
            return etiquetas.nth(i)
    return etiquetas.first


def seleccionar_con_clics(page, etiqueta, texto):
    """Abre el combo visible que está tras la etiqueta, busca el texto y hace clic en el resultado."""
    log(f"   {etiqueta}: el combo no trae la opción cargada; lo abro y la busco con clics...")
    try:
        etq = etiqueta_visible(page, etiqueta)
        posibles = etq.locator(
            "xpath=following::*[contains(concat(' ', normalize-space(@class), ' '), ' select2-selection ')"
            " or contains(concat(' ', normalize-space(@class), ' '), ' select2-choices ')"
            " or contains(concat(' ', normalize-space(@class), ' '), ' select2-choice ')"
            " or (self::input and not(@type='hidden') and not(@type='checkbox'))"
            " or self::select]"
        )
        widget = None
        for i in range(min(posibles.count(), 6)):   # el primero VISIBLE tras la etiqueta
            if posibles.nth(i).is_visible():
                widget = posibles.nth(i)
                break
        if widget is None:
            raise RuntimeError("no encontré el combo visible")
        widget.click()
        page.wait_for_timeout(500)

        # Escribimos las primeras palabras para filtrar (si el combo tiene buscador).
        palabras = " ".join(texto.split()[:3])
        page.keyboard.type(palabras, delay=60)

        # Para reconocer la opción alcanza con la parte "fuerte" del texto
        # (hasta el último paréntesis): "Sum Li Active Power + (QI+QIV) (last average 1)".
        # Así no importa si al final dice "- 0", "- 0 x" o tiene otros espacios.
        clave = texto[: texto.rfind(")") + 1] if ")" in texto else texto
        patron = regex_flexible(clave)

        estrategias = [
            ("lista del combo", page.locator(
                ".select2-results__option:visible, .select2-result:visible, .select2-results li:visible, "
                ".ui-menu-item:visible, .dropdown-menu li:visible, .dropdown-item:visible, "
                ".chosen-results li:visible, .tt-suggestion:visible, .autocomplete-suggestion:visible, "
                "[class*='dropdown'] li:visible, [class*='token'] li:visible, [role=option]:visible"
            ).filter(has_text=patron)),
            ("texto visible", page.get_by_text(patron)),
        ]
        limite = time.time() + 15
        while time.time() < limite:
            for nombre, loc in estrategias:
                for i in range(min(loc.count(), 10)):
                    item = loc.nth(i)
                    if not item.is_visible():
                        continue
                    elegido = item.inner_text().strip()
                    # Muchos combos escuchan el clic en el <a> de adentro, no en el <li>.
                    interno = item.locator("a:visible")
                    (interno.first if interno.count() else item).click()
                    page.wait_for_timeout(LENTITUD_MS * 3 + 500)
                    log(f"   {etiqueta}: {elegido}  (por {nombre})")
                    return True
            page.wait_for_timeout(500)

        # Último recurso: elegir la primera sugerencia con el teclado.
        log(f"   {etiqueta}: no reconocí la opción en la lista; pruebo con flecha abajo + Enter")
        guardar_debug(page, f"{etiqueta}_lista")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.wait_for_timeout(LENTITUD_MS * 3 + 500)
        return True
    except Exception as e:  # noqa: BLE001
        log(f"   No pude elegirlo con clics: {str(e).splitlines()[0]}")
        page.keyboard.press("Escape")
        return False


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

    # El campo es un select2: al elegir "Todos" aparece la etiqueta "×Todos".
    chip = page.locator(".select2-selection__choice:visible, .select2-search-choice:visible")
    if chip.filter(has_text=re.compile("Todos", re.I)).count():
        log("   Clientes: Todos")
        return
    try:
        inp = control_despues_de(page, "Clientes", "input")
        if "todos" in normalizar(inp.input_value()):
            log("   Clientes: Todos")
            return
    except Exception:
        pass
    opcion = page.get_by_text(re.compile(r"^\s*Todos\s*$", re.I)).first
    if opcion.count() and opcion.is_visible():
        opcion.click()
        page.wait_for_timeout(LENTITUD_MS * 3)
    log("   Clientes: (no pude confirmar 'Todos', sigo igual)")


def ingresar_nis(page, nis):
    log(f"7) Punto de Medida: {nis}")
    inp = control_despues_de(page, "Punto de", "input")
    inp.click()
    inp.fill("")
    inp.type(str(nis), delay=80)  # tipeo lento para disparar el autocompletado

    # Si aparece una lista de sugerencias, elegimos la que contiene el NIS.
    sugerencias = page.locator(
        ".select2-results__option:not(.select2-results__message):not(.loading-results):visible, "
        ".select2-results li.select2-result-selectable:visible, "
        ".ui-autocomplete li:visible, .tt-menu .tt-suggestion:visible, "
        ".typeahead li:visible, .autocomplete-suggestion:visible, "
        ".easy-autocomplete-container li:visible"
    ).filter(has_text=str(nis))
    try:
        sugerencias.first.wait_for(state="visible", timeout=10_000)
        log(f"   Sugerencia: {sugerencias.first.inner_text().strip()}")
        sugerencias.first.click()
    except PWTimeout:
        log("   No apareció lista de sugerencias; confirmo con Enter")
        inp.press("Enter")
        inp.press("Tab")
    page.wait_for_timeout(LENTITUD_MS * 4)


def aplicar(page):
    log("11) Aplicar")
    boton = None
    for nombre in ("Aplicar", "Graficar"):
        cand = page.locator(
            f"button:visible:has-text('{nombre}'), a:visible:has-text('{nombre}'), "
            f"input[type=submit][value*='{nombre}' i]:visible, input[type=button][value*='{nombre}' i]:visible"
        )
        if cand.count():
            boton = cand.first
            break
    if boton is None:
        raise RuntimeError("No encontré el botón Aplicar / Graficar.")
    log(f"   Botón: {boton.inner_text().strip() or boton.get_attribute('value')}")
    boton.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def descargar_excel(page, nis, etiqueta=None):
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
    limite = time.time() + ESPERA_TABLA_S   # la tabla puede tardar en cargar
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

    # Las descargas se capturan aunque salgan de una pestaña nueva, y los avisos
    # tipo "¿Desea descargar...?" se aceptan solos (ver descargar_perfil).
    recibidas = page.context._descargas_recibidas
    recibidas.clear()
    excel.click()

    limite = time.time() + ESPERA_DESCARGA_S
    while not recibidas and time.time() < limite:
        page.wait_for_timeout(500)
    if not recibidas:
        raise RuntimeError(f"Hice clic en Excel pero no llegó ninguna descarga en {ESPERA_DESCARGA_S} s.")
    page.wait_for_timeout(3000)   # por si el sitio dispara más de un archivo

    CARPETA_DESCARGAS.mkdir(parents=True, exist_ok=True)
    guardados = []
    for i, descarga in enumerate(list(recibidas), start=1):
        original = descarga.suggested_filename or "perfil.xlsx"
        extension = Path(original).suffix or ".xlsx"
        sufijo = "" if i == 1 else f"_{i}"
        etiqueta = etiqueta or f"{date.today():%Y%m%d}"
        destino = CARPETA_DESCARGAS / f"perfil_{nis}_{etiqueta}{sufijo}{extension}"
        falla = descarga.failure()   # espera a que termine; None = OK
        if falla:
            log(f"   La descarga '{original}' falló: {falla}")
            continue
        descarga.save_as(str(destino))
        log(f"   Guardado en: {destino}  (nombre original: {original})")
        guardados.append(destino)
    if not guardados:
        raise RuntimeError("La descarga del Excel falló (ver mensajes arriba).")
    return guardados[0]


def abrir_navegador(p):
    """Prueba Chrome instalado, luego Edge (siempre está en Windows), luego Chromium de Playwright."""
    canales = []
    for c in (NAVEGADOR, "chrome", "msedge", None):
        if c not in canales:
            canales.append(c)
    errores = []
    for canal in canales:
        opciones = {"headless": HEADLESS, "slow_mo": LENTITUD_MS}
        opciones["args"] = [
            # El sitio es http:// y Chrome frena las descargas "no seguras" (la flechita
            # de arriba a la derecha que había que tocar). Así las deja pasar directo.
            f"--unsafely-treat-insecure-origin-as-secure={ORIGEN_SITIO}",
            "--disable-features=InsecureDownloadWarnings,DownloadBubble,DownloadBubbleV2",
        ]
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


def descargar_perfil(nis, usuario, clave, desde=None, hasta=None, etiqueta=None):
    """Por defecto: del 1° del mes actual a hoy. `desde`/`hasta` en formato YYYY-MM-DD."""
    hoy = date.today()
    desde = desde or hoy.replace(day=1).isoformat()
    hasta = hasta or hoy.isoformat()
    log(f"   Período: {desde} a {hasta}")

    with sync_playwright() as p:
        navegador = abrir_navegador(p)
        contexto = navegador.new_context(accept_downloads=True, viewport={"width": 1600, "height": 900})

        # Capturar descargas de cualquier pestaña y aceptar avisos JS (confirm/alert).
        contexto._descargas_recibidas = []

        def vigilar(pg):
            if getattr(pg, "_vigilada", False):
                return
            pg._vigilada = True
            pg.on("download", lambda d: (log(f"   Descarga iniciada: {d.suggested_filename}"),
                                         contexto._descargas_recibidas.append(d)))
            pg.on("dialog", lambda dlg: (log(f"   Aviso del sitio aceptado: {dlg.message[:80]}"),
                                         dlg.accept()))

        contexto.on("page", vigilar)
        page = contexto.new_page()
        vigilar(page)
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
            paso = "excel";            archivo = descargar_excel(page, nis, etiqueta)
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


def obtener_clave(interactivo=True):
    """
    Variable OPTIMUM_PASS -> Credential Manager -> ventanita (y se guarda).
    Con interactivo=False (tarea programada) nunca pregunta: si falta, da error.
    """
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

    if not interactivo:
        raise RuntimeError(
            "No hay contraseña de Optimum guardada. Ejecutá una vez: "
            "python orquestador_diario.py --configurar"
        )
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

    if ANALIZAR_AL_DESCARGAR:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import analisis_perfil
        analisis_perfil.procesar(archivo, nis)


if __name__ == "__main__":
    main()
