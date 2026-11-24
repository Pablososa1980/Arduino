"""
Orquestador diario: Optimum.SM -> panel web (Hostinger, PHP + MySQL).

Qué hace cada vez que corre (pensado para el Programador de tareas de Windows):
  1. Le pide al panel web la lista de suministros activos (se agregan desde el
     panel: no hace falta tocar este script).
  2. Para cada uno descarga de Optimum el Perfil de Carga del mes actual
     (del 1° a hoy), sin mostrar el navegador.
  3. Los días 1 a DIAS_RELLENO de cada mes, además, vuelve a bajar el mes
     anterior completo, para que no se pierda la "cola" final del mes.
  4. Envía las lecturas al panel por HTTPS con curl.exe, que atraviesa el proxy
     corporativo con la sesión de Windows (mismo método que el panel SEP2).
     El panel calcula los kW, guarda el histórico y manda las alertas por correo.
  5. Deja un registro en logs/ y termina con código 0 (OK) o 1 (hubo errores).

Primera vez (una sola vez, a mano):
    python orquestador_diario.py --configurar
  Guarda en el Administrador de credenciales de Windows la contraseña de
  Optimum y el token de la API (se genera en el panel > Tokens) y prueba la conexión.

Otras opciones:
    python orquestador_diario.py --sin-subir             # descarga pero no envía
    python orquestador_diario.py --sin-descargar         # reenvía el último Excel ya bajado
    python orquestador_diario.py --mes 2026-10           # carga un mes pasado completo (histórico)
    python orquestador_diario.py --nis 1379190           # solo ese suministro
    python orquestador_diario.py --archivo X.xlsx --nis 1379190   # envía un Excel bajado a mano
    python orquestador_diario.py --crear-tarea [HH:MM]   # crea la tarea diaria de Windows
"""

import argparse
import calendar
import re
import getpass
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA))

import analisis_perfil as ap          # noqa: E402  (lectura del Excel de Optimum)
import descargar_perfil_carga as dp   # noqa: E402  (automatización de Optimum)

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
WEB = {
    "url_base": "https://velilla.monitorkw.com",   # dirección del panel, sin barra final
    # El token de la API se guarda en el Administrador de credenciales de Windows:
    "servicio_credencial": "Automatismo_Telemedicion",
    "clave_credencial": "potencia_api_token",
    "timeout_s": 180,
    "intentos": 3,
}
DIAS_RELLENO = 5                     # días 1..N: también se reenvía el mes anterior completo
REINTENTOS_DESCARGA = 2              # reintentos por suministro si Optimum falla
VENTANA_ALERTA_AL_FINAL = True       # aviso en la PC si el panel detectó alertas nuevas
CARPETA_LOGS = CARPETA / "logs"
GUARDAR_LOGS_DIAS = 60
NOMBRE_TAREA = "Optimum - Perfil de Carga diario"
# =============================================================================

# Corrida a mano (botón Ejecutar del editor o consola): si falta el token o la
# contraseña, se piden en una ventanita. La tarea programada usa --auto y nunca
# pregunta nada (si falta algo, deja el error en el log y termina).
MODO_INTERACTIVO = True


# -----------------------------------------------------------------------------
# Registro (pantalla + archivo)
# -----------------------------------------------------------------------------
class _Tee(io.TextIOBase):
    def __init__(self, *destinos):
        self.destinos = destinos

    def write(self, s):
        for d in self.destinos:
            try:
                d.write(s)
                d.flush()
            except Exception:
                pass
        return len(s)

    def flush(self):
        for d in self.destinos:
            try:
                d.flush()
            except Exception:
                pass


def iniciar_log():
    CARPETA_LOGS.mkdir(parents=True, exist_ok=True)
    archivo = CARPETA_LOGS / f"orquestador_{date.today():%Y-%m-%d}.log"
    f = open(archivo, "a", encoding="utf-8")
    sys.stdout = _Tee(sys.__stdout__, f) if sys.__stdout__ else f
    sys.stderr = _Tee(sys.__stderr__, f) if sys.__stderr__ else f
    limite = time.time() - GUARDAR_LOGS_DIAS * 86400
    for viejo in CARPETA_LOGS.glob("orquestador_*.log"):
        if viejo.stat().st_mtime < limite:
            viejo.unlink(missing_ok=True)
    return archivo


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# -----------------------------------------------------------------------------
# Credenciales
# -----------------------------------------------------------------------------
def _keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        raise SystemExit("Falta 'keyring':  pip install keyring")


def token_api(interactivo=False):
    if os.environ.get("POTENCIA_API_TOKEN"):
        return os.environ["POTENCIA_API_TOKEN"].strip()
    kr = _keyring()
    token = kr.get_password(WEB["servicio_credencial"], WEB["clave_credencial"])
    if token:
        return token
    if not (interactivo or MODO_INTERACTIVO):
        raise RuntimeError("No hay token de la API guardado. Ejecutá: python orquestador_diario.py --configurar")
    crudo = pedir_token_ventana() or ""
    # El token solo tiene letras, números, "-" y "_": se descarta todo lo demás
    # (espacios, saltos de línea o el carácter invisible que deja un Ctrl+V fallido).
    token = re.sub(r"[^A-Za-z0-9_-]", "", crudo)
    if not token:
        raise SystemExit("Cancelado: no se recibió ningún token.")
    log(f"   Token recibido: {len(token)} caracteres (termina en ...{token[-4:]})"
        + ("" if len(token) == 43 else "  ⚠️ los tokens del panel tienen 43: puede haberse copiado mal"))
    kr.set_password(WEB["servicio_credencial"], WEB["clave_credencial"], token)
    log("✅ Token guardado en el Administrador de credenciales de Windows.")
    return token


def pedir_token_ventana():
    """Ventanita para pegar el token (si no hay entorno gráfico, lo pide por consola)."""
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        token = simpledialog.askstring(
            "Panel de Potencia - token de la API",
            "Pegá el token que generaste en el panel\n(menú Tokens > Generar token).\n\n"
            "Se guarda en el Administrador de credenciales de Windows\ny no se vuelve a pedir.",
            show="*", parent=root)
        root.destroy()
        return token
    except Exception:
        # Sin ventana: se pide por consola de forma visible, para que se vea si el pegado funcionó
        # (en la consola de Windows, si Ctrl+V no pega, usá clic derecho).
        print("Pegá el token de la API (panel > Tokens) con clic derecho o Ctrl+V y apretá Enter.")
        return input("Token: ")


def configurar():
    log("Configuración inicial")
    kr = _keyring()
    if kr.get_password(dp.SERVICIO_CREDENCIAL, dp.CLAVE_CREDENCIAL):
        log("✅ La contraseña de Optimum ya está guardada (la misma del script del MDC).")
    else:
        dp.obtener_clave(interactivo=True)

    if kr.get_password(WEB["servicio_credencial"], WEB["clave_credencial"]):
        if input("Ya hay un token de la API guardado. ¿Reemplazarlo? (s/N): ").strip().lower() == "s":
            kr.delete_password(WEB["servicio_credencial"], WEB["clave_credencial"])
    token_api(interactivo=True)

    log(f"Probando conexión con {WEB['url_base']} ...")
    try:
        suministros = obtener_suministros()
    except RuntimeError as e:
        if "401" in str(e):
            # No dejar guardado un token que el panel no acepta.
            kr.delete_password(WEB["servicio_credencial"], WEB["clave_credencial"])
            raise RuntimeError(
                "El panel no aceptó el token (no se guardó). Generá uno nuevo en el panel > Tokens, "
                "copialo completo y volvé a ejecutar --configurar.") from None
        raise
    log(f"✅ Conexión OK. Suministros activos en el panel: {len(suministros)}")
    for s in suministros:
        log(f"   NIS {s['nis']} · {s['name']}" + ("" if s.get("ready") else "  (falta cargar su contrato)"))


# -----------------------------------------------------------------------------
# API del panel (curl.exe: atraviesa el proxy corporativo con la sesión de Windows)
# -----------------------------------------------------------------------------
def _proxy_para(url):
    """Proxy configurado en Windows, salvo para direcciones locales o excluidas."""
    host = urlparse(url).hostname or ""
    if host in ("localhost", "127.0.0.1") or urllib.request.proxy_bypass(host):
        return None
    proxies = urllib.request.getproxies()
    return proxies.get("https") or proxies.get("http")


def llamar_api(metodo, ruta, cuerpo=None):
    """Llama a la API con curl y devuelve el JSON de respuesta. Lanza RuntimeError si falla."""
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("No se encontró curl.exe (viene con Windows 10 1803 o posterior).")
    url = WEB["url_base"].rstrip("/") + "/" + ruta.lstrip("/")
    token = token_api()

    with tempfile.TemporaryDirectory() as tmp:
        # El token va en un archivo de cabeceras (no en la línea de comandos, donde otros procesos lo verían).
        cabeceras = Path(tmp) / "cabeceras.txt"
        cabeceras.write_text(f"Authorization: Bearer {token}\nContent-Type: application/json\n", encoding="utf-8")
        cmd = [curl, "--silent", "--show-error", "--max-time", str(WEB["timeout_s"]),
               "-X", metodo, url, "-H", f"@{cabeceras}", "-w", "\n%{http_code}"]
        if cuerpo is not None:
            datos = Path(tmp) / "cuerpo.json"
            datos.write_text(json.dumps(cuerpo, ensure_ascii=False), encoding="utf-8")
            cmd += ["--data-binary", f"@{datos}"]
        proxy = _proxy_para(url)
        if proxy:
            cmd[1:1] = ["--proxy-anyauth", "--proxy-user", ":", "-x", proxy]

        ultimo = None
        for intento in range(1, WEB["intentos"] + 1):
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=WEB["timeout_s"] + 15)
                if p.returncode != 0:
                    ultimo = f"curl devolvió {p.returncode}: {p.stderr.strip()[:300]}"
                else:
                    cuerpo_txt, _, codigo = p.stdout.rpartition("\n")
                    try:
                        respuesta = json.loads(cuerpo_txt) if cuerpo_txt.strip() else {}
                    except ValueError:
                        respuesta = {"error": cuerpo_txt.strip()[:300]}
                    if codigo.strip() == "200" and respuesta.get("ok"):
                        return respuesta
                    ultimo = f"HTTP {codigo.strip()}: {respuesta.get('error', '')}"
                    if codigo.strip() in ("401", "403", "422"):
                        break   # errores que no se arreglan reintentando
            except subprocess.TimeoutExpired:
                ultimo = "sin respuesta del servidor (timeout)"
            if intento < WEB["intentos"]:
                log(f"   Aviso: falló la llamada a {ruta} ({ultimo}); reintento {intento + 1}/{WEB['intentos']}")
                time.sleep(5)
        raise RuntimeError(f"La API respondió con error: {ultimo}")


def obtener_suministros():
    return llamar_api("GET", "api/supplies.php")["supplies"]


def canal_aceptado(canal_excel):
    """El canal del Excel tiene que ser el configurado o uno de los canales conocidos."""
    def clave(c):  # hasta el último paréntesis: "... (time integral 5)" sin el "- 0"
        return dp.compacto(c[: c.rfind(")") + 1] if ")" in c else c)
    return any(clave(c) and dp.compacto(canal_excel).startswith(clave(c)) for c in [dp.CANAL, *dp.CANALES_CONOCIDOS])


def armar_paquete(archivo_excel, nis, desde, hasta):
    """Convierte el Excel de Optimum en el paquete mdc-readings-v1 que recibe el panel."""
    registros, info = ap.leer_perfil(archivo_excel)
    if info["punto"] and str(info["punto"]).strip() != str(nis):
        raise RuntimeError(f"El Excel es del Punto de Medida {info['punto']}, no del {nis}: no se envía.")
    if not registros:
        raise RuntimeError("El Excel no tiene lecturas.")
    if info["canal"] and not canal_aceptado(info["canal"]):
        raise RuntimeError(f"El Excel trae el canal '{info['canal']}', que no es un canal de potencia activa "
                           f"conocido ni el configurado ('{dp.CANAL}'): no se envía.")
    if info.get("unidad_original", info["unidad"]) != info["unidad"]:
        log(f"   El medidor registra energía ({info['unidad_original']} por intervalo): "
            f"se convierte a potencia media ({info['unidad']}).")
    lecturas = []
    for r in registros:
        hueco = r["valor"] is None or r["estado"].lower() == "hueco"
        lecturas.append([r["inicio"].strftime("%Y-%m-%d %H:%M"), None if hueco else r["valor"], r["estado"]])
    return {
        "format": "mdc-readings-v1",
        "nis": str(nis),
        "period_start": desde or registros[0]["inicio"].strftime("%Y-%m-%d"),
        "period_end": hasta or registros[-1]["inicio"].strftime("%Y-%m-%d"),
        "unit": info["unidad"] or "W",
        "source_unit": info.get("unidad_original") or info["unidad"] or "W",
        "meter": info["medidor"],
        "channel": info["canal"],
        "source_file": Path(archivo_excel).name,
        "readings": lecturas,
    }


def enviar(archivo_excel, nis, desde=None, hasta=None):
    paquete = armar_paquete(archivo_excel, nis, desde, hasta)
    r = llamar_api("POST", "api/readings-import.php", paquete)
    estado = {"normal": "Normal", "atencion": "Sobre la contratada", "critico": "SUPERA LA TOLERANCIA"}.get(r.get("status"), r.get("status"))
    log(f"   ✅ Panel: {r['readings']} lecturas ({r['inserted']} nuevas, {r['updated']} actualizadas) · "
        f"máx. {r.get('max_kw')} kW / límite {r.get('limit_kw')} kW · {estado}")
    if r.get("new_alerts"):
        log(f"   🚨 {r['new_alerts']} intervalo(s) nuevo(s) sobre el límite"
            + (f" · correo enviado ({r['mailed_alerts']})" if r.get("mailed_alerts") else ""))
    return r


# -----------------------------------------------------------------------------
# Descarga desde Optimum
# -----------------------------------------------------------------------------
def descargar(s, usuario, clave, desde=None, hasta=None, etiqueta=None):
    dp.MEDIDOR_PREFIJO = s.get("meter_prefix") or "EGM"
    dp.CANAL = s.get("channel") or dp.CANAL
    ultimo_error = None
    for intento in range(1, REINTENTOS_DESCARGA + 2):
        try:
            log(f"   Descarga de Optimum (intento {intento})")
            return dp.ejecutar_en_hilo(dp.descargar_perfil, s["nis"], usuario, clave, desde, hasta, etiqueta)
        except Exception as e:  # noqa: BLE001
            ultimo_error = e
            log(f"   Falló: {str(e).splitlines()[0] if str(e) else repr(e)}")
            time.sleep(20)
    raise ultimo_error


def ultimo_excel(nis):
    candidatos = sorted(dp.CARPETA_DESCARGAS.glob(f"perfil_{nis}_*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidatos[0] if candidatos else None


def rango_mes(aaaa_mm):
    a, m = (int(x) for x in aaaa_mm.split("-"))
    return date(a, m, 1), date(a, m, calendar.monthrange(a, m)[1])


def correr(descargar_datos=True, subir=True, mes=None, solo_nis=None):
    hoy = date.today()
    errores, alertas = [], []

    dp.HEADLESS = True            # sin ventana del navegador
    dp.PAUSA_SI_FALLA_S = 0       # nunca se queda esperando a nadie
    dp.LENTITUD_MS = 50

    suministros = obtener_suministros()
    if solo_nis:
        suministros = [s for s in suministros if s["nis"] == str(solo_nis)]
        if not suministros:
            raise RuntimeError(f"El NIS {solo_nis} no está activo en el panel.")
    log(f"Suministros a procesar: {', '.join(s['nis'] for s in suministros) or 'ninguno'}")

    usuario = dp.USUARIO
    clave = dp.obtener_clave(interactivo=MODO_INTERACTIVO) if descargar_datos else None

    # Qué períodos bajar
    if mes:
        ini, fin = rango_mes(mes)
        periodos = [(ini.isoformat(), min(fin, hoy).isoformat(), f"{mes}_completo")]
    else:
        periodos = []
        if hoy.day <= DIAS_RELLENO:
            fin_ant = hoy.replace(day=1) - timedelta(days=1)
            periodos.append((fin_ant.replace(day=1).isoformat(), fin_ant.isoformat(), f"{fin_ant:%Y-%m}_completo"))
        periodos.append((hoy.replace(day=1).isoformat(), hoy.isoformat(), None))

    for s in suministros:
        log(f"=== {s['name']} · NIS {s['nis']} ===")
        if not s.get("ready"):
            msg = "falta cargar su potencia contratada / factor en el panel"
            log(f"   ⚠️  Se omite: {msg}")
            errores.append(f"{s['nis']}: {msg}")
            continue
        for desde, hasta, etiqueta in periodos:
            # Ciclo en curso: si el ciclo de facturación empezó antes del 1° del mes
            # (ej. cierre 15 → arranca el 16 del mes anterior), se baja desde ahí.
            if etiqueta is None and not mes and s.get("cycle_start") and s["cycle_start"] < desde:
                desde = s["cycle_start"]
            try:
                if descargar_datos:
                    log(f"   Período {desde} a {hasta}")
                    xls = descargar(s, usuario, clave, desde, hasta, etiqueta)
                else:
                    xls = ultimo_excel(s["nis"])
                    if not xls:
                        raise RuntimeError("No hay ningún Excel descargado de este suministro.")
                    desde = hasta = None
                    log(f"   Reenviando {xls.name}")
                if subir:
                    r = enviar(xls, s["nis"], desde, hasta)
                    if r.get("new_alerts"):
                        alertas.append(f"{s['name']} (NIS {s['nis']}): {r['new_alerts']} intervalo(s) sobre el límite; "
                                       f"máx. {r.get('max_kw')} kW, límite {r.get('limit_kw')} kW.")
                if not descargar_datos:
                    break
            except Exception as e:  # noqa: BLE001
                errores.append(f"{s['nis']} ({desde or 'último'}): {e}")
                log(f"   ❌ {e}")
                traceback.print_exc()

    if alertas and VENTANA_ALERTA_AL_FINAL:
        ap._ventana("Alerta de potencia - Optimum", "\n\n".join(alertas)[:3000])
    return errores


# -----------------------------------------------------------------------------
# Tarea programada de Windows
# -----------------------------------------------------------------------------
def crear_tarea(hora="07:15"):
    """Escribe ejecutar_orquestador.bat (con el Python que estás usando) y crea la tarea diaria."""
    if not sys.platform.startswith("win"):
        raise SystemExit("La tarea programada solo se puede crear en Windows.")
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    prefijo = Path(sys.prefix)
    activar = prefijo / "Scripts" / "activate.bat"
    lineas = ["@echo off", "REM Generado por orquestador_diario.py --crear-tarea",
              'cd /d "%~dp0"', "if not exist logs mkdir logs"]
    if activar.exists():   # Anaconda: activar el entorno para que encuentre sus DLL
        lineas.append(f'call "{activar}" "{prefijo}"')
    lineas += [f'"{python}" orquestador_diario.py --auto %* >> "logs\\tarea_programada.log" 2>&1',
               "exit /b %ERRORLEVEL%"]
    bat = CARPETA / "ejecutar_orquestador.bat"
    # cmd.exe lee los .bat con la página de códigos OEM (rutas con tildes/ñ incluidas)
    bat.write_text("\r\n".join(lineas) + "\r\n", encoding="oem", errors="replace")
    log(f"✅ Creado {bat}")
    comando = ["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", hora, "/TN", NOMBRE_TAREA, "/TR", f'"{bat}"']
    r = subprocess.run(comando, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"schtasks no pudo crear la tarea:\n{((r.stdout or '') + (r.stderr or '')).strip()}")
    log(f"✅ Tarea '{NOMBRE_TAREA}' creada: todos los días a las {hora}.")
    log(f'   Probarla ahora:  schtasks /Run /TN "{NOMBRE_TAREA}"')


# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Orquestador diario: Optimum.SM -> panel web")
    parser.add_argument("--configurar", action="store_true", help="guardar contraseña y token, y probar la conexión")
    parser.add_argument("--sin-subir", action="store_true", help="descargar pero no enviar al panel")
    parser.add_argument("--sin-descargar", action="store_true", help="reenviar el último Excel ya descargado")
    parser.add_argument("--mes", metavar="AAAA-MM", help="cargar un mes pasado completo (histórico)")
    parser.add_argument("--nis", help="procesar solo este suministro")
    parser.add_argument("--archivo", help="enviar un Excel descargado a mano (requiere --nis)")
    parser.add_argument("--auto", action="store_true",
                        help="modo tarea programada: nunca abre ventanas ni pregunta nada")
    parser.add_argument("--crear-tarea", nargs="?", const="07:15", metavar="HH:MM",
                        help="crear la tarea diaria en Windows (por defecto 07:15)")
    args = parser.parse_args()
    global MODO_INTERACTIVO, VENTANA_ALERTA_AL_FINAL
    if args.auto:
        MODO_INTERACTIVO = False
        VENTANA_ALERTA_AL_FINAL = False   # nadie está mirando: las alertas van por correo desde el panel

    archivo_log = iniciar_log()
    inicio = time.time()
    log(f"##### Orquestador iniciado (log: {archivo_log.name}) #####")
    try:
        if args.configurar:
            configurar()
            return 0
        if args.crear_tarea:
            crear_tarea(args.crear_tarea)
            return 0
        if args.archivo:
            if not args.nis:
                raise SystemExit("--archivo necesita también --nis")
            enviar(Path(args.archivo), args.nis)
            return 0
        if args.mes and not (len(args.mes) == 7 and args.mes[4] == "-"):
            raise SystemExit("--mes debe tener formato AAAA-MM, por ejemplo 2026-10")
        errores = correr(descargar_datos=not args.sin_descargar, subir=not args.sin_subir,
                         mes=args.mes, solo_nis=args.nis)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        log(f"❌ Error general: {e}")
        traceback.print_exc()
        return 1
    finally:
        log(f"##### Fin ({time.time() - inicio:.0f} s) #####")
    if errores:
        log("Terminó con errores:\n  " + "\n  ".join(errores))
        return 1
    log("✅ Todo OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
