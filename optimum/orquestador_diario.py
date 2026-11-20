"""
Orquestador diario: Optimum.SM -> análisis -> página web en Hostinger.

Qué hace cada vez que corre (pensado para el Programador de tareas de Windows):
  1. Para cada suministro de SUMINISTROS (analisis_perfil.py) descarga el
     Perfil de Carga del mes actual (del 1° a hoy) sin mostrar el navegador.
     El día 1 de cada mes, además, baja el mes anterior completo para cerrarlo.
  2. Genera la página de cada suministro y una portada (index.html).
  3. Revisa alertas (correo si está configurado; ventana si corrés a mano).
  4. Sube todo a Hostinger por FTP (FTPS si el servidor lo acepta).
  5. Deja un registro en logs/ y termina con código 0 (OK) o 1 (hubo errores).

Primera vez (una sola vez, a mano):
    python orquestador_diario.py --configurar
  Guarda en el Administrador de credenciales de Windows la contraseña de
  Optimum y la del FTP de Hostinger, y prueba la conexión FTP.

Otras opciones útiles para probar:
    python orquestador_diario.py --sin-subir      # todo menos subir a Hostinger
    python orquestador_diario.py --sin-descargar  # usa el último Excel ya bajado
    python orquestador_diario.py --solo-subir     # sube lo que ya está en reportes/web
"""

import argparse
import ftplib
import getpass
import io
import json
import os
import socket
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA))

import analisis_perfil as ap          # noqa: E402
import descargar_perfil_carga as dp   # noqa: E402

# =============================================================================
# CONFIGURACIÓN — Hostinger
# =============================================================================
# Datos en hPanel > Archivos > Cuentas FTP (host, usuario y puerto).
HOSTINGER = {
    "host": "ftp.tudominio.com",          # o la IP que muestra hPanel
    "puerto": 21,
    "usuario": "u123456789.tudominio.com",
    "carpeta_remota": "public_html/potencia",  # quedaría en https://tudominio.com/potencia/
    "usar_tls": True,                     # FTPS explícito (cifrado). Hostinger lo acepta.
    "permitir_sin_cifrar": False,         # True = si FTPS falla, usa FTP común (la clave viaja sin cifrar)
    # La contraseña FTP se guarda en el Administrador de credenciales de Windows:
    "servicio_credencial": "Automatismo_Telemedicion",
    "clave_credencial": "hostinger_ftp",
}

URL_SITIO = "https://tudominio.com/potencia"   # dirección pública (va en los correos de alerta)
TITULO_SITIO = "Monitoreo de potencia — ANDE"
VENTANA_ALERTA_AL_FINAL = True       # muestra un aviso en la PC al terminar si hubo alertas nuevas
CARPETA_WEB = CARPETA / "reportes" / "web"        # copia local exacta de lo que se sube
ARCHIVO_RESUMENES = CARPETA / "reportes" / "resumenes.json"
CARPETA_LOGS = CARPETA / "logs"
GUARDAR_LOGS_DIAS = 60
REINTENTOS_DESCARGA = 2              # reintentos por suministro si Optimum falla
# =============================================================================


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


def clave_ftp(interactivo=False):
    if os.environ.get("HOSTINGER_FTP_PASS"):
        return os.environ["HOSTINGER_FTP_PASS"]
    kr = _keyring()
    clave = kr.get_password(HOSTINGER["servicio_credencial"], HOSTINGER["clave_credencial"])
    if clave:
        return clave
    if not interactivo:
        raise RuntimeError("No hay contraseña FTP guardada. Ejecutá: python orquestador_diario.py --configurar")
    clave = getpass.getpass(f"Contraseña FTP de Hostinger ({HOSTINGER['usuario']}): ")
    if not clave:
        raise SystemExit("Cancelado.")
    kr.set_password(HOSTINGER["servicio_credencial"], HOSTINGER["clave_credencial"], clave)
    log("✅ Contraseña FTP guardada en el Administrador de credenciales de Windows.")
    return clave


def configurar():
    log("Configuración inicial de credenciales")
    kr = _keyring()
    if kr.get_password(dp.SERVICIO_CREDENCIAL, dp.CLAVE_CREDENCIAL):
        log("✅ La contraseña de Optimum ya está guardada (la misma del script del MDC).")
    else:
        dp.obtener_clave(interactivo=True)

    if kr.get_password(HOSTINGER["servicio_credencial"], HOSTINGER["clave_credencial"]):
        r = input("Ya hay una contraseña FTP guardada. ¿Reemplazarla? (s/N): ").strip().lower()
        if r == "s":
            kr.delete_password(HOSTINGER["servicio_credencial"], HOSTINGER["clave_credencial"])
    clave_ftp(interactivo=True)

    log("Probando conexión FTP...")
    with conectar_ftp() as ftp:
        ir_a_carpeta(ftp, HOSTINGER["carpeta_remota"], crear=True)
        log(f"✅ Conexión OK. Carpeta remota: /{HOSTINGER['carpeta_remota']}")


# -----------------------------------------------------------------------------
# FTP
# -----------------------------------------------------------------------------
def conectar_ftp():
    clave = clave_ftp()
    h = HOSTINGER
    if h["usar_tls"]:
        try:
            ftp = ftplib.FTP_TLS(timeout=60)
            ftp.connect(h["host"], h["puerto"])
            ftp.login(h["usuario"], clave)
            ftp.prot_p()                      # datos cifrados también
            ftp.set_pasv(True)
            log(f"   Conectado por FTPS a {h['host']}")
            return ftp
        except (ftplib.all_errors) as e:
            if not h.get("permitir_sin_cifrar"):
                raise RuntimeError(f"No se pudo conectar por FTPS ({e}). Revisá host/usuario/clave; "
                                   "si tu servidor no admite FTPS, poné permitir_sin_cifrar = True.")
            log(f"   FTPS no disponible ({e}); pruebo FTP común")
    ftp = ftplib.FTP(timeout=60)
    ftp.connect(h["host"], h["puerto"])
    ftp.login(h["usuario"], clave)
    ftp.set_pasv(True)
    log(f"   Conectado por FTP a {h['host']}")
    return ftp


def ir_a_carpeta(ftp, ruta, crear=True):
    ftp.cwd("/")
    for parte in [p for p in ruta.replace("\\", "/").split("/") if p]:
        try:
            ftp.cwd(parte)
        except ftplib.error_perm:
            if not crear:
                raise
            ftp.mkd(parte)
            ftp.cwd(parte)


def subir_carpeta(local, remota):
    """Sube todos los archivos de `local` a `remota` (sube a .tmp y renombra: nunca queda una página a medias)."""
    archivos = sorted(p for p in Path(local).rglob("*") if p.is_file())
    if not archivos:
        log("   No hay archivos para subir.")
        return 0
    with conectar_ftp() as ftp:
        for archivo in archivos:
            rel = archivo.relative_to(local).as_posix()
            carpeta_rel, _, nombre = rel.rpartition("/")
            ir_a_carpeta(ftp, f"{remota}/{carpeta_rel}" if carpeta_rel else remota, crear=True)
            temporal = nombre + ".tmp"
            with open(archivo, "rb") as f:
                ftp.storbinary(f"STOR {temporal}", f)
            try:
                ftp.delete(nombre)
            except ftplib.error_perm:
                pass
            ftp.rename(temporal, nombre)
            log(f"   ↑ {rel}")
    return len(archivos)


# -----------------------------------------------------------------------------
# Pasos
# -----------------------------------------------------------------------------
def descargar(nis, usuario, clave, desde=None, hasta=None, etiqueta=None):
    ultimo_error = None
    for intento in range(1, REINTENTOS_DESCARGA + 2):
        try:
            log(f"   Descarga NIS {nis} (intento {intento})")
            return dp.ejecutar_en_hilo(dp.descargar_perfil, nis, usuario, clave, desde, hasta, etiqueta)
        except Exception as e:  # noqa: BLE001
            ultimo_error = e
            log(f"   Falló: {str(e).splitlines()[0] if str(e) else repr(e)}")
            time.sleep(20)
    raise ultimo_error


def ultimo_excel(nis, etiqueta_prefijo=""):
    candidatos = sorted(dp.CARPETA_DESCARGAS.glob(f"perfil_{nis}_{etiqueta_prefijo}*.xls*"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    return candidatos[0] if candidatos else None


def cargar_resumenes():
    try:
        return json.loads(ARCHIVO_RESUMENES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def historial_local():
    """{nis: [(mes, ruta_relativa), ...]} con las páginas mensuales ya generadas."""
    hist = {}
    for p in sorted((CARPETA_WEB / "historial").glob("perfil_*_*.html"), reverse=True):
        _, nis, mes = p.stem.split("_", 2)
        hist.setdefault(nis, []).append((mes, f"historial/{p.name}"))
    return hist


def correr(descargar_datos=True, subir=True):
    hoy = date.today()
    errores = []
    resumenes = cargar_resumenes()
    CARPETA_WEB.mkdir(parents=True, exist_ok=True)

    # El navegador no se muestra y nunca se queda esperando a nadie.
    dp.HEADLESS = True
    dp.PAUSA_SI_FALLA_S = 0
    dp.LENTITUD_MS = 50
    # Durante la corrida no se abren ventanas (bloquearían la subida); se avisa al final.
    ap.ALERTA_VENTANA = False
    ap.URL_SITIO = URL_SITIO
    alertas = []

    usuario = dp.USUARIO
    clave = dp.obtener_clave(interactivo=False) if descargar_datos else None

    for nis, cfg in ap.SUMINISTROS.items():
        log(f"=== Suministro {nis} ({cfg.get('nombre', '')}) ===")
        try:
            # Día 1: cerrar el mes anterior completo (queda en historial/)
            if descargar_datos and hoy.day == 1:
                fin_ant = hoy - timedelta(days=1)
                ini_ant = fin_ant.replace(day=1)
                etiqueta = f"{ini_ant:%Y-%m}_completo"
                xls = descargar(nis, usuario, clave, ini_ant.isoformat(), fin_ant.isoformat(), etiqueta)
                res_ant, _ = ap.procesar(xls, nis, abrir=False, alertar=True, enlace_volver="../index.html",
                                     destino=CARPETA_WEB / "historial" / f"perfil_{nis}_{ini_ant:%Y-%m}.html")
                if res_ant["alerta_nueva"]:
                    alertas.append(res_ant["alerta_nueva"])

            xls = descargar(nis, usuario, clave) if descargar_datos else ultimo_excel(nis)
            if not xls:
                raise RuntimeError("No hay ningún Excel descargado para este suministro.")
            res, _ = ap.procesar(xls, nis, abrir=False, alertar=True, enlace_volver="index.html",
                                 destino=CARPETA_WEB / f"perfil_{nis}.html")
            # Copia del mes en curso en el historial (se pisa cada día hasta que cierra el mes)
            ap.generar_html(res, CARPETA_WEB / "historial" / f"perfil_{nis}_{hoy:%Y-%m}.html", "../index.html")
            resumenes[nis] = ap.resumen(res, f"perfil_{nis}.html")
            if res["alerta_nueva"]:
                alertas.append(res["alerta_nueva"])
        except Exception as e:  # noqa: BLE001
            errores.append(f"{nis}: {e}")
            log(f"❌ Error con el suministro {nis}: {e}")
            traceback.print_exc()

    # Portada (con lo último que haya de cada suministro, aunque hoy haya fallado alguno)
    ARCHIVO_RESUMENES.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO_RESUMENES.write_text(json.dumps(resumenes, ensure_ascii=False, indent=1), encoding="utf-8")
    vigentes = [r for n, r in resumenes.items() if n in ap.SUMINISTROS]
    if vigentes:
        ap.generar_indice(vigentes, CARPETA_WEB / "index.html", historial_local(), TITULO_SITIO)
        log(f"Portada generada: {CARPETA_WEB / 'index.html'}")

    if subir:
        log("=== Subiendo a Hostinger ===")
        try:
            n = subir_carpeta(CARPETA_WEB, HOSTINGER["carpeta_remota"])
            log(f"✅ {n} archivo(s) subidos a /{HOSTINGER['carpeta_remota']}")
        except (ftplib.all_errors, socket.error, RuntimeError) as e:
            errores.append(f"FTP: {e}")
            log(f"❌ Error subiendo a Hostinger: {e}")

    if alertas and VENTANA_ALERTA_AL_FINAL:
        ap._ventana("Alerta de potencia - Optimum", "\n\n".join(alertas)[:3000])
    return errores


def main():
    parser = argparse.ArgumentParser(description="Orquestador diario del Perfil de Carga")
    parser.add_argument("--configurar", action="store_true", help="guardar credenciales y probar FTP")
    parser.add_argument("--sin-subir", action="store_true", help="no subir a Hostinger")
    parser.add_argument("--sin-descargar", action="store_true", help="usar el último Excel ya descargado")
    parser.add_argument("--solo-subir", action="store_true", help="solo subir reportes/web")
    args = parser.parse_args()

    archivo_log = iniciar_log()
    inicio = time.time()
    log(f"##### Orquestador iniciado (log: {archivo_log.name}) #####")
    try:
        if args.configurar:
            configurar()
            return 0
        if args.solo_subir:
            subir_carpeta(CARPETA_WEB, HOSTINGER["carpeta_remota"])
            return 0
        errores = correr(descargar_datos=not args.sin_descargar, subir=not args.sin_subir)
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
