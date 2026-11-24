"""
Análisis del Perfil de Carga descargado de Optimum.SM.

- Lee el Excel que baja descargar_perfil_carga.py (columna "Valor" en W,
  valores secundarios del medidor, intervalos de 15 min). Si el medidor
  registra energía por intervalo (Wh, p. ej. Actaris ACE6000), la pasa a
  potencia media del intervalo (W = Wh ÷ horas del intervalo = Wh × 4).
- Multiplica por el factor del suministro y pasa a kW.
- Compara contra la potencia contratada y su tolerancia.
- Genera una página web (HTML autocontenido, no necesita internet ni servidor).
- Si se supera la tolerancia, avisa: ventana emergente en Windows y,
  opcionalmente, correo (Outlook o SMTP). No repite alertas ya enviadas.

Uso suelto (sobre un Excel ya descargado):
    python analisis_perfil.py ruta\\al\\perfil_1379190_20261120.xlsx
    python analisis_perfil.py ruta\\al\\archivo.xlsx 1379190
"""

import html
import json
import re
import sys
import webbrowser
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIGURACIÓN DE SUMINISTROS — agregá acá los que quieras monitorear
# =============================================================================
SUMINISTROS = {
    "1379190": {
        "nombre": "Suministro 1379190",
        "factor": 1815.78,                 # factor multiplicador (TC x TP)
        "potencia_contratada_kw": 1520.0,  # potencia contratada actual
        "tolerancia": 0.10,                # 10 %
    },
}

CARPETA_BASE = Path(__file__).resolve().parent
CARPETA_REPORTES = CARPETA_BASE / "reportes"
ARCHIVO_ESTADO_ALERTAS = CARPETA_BASE / "reportes" / "alertas_enviadas.json"

ABRIR_PAGINA_AL_TERMINAR = True     # abre el reporte en el navegador

# ---- Alertas ----------------------------------------------------------------
ALERTA_VENTANA = True               # ventana emergente en la PC
URL_SITIO = ""                      # si hay página publicada, se incluye el enlace en la alerta

ALERTA_EMAIL = {
    "activar": False,               # poné True cuando completes los datos
    "metodo": "outlook",            # "outlook" (usa tu Outlook abierto) o "smtp"
    "para": ["destinatario@ande.gov.py"],
    # Solo para metodo = "smtp":
    "smtp_servidor": "smtp.ande.gov.py",
    "smtp_puerto": 587,
    "smtp_usuario": "",
    "smtp_remitente": "",
    # La contraseña SMTP se guarda en el Administrador de credenciales de Windows:
    "smtp_servicio_credencial": "Automatismo_Telemedicion",
    "smtp_clave_credencial": "smtp",
}
# =============================================================================


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# -----------------------------------------------------------------------------
# Lectura del Excel
# -----------------------------------------------------------------------------
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _leer_filas_xlsx(ruta):
    """
    Lee la primera hoja directamente del XML. El Excel que genera Optimum trae
    una hoja de estilos que openpyxl/pandas no pueden abrir, por eso no los usamos.
    """
    with zipfile.ZipFile(ruta) as z:
        nombres = z.namelist()
        compartidos = []
        if "xl/sharedStrings.xml" in nombres:
            raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in raiz.findall("m:si", _NS):
                compartidos.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        hojas = sorted(n for n in nombres if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        raiz = ET.fromstring(z.read(hojas[0]))

    filas = []
    for fila in raiz.find("m:sheetData", _NS):
        datos = {}
        for c in fila:
            col = re.match(r"[A-Z]+", c.get("r", "")).group(0)
            tipo = c.get("t")
            if tipo == "inlineStr":
                valor = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                v = c.find("m:v", _NS)
                valor = v.text if v is not None else None
                if tipo == "s" and valor is not None:
                    valor = compartidos[int(valor)]
            datos[col] = valor
        filas.append(datos)
    return filas


def _a_fecha(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            pass
    try:  # número de serie de Excel
        from datetime import timedelta
        return datetime(1899, 12, 30) + timedelta(days=float(texto))
    except ValueError:
        return None


def leer_perfil(ruta):
    """Devuelve (registros, info). Cada registro: inicio, fin, valor, unidad, estado."""
    filas = _leer_filas_xlsx(ruta)

    # Buscar la fila de encabezados ("Fecha Desde", "Valor", ...)
    columnas = None
    for i, fila in enumerate(filas):
        nombres = {(v or "").strip().lower(): col for col, v in fila.items()}
        if "fecha desde" in nombres and "valor" in nombres:
            columnas = nombres
            inicio_datos = i + 1
            break
    if not columnas:
        raise ValueError("No encontré los encabezados 'Fecha Desde' / 'Valor' en el Excel.")

    def col(nombre):
        return columnas.get(nombre)

    registros = []
    for fila in filas[inicio_datos:]:
        inicio = _a_fecha(fila.get(col("fecha desde")))
        if inicio is None:
            continue
        try:
            valor = float(fila.get(col("valor")))
        except (TypeError, ValueError):
            valor = None
        registros.append({
            "inicio": inicio,
            "fin": _a_fecha(fila.get(col("fecha hasta"))),
            "valor": valor,
            "unidad": (fila.get(col("unidad")) or "").strip(),
            "estado": (fila.get(col("resultado de lectura")) or "").strip(),
            "medidor": (fila.get(col("medidor")) or "").strip(),
            "punto": (fila.get(col("punto de medida")) or "").strip(),
            "canal": (fila.get(col("desc. canal")) or "").strip(),
        })
    registros.sort(key=lambda r: r["inicio"])

    info = {
        "medidor": next((r["medidor"] for r in registros if r["medidor"]), ""),
        "punto": next((r["punto"] for r in registros if r["punto"]), ""),
        "canal": next((r["canal"] for r in registros if r["canal"]), ""),
        "unidad": next((r["unidad"] for r in registros if r["unidad"]), "W"),
    }
    info["unidad_original"] = info["unidad"]
    if _ENERGIA_A_POTENCIA.get(info["unidad"].lower()):
        _energia_a_potencia(registros, info)
    return registros, info


# Algunos medidores (p. ej. Actaris ACE6000, canal "... (time integral 5)") no
# registran potencia sino la ENERGÍA de cada intervalo (Wh por 15 min). La
# potencia media del intervalo, que es la demanda que se factura, es
# energía ÷ duración: 2,9 Wh en 15 min = 2,9 × 4 = 11,6 W.
_ENERGIA_A_POTENCIA = {"wh": "W", "kwh": "kW", "mwh": "MW"}


def _energia_a_potencia(registros, info):
    """Convierte en el lugar los valores de energía por intervalo en potencia media."""
    for r in registros:
        r["valor_original"] = r["valor"]
        destino = _ENERGIA_A_POTENCIA.get(r["unidad"].lower())
        if destino is None:
            if r["unidad"]:
                raise ValueError(f"El Excel mezcla unidades ({info['unidad']} y {r['unidad']}).")
            destino = _ENERGIA_A_POTENCIA[info["unidad"].lower()]
        horas = (r["fin"] - r["inicio"]).total_seconds() / 3600 if r["fin"] else 0.25
        if horas <= 0:
            raise ValueError(f"Intervalo inválido en {r['inicio']} (fin {r['fin']}).")
        if r["valor"] is not None:
            r["valor"] = round(r["valor"] / horas, 6)
        r["unidad"] = destino
    info["unidad"] = _ENERGIA_A_POTENCIA[info["unidad"].lower()]


# -----------------------------------------------------------------------------
# Cálculos
# -----------------------------------------------------------------------------
_A_KW = {"w": 1 / 1000, "kw": 1.0, "mw": 1000.0}


def analizar(registros, info, cfg):
    factor = cfg["factor"]
    contratada = cfg["potencia_contratada_kw"]
    limite = contratada * (1 + cfg["tolerancia"])
    a_kw = _A_KW.get(info["unidad"].lower(), 1 / 1000)

    puntos = []        # para el gráfico (huecos = None)
    validos = []
    huecos = 0
    for r in registros:
        es_hueco = r["valor"] is None or r["estado"].lower() == "hueco"
        if es_hueco:
            huecos += 1
            puntos.append([r["inicio"].strftime("%Y-%m-%dT%H:%M"), None])
            continue
        kw = r["valor"] * factor * a_kw
        puntos.append([r["inicio"].strftime("%Y-%m-%dT%H:%M"), round(kw, 1)])
        horas = ((r["fin"] - r["inicio"]).total_seconds() / 3600) if r["fin"] else 0.25
        validos.append({"inicio": r["inicio"], "kw": kw, "horas": horas})

    if not validos:
        raise ValueError("El archivo no tiene lecturas válidas.")

    def estado(kw):
        if kw > limite:
            return "critico"
        if kw > contratada:
            return "atencion"
        return "normal"

    maximo = max(validos, key=lambda v: v["kw"])
    energia_kwh = sum(v["kw"] * v["horas"] for v in validos)
    horas_totales = sum(v["horas"] for v in validos)
    promedio = energia_kwh / horas_totales if horas_totales else 0

    por_dia = {}
    for v in validos:
        dia = v["inicio"].date()
        if dia not in por_dia or v["kw"] > por_dia[dia]["kw"]:
            por_dia[dia] = v
    diario = [
        {"dia": d.isoformat(), "kw": round(v["kw"], 1), "hora": v["inicio"].strftime("%H:%M"),
         "estado": estado(v["kw"])}
        for d, v in sorted(por_dia.items())
    ]

    excesos = [
        {"inicio": v["inicio"].strftime("%Y-%m-%d %H:%M"), "kw": round(v["kw"], 1),
         "pct": round(v["kw"] / contratada * 100, 1)}
        for v in validos if v["kw"] > limite
    ]
    sobre_contratada = sum(1 for v in validos if v["kw"] > contratada)
    top = sorted(validos, key=lambda v: v["kw"], reverse=True)[:10]

    return {
        "nis": info["punto"] or cfg.get("nis", ""),
        "nombre": cfg.get("nombre", ""),
        "medidor": info["medidor"],
        "canal": info["canal"],
        "factor": factor,
        "contratada": contratada,
        "tolerancia": cfg["tolerancia"],
        "limite": round(limite, 1),
        "desde": validos[0]["inicio"].strftime("%Y-%m-%d %H:%M"),
        "hasta": registros[-1]["fin"].strftime("%Y-%m-%d %H:%M") if registros[-1]["fin"]
                 else registros[-1]["inicio"].strftime("%Y-%m-%d %H:%M"),
        "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "max_kw": round(maximo["kw"], 1),
        "max_cuando": maximo["inicio"].strftime("%Y-%m-%d %H:%M"),
        "max_pct": round(maximo["kw"] / contratada * 100, 1),
        "margen_kw": round(limite - maximo["kw"], 1),
        "energia_kwh": round(energia_kwh, 0),
        "promedio_kw": round(promedio, 1),
        "factor_carga": round(promedio / maximo["kw"] * 100, 1) if maximo["kw"] else 0,
        "lecturas": len(registros),
        "huecos": huecos,
        "sobre_contratada": sobre_contratada,
        "excesos": excesos,
        "estado": estado(maximo["kw"]),
        "diario": diario,
        "top": [{"inicio": v["inicio"].strftime("%Y-%m-%d %H:%M"), "kw": round(v["kw"], 1),
                 "pct": round(v["kw"] / contratada * 100, 1)} for v in top],
        "puntos": puntos,
    }


# -----------------------------------------------------------------------------
# Página web
# -----------------------------------------------------------------------------
def generar_html(res, destino, enlace_volver=None):
    datos = json.dumps(res, ensure_ascii=False, separators=(",", ":"))
    titulo = html.escape(f"Perfil de carga NIS {res['nis']}")
    volver = (f'<a class="volver" href="{html.escape(enlace_volver)}">← Todos los suministros</a>'
              if enlace_volver else "")
    pagina = (_PLANTILLA.replace("__TITULO__", titulo).replace("__VOLVER__", volver)
              .replace("__DATOS__", datos.replace("</", "<\\/")))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina, encoding="utf-8")
    return destino


_PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>__TITULO__</title>
<style>
:root{
  color-scheme: light;
  --bg:#f4f3f0; --surface:#fcfcfb; --border:#e3e2dd; --grid:#ecebe7;
  --text:#0b0b0b; --text-2:#52514e; --text-3:#7a7974;
  --series:#2a78d6; --series-soft:rgba(42,120,214,.10);
  --good:#0ca30c; --good-text:#006300; --warning:#fab219; --warning-text:#8a5a00;
  --critical:#d03b3b; --critical-text:#b02a2a;
  --accent:#4f1f5c;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --bg:#121211; --surface:#1a1a19; --border:#2e2e2b; --grid:#262624;
    --text:#f0efec; --text-2:#c3c2b7; --text-3:#8f8e86;
    --series:#3987e5; --series-soft:rgba(57,135,229,.16);
    --good:#0ca30c; --good-text:#4cc94c; --warning:#fab219; --warning-text:#fab219;
    --critical:#d03b3b; --critical-text:#f07b7b;
    --accent:#c79ad6;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --bg:#121211; --surface:#1a1a19; --border:#2e2e2b; --grid:#262624;
  --text:#f0efec; --text-2:#c3c2b7; --text-3:#8f8e86;
  --series:#3987e5; --series-soft:rgba(57,135,229,.16);
  --good:#0ca30c; --good-text:#4cc94c; --warning:#fab219; --warning-text:#fab219;
  --critical:#d03b3b; --critical-text:#f07b7b;
  --accent:#c79ad6;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.45 "Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif;font-variant-numeric:tabular-nums}
.wrap{max-width:1240px;margin:0 auto;padding:24px 16px 48px}
header{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:flex-end;justify-content:space-between;margin-bottom:16px}
h1{font-size:22px;margin:0 0 4px;font-weight:650}
.sub{color:var(--text-2);font-size:13px}
.sub b{color:var(--text);font-weight:600}
.estado{display:flex;gap:12px;align-items:center;padding:14px 16px;border-radius:10px;
  background:var(--surface);border:1px solid var(--border);border-left-width:6px;margin-bottom:16px}
.estado .ico{flex:none;width:26px;height:26px}
.estado strong{display:block;font-size:15px}
.estado span{color:var(--text-2);font-size:13px}
.estado.normal{border-left-color:var(--good)} .estado.normal strong{color:var(--good-text)}
.estado.atencion{border-left-color:var(--warning)} .estado.atencion strong{color:var(--warning-text)}
.estado.critico{border-left-color:var(--critical)} .estado.critico strong{color:var(--critical-text)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.kpi .l{color:var(--text-2);font-size:12px}
.kpi .v{font-size:24px;font-weight:650;margin-top:2px;white-space:nowrap}
.kpi .v small{font-size:13px;font-weight:500;color:var(--text-2);margin-left:3px}
.kpi .d{color:var(--text-3);font-size:12px;margin-top:2px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px 10px;margin-bottom:16px}
.card h2{font-size:15px;margin:0;font-weight:620}
.card .nota{color:var(--text-2);font-size:12px;margin:2px 0 8px}
.chart{position:relative;width:100%}
.chart svg{display:block;width:100%;overflow:visible}
.axis text{fill:var(--text-3);font-size:11px}
.grid line{stroke:var(--grid);stroke-width:1}
.ref line{stroke-width:1.5;stroke-dasharray:6 4}
.ref text,.lbl{font-size:11px;font-weight:600;paint-order:stroke;stroke:var(--surface);stroke-width:4px;stroke-linejoin:round}
.ref.contratada line{stroke:var(--text-2)} .ref.contratada text{fill:var(--text-2)}
.ref.limite line{stroke:var(--critical)} .ref.limite text{fill:var(--critical-text)}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.12);
  white-space:nowrap;opacity:0;transition:opacity .08s;z-index:2}
.tip b{font-size:14px}
.tip .e{display:flex;align-items:center;gap:6px;margin-top:3px;color:var(--text-2)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none}
.leyenda{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--text-2);margin:2px 0 6px}
.leyenda span{display:inline-flex;align-items:center;gap:6px}
.rango{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 4px}
.rango button{font:inherit;font-size:12px;padding:4px 10px;border-radius:6px;border:1px solid var(--border);
  background:var(--surface);color:var(--text-2);cursor:pointer}
.rango button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
details{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 16px;margin-bottom:12px}
summary{cursor:pointer;font-weight:600}
table{border-collapse:collapse;width:100%;margin-top:10px;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--border);text-align:right}
th:first-child,td:first-child{text-align:left}
th{color:var(--text-2);font-weight:600}
.tabla-scroll{overflow-x:auto}
.volver{display:inline-block;margin-bottom:10px;color:var(--accent);text-decoration:none;font-size:13px;font-weight:600}
.volver:hover{text-decoration:underline}
footer{color:var(--text-3);font-size:12px;margin-top:20px}
</style>
</head>
<body>
<div class="wrap">
  __VOLVER__
  <header>
    <div>
      <h1 id="titulo"></h1>
      <div class="sub" id="sub"></div>
    </div>
    <div class="sub" id="gen"></div>
  </header>

  <div class="estado" id="estado"></div>
  <div class="kpis" id="kpis"></div>

  <section class="card">
    <h2>Curva de carga</h2>
    <div class="nota">Demanda en kW cada 15 minutos (valor del medidor × factor). Los huecos sin lectura quedan cortados.</div>
    <div class="rango" id="rango"></div>
    <div class="leyenda" id="ley1"></div>
    <div class="chart" id="curva"></div>
  </section>

  <section class="card">
    <h2>Demanda máxima diaria</h2>
    <div class="nota">El pico de cada día comparado con la potencia contratada y el límite de tolerancia.</div>
    <div class="leyenda" id="ley2"></div>
    <div class="chart" id="diario"></div>
  </section>

  <details id="det-excesos"><summary></summary><div class="tabla-scroll" id="t-excesos"></div></details>
  <details><summary>Las 10 demandas más altas</summary><div class="tabla-scroll" id="t-top"></div></details>
  <details><summary>Tabla de máximos diarios</summary><div class="tabla-scroll" id="t-diario"></div></details>

  <footer id="pie"></footer>
</div>

<script>
const D = __DATOS__;
const NF = (n, d=1) => Number(n).toLocaleString('es-PY', {minimumFractionDigits:d, maximumFractionDigits:d});
const F0 = n => NF(n, 0);
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fechaLarga = s => { const d = typeof s === 'number' ? new Date(s) : new Date(s.replace(' ', 'T'));
  return d.toLocaleDateString('es-PY', {weekday:'short', day:'2-digit', month:'2-digit', year:'numeric'}) + ' ' +
         d.toLocaleTimeString('es-PY', {hour:'2-digit', minute:'2-digit', hour12:false}); };
const diaCorto = s => { const d = new Date(s + 'T00:00'); return d.toLocaleDateString('es-PY', {day:'2-digit', month:'2-digit'}); };
const ESTADOS = {
  normal:   {txt:'Normal', color:'--good', barra:'--series', ico:'<path d="M5 13l4 4L19 7" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'},
  atencion: {txt:'Sobre la contratada (dentro de tolerancia)', color:'--warning', barra:'--warning', ico:'<path d="M12 7v6M12 16.5v.5" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/>'},
  critico:  {txt:'Supera la tolerancia', color:'--critical', barra:'--critical', ico:'<path d="M8 8l8 8M16 8l-8 8" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/>'},
};
const icono = (e, size=26) => `<svg class="ico" viewBox="0 0 24 24" width="${size}" height="${size}" style="color:var(${ESTADOS[e].color})"><circle cx="12" cy="12" r="11" fill="currentColor" opacity=".16"/>${ESTADOS[e].ico}</svg>`;

// ---------- Encabezado, estado y KPIs ----------
document.getElementById('titulo').textContent = `Perfil de carga · NIS ${D.nis}`;
document.getElementById('sub').innerHTML =
  `Medidor <b>${D.medidor}</b> · Período <b>${fechaLarga(D.desde)}</b> a <b>${fechaLarga(D.hasta)}</b><br>` +
  `Factor <b>${NF(D.factor, 2)}</b> · Contratada <b>${F0(D.contratada)} kW</b> · Tolerancia <b>${F0(D.tolerancia*100)} %</b> (límite <b>${F0(D.limite)} kW</b>)`;
document.getElementById('gen').textContent = `Actualizado: ${fechaLarga(D.generado)}`;

const msgEstado = {
  normal: `La demanda máxima del período (${F0(D.max_kw)} kW) está por debajo de la potencia contratada. Margen hasta el límite: ${F0(D.margen_kw)} kW.`,
  atencion: `La demanda superó la potencia contratada en ${D.sobre_contratada} intervalo(s), pero sin pasar el límite de tolerancia (${F0(D.limite)} kW).`,
  critico: `Se superó el límite de tolerancia (${F0(D.limite)} kW) en ${D.excesos.length} intervalo(s). Máximo: ${F0(D.max_kw)} kW (${NF(D.max_pct)} % de la contratada).`,
};
const est = document.getElementById('estado');
est.className = 'estado ' + D.estado;
est.innerHTML = icono(D.estado) + `<div><strong>${ESTADOS[D.estado].txt}</strong><span>${msgEstado[D.estado]}</span></div>`;

const kpis = [
  ['Demanda máxima', F0(D.max_kw), 'kW', `${NF(D.max_pct)} % de la contratada · ${fechaLarga(D.max_cuando)}`],
  D.margen_kw >= 0
    ? ['Margen hasta el límite', F0(D.margen_kw), 'kW', `Límite ${F0(D.limite)} kW (contratada + ${F0(D.tolerancia*100)} %)`]
    : ['Exceso sobre el límite', F0(-D.margen_kw), 'kW', `Límite ${F0(D.limite)} kW (contratada + ${F0(D.tolerancia*100)} %)`],
  ['Energía del período', NF(D.energia_kwh/1000, 1), 'MWh', `Demanda promedio ${F0(D.promedio_kw)} kW`],
  ['Factor de carga', NF(D.factor_carga), '%', 'Promedio ÷ máxima'],
  ['Intervalos sobre la contratada', F0(D.sobre_contratada), '', `De ${F0(D.lecturas - D.huecos)} lecturas válidas`],
  ['Intervalos sobre el límite', F0(D.excesos.length), '', D.excesos.length ? 'Generan alerta' : 'Sin alertas'],
  ['Huecos sin lectura', F0(D.huecos), '', `${NF(D.huecos / D.lecturas * 100)} % del período`],
];
document.getElementById('kpis').innerHTML = kpis.map(([l, v, u, d]) =>
  `<div class="kpi"><div class="l">${l}</div><div class="v">${v}<small>${u}</small></div><div class="d">${d}</div></div>`).join('');

// ---------- Utilidades de gráfico ----------
const NS = 'http://www.w3.org/2000/svg';
function el(tag, attrs={}, parent){ const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
function niceMax(v){ const p = Math.pow(10, Math.floor(Math.log10(v))); const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p; }
function ejeY(svg, y, w, m, ymax){
  const step = niceMax(ymax / 5); const g = el('g', {class:'grid'}, svg); const a = el('g', {class:'axis'}, svg);
  for (let v = 0; v <= ymax + 1e-9; v += step){
    el('line', {x1:m.l, x2:w-m.r, y1:y(v), y2:y(v)}, g);
    const t = el('text', {x:m.l-8, y:y(v)+4, 'text-anchor':'end'}, a); t.textContent = F0(v);
  }
}
function refs(svg, y, w, m){
  [['contratada', D.contratada, `Contratada ${F0(D.contratada)} kW`], ['limite', D.limite, `Límite +${F0(D.tolerancia*100)} % · ${F0(D.limite)} kW`]]
  .forEach(([cls, v, txt]) => { const g = el('g', {class:'ref ' + cls}, svg);
    el('line', {x1:m.l, x2:w-m.r, y1:y(v), y2:y(v)}, g);
    const t = el('text', {x:m.l+6, y:y(v)-6, 'text-anchor':'start'}, g); t.textContent = txt; });
}
function tooltip(cont){ const t = document.createElement('div'); t.className = 'tip'; cont.appendChild(t); return t; }
function ubicar(tip, cont, x, y){
  const w = tip.offsetWidth, cw = cont.clientWidth;
  tip.style.left = Math.min(Math.max(x + 14, 0), cw - w) + 'px';
  if (x + 14 + w > cw) tip.style.left = Math.max(x - w - 14, 0) + 'px';
  tip.style.top = Math.max(y - tip.offsetHeight - 10, 0) + 'px'; tip.style.opacity = 1;
}
const estadoDe = kw => kw > D.limite ? 'critico' : kw > D.contratada ? 'atencion' : 'normal';
const lineaEstado = kw => { const e = estadoDe(kw);
  return `<div class="e"><span class="dot" style="background:var(${ESTADOS[e].color})"></span>${ESTADOS[e].txt}</div>`; };

document.getElementById('ley1').innerHTML =
  `<span><span class="dot" style="background:var(--series)"></span>Demanda (kW)</span>` +
  `<span><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--text-2)" stroke-width="1.5" stroke-dasharray="6 4"/></svg>Potencia contratada</span>` +
  `<span><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--critical)" stroke-width="1.5" stroke-dasharray="6 4"/></svg>Límite de tolerancia</span>` +
  (D.excesos.length ? `<span><span class="dot" style="background:var(--critical)"></span>Intervalo sobre el límite</span>` : '');
document.getElementById('ley2').innerHTML = ['normal', 'atencion', 'critico'].map(e =>
  `<span><span class="dot" style="border-radius:2px;background:var(${ESTADOS[e].barra})"></span>${icono(e, 14)}${ESTADOS[e].txt}</span>`).join('');

// ---------- Curva de carga ----------
const PTS = D.puntos.map(([t, kw]) => [new Date(t).getTime(), kw]);
let rango = 'todo';
function dibujarCurva(){
  const cont = document.getElementById('curva'); cont.innerHTML = '';
  const fin = PTS[PTS.length - 1][0];
  const desde = rango === 'todo' ? PTS[0][0] : fin - Number(rango) * 86400000;
  const pts = PTS.filter(p => p[0] >= desde);
  const w = cont.clientWidth, h = Math.max(260, Math.min(380, w * 0.42)), m = {l:52, r:12, t:14, b:28};
  const svg = el('svg', {viewBox:`0 0 ${w} ${h}`, height:h, role:'img', 'aria-label':'Curva de carga en kW'}, cont);
  const vmax = Math.max(D.limite, ...pts.map(p => p[1] || 0)) * 1.08;
  const ymax = Math.ceil(vmax / niceMax(vmax / 5)) * niceMax(vmax / 5);
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  const x = t => m.l + (t - t0) / (t1 - t0 || 1) * (w - m.l - m.r);
  const y = v => m.t + (1 - v / ymax) * (h - m.t - m.b);
  ejeY(svg, y, w, m, ymax);

  // eje X: un rótulo por día (salteando si no entran)
  const ax = el('g', {class:'axis'}, svg);
  const dias = []; const d0 = new Date(t0); d0.setHours(0,0,0,0);
  for (let t = d0.getTime(); t <= t1; t += 86400000) if (t >= t0) dias.push(t);
  const cada = Math.max(1, Math.ceil(dias.length / Math.floor((w - m.l - m.r) / 52)));
  dias.forEach((t, i) => { if (i % cada) return;
    const tx = el('text', {x:x(t), y:h-8, 'text-anchor':'middle'}, ax);
    tx.textContent = new Date(t).toLocaleDateString('es-PY', {day:'2-digit', month:'2-digit'}); });

  refs(svg, y, w, m);

  // área suave + línea (cortada en huecos)
  let dLinea = '', dArea = '', tramo = [];
  const cerrar = () => { if (tramo.length) {
      dLinea += 'M' + tramo.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('L');
      dArea += `M${x(tramo[0][0]).toFixed(1)},${y(0)}L` + tramo.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('L') +
               `L${x(tramo[tramo.length-1][0]).toFixed(1)},${y(0)}Z`; }
    tramo = []; };
  pts.forEach(p => p[1] === null ? cerrar() : tramo.push(p)); cerrar();
  el('path', {d:dArea, fill:'var(--series-soft)'}, svg);
  el('path', {d:dLinea, fill:'none', stroke:'var(--series)', 'stroke-width':1.6, 'stroke-linejoin':'round'}, svg);

  // marcar excesos
  pts.filter(p => p[1] !== null && p[1] > D.limite).forEach(p =>
    el('circle', {cx:x(p[0]), cy:y(p[1]), r:4.5, fill:'var(--critical)', stroke:'var(--surface)', 'stroke-width':2}, svg));

  // máximo del período (rótulo directo)
  const pm = pts.reduce((a, b) => (b[1] ?? -1) > (a[1] ?? -1) ? b : a);
  el('circle', {cx:x(pm[0]), cy:y(pm[1]), r:4.5, fill: pm[1] > D.limite ? 'var(--critical)' : 'var(--series)', stroke:'var(--surface)', 'stroke-width':2}, svg);
  let ly = y(pm[1]) - 10;
  if ([D.contratada, D.limite].some(v => Math.abs(ly - 4 - y(v)) < 12)) ly = y(pm[1]) + 18;
  const lt = el('text', {x:x(pm[0]), y:ly, 'text-anchor': x(pm[0]) > w - 120 ? 'end' : x(pm[0]) < m.l + 60 ? 'start' : 'middle',
    class:'lbl', fill:'var(--text)'}, svg);
  lt.textContent = `Máx. ${F0(pm[1])} kW`;

  // capa de hover: cruz + tooltip
  const cruz = el('line', {y1:m.t, y2:h-m.b, stroke:'var(--text-3)', 'stroke-width':1, opacity:0}, svg);
  const punto = el('circle', {r:5, fill:'var(--series)', stroke:'var(--surface)', 'stroke-width':2, opacity:0}, svg);
  const hit = el('rect', {x:m.l, y:m.t, width:w-m.l-m.r, height:h-m.t-m.b, fill:'transparent'}, svg);
  const tip = tooltip(cont);
  const mover = ev => {
    const r = svg.getBoundingClientRect(); const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
    const t = t0 + (px - m.l) / (w - m.l - m.r) * (t1 - t0);
    let lo = 0, hi = pts.length - 1; while (hi - lo > 1){ const mid = (lo + hi) >> 1; pts[mid][0] < t ? lo = mid : hi = mid; }
    const p = Math.abs(pts[lo][0] - t) < Math.abs(pts[hi][0] - t) ? pts[lo] : pts[hi];
    const cx = x(p[0]); cruz.setAttribute('x1', cx); cruz.setAttribute('x2', cx); cruz.setAttribute('opacity', 1);
    const fecha = fechaLarga(p[0]);
    if (p[1] === null){ punto.setAttribute('opacity', 0);
      tip.innerHTML = `${fecha}<br><b>Sin lectura</b> <span style="color:var(--text-3)">(hueco)</span>`;
    } else { punto.setAttribute('cx', cx); punto.setAttribute('cy', y(p[1])); punto.setAttribute('opacity', 1);
      tip.innerHTML = `${fecha}<br><b>${NF(p[1])} kW</b> · ${NF(p[1] / D.contratada * 100)} % de la contratada` + lineaEstado(p[1]); }
    ubicar(tip, cont, cx, p[1] === null ? m.t + 40 : y(p[1]));
  };
  hit.addEventListener('mousemove', mover); hit.addEventListener('touchmove', mover, {passive:true});
  hit.addEventListener('mouseleave', () => { tip.style.opacity = 0; cruz.setAttribute('opacity', 0); punto.setAttribute('opacity', 0); });
}
const rangos = [['todo', 'Todo el período'], ['7', 'Últimos 7 días'], ['2', 'Últimas 48 h']];
document.getElementById('rango').innerHTML = rangos.map(([v, t]) =>
  `<button data-r="${v}" aria-pressed="${v === rango}">${t}</button>`).join('');
document.getElementById('rango').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return;
  rango = b.dataset.r; document.querySelectorAll('#rango button').forEach(x => x.setAttribute('aria-pressed', x === b)); dibujarCurva(); });

// ---------- Máximos diarios ----------
function dibujarDiario(){
  const cont = document.getElementById('diario'); cont.innerHTML = '';
  const w = cont.clientWidth, h = Math.max(220, Math.min(300, w * 0.32)), m = {l:52, r:12, t:14, b:28};
  const svg = el('svg', {viewBox:`0 0 ${w} ${h}`, height:h, role:'img', 'aria-label':'Demanda máxima diaria en kW'}, cont);
  const vmax = Math.max(D.limite, ...D.diario.map(d => d.kw)) * 1.08;
  const ymax = Math.ceil(vmax / niceMax(vmax / 5)) * niceMax(vmax / 5);
  const y = v => m.t + (1 - v / ymax) * (h - m.t - m.b);
  ejeY(svg, y, w, m, ymax);
  const n = D.diario.length, banda = (w - m.l - m.r) / n, bw = Math.max(4, Math.min(36, banda - 2));
  const tip = tooltip(cont); const ax = el('g', {class:'axis'}, svg);
  const cada = Math.max(1, Math.ceil(n / Math.floor((w - m.l - m.r) / 44)));
  D.diario.forEach((d, i) => {
    const cx = m.l + banda * (i + .5), top = y(d.kw), base = y(0), r = Math.min(4, bw / 2);
    const path = `M${cx-bw/2},${base}V${top+r}Q${cx-bw/2},${top} ${cx-bw/2+r},${top}H${cx+bw/2-r}Q${cx+bw/2},${top} ${cx+bw/2},${top+r}V${base}Z`;
    const bar = el('path', {d:path, fill:`var(${ESTADOS[d.estado].barra})`}, svg);
    if (i % cada === 0){ const t = el('text', {x:cx, y:h-8, 'text-anchor':'middle'}, ax); t.textContent = diaCorto(d.dia); }
    const hit = el('rect', {x:cx - banda/2, y:m.t, width:banda, height:h-m.t-m.b, fill:'transparent'}, svg);
    hit.addEventListener('mouseenter', () => { bar.setAttribute('opacity', .8);
      tip.innerHTML = `${new Date(d.dia + 'T00:00').toLocaleDateString('es-PY', {weekday:'long', day:'2-digit', month:'2-digit'})}<br>` +
        `<b>${NF(d.kw)} kW</b> a las ${d.hora} · ${NF(d.kw / D.contratada * 100)} %` + lineaEstado(d.kw);
      ubicar(tip, cont, cx, top); });
    hit.addEventListener('mouseleave', () => { bar.setAttribute('opacity', 1); tip.style.opacity = 0; });
  });
  refs(svg, y, w, m);
}

// ---------- Tablas ----------
const tabla = (cols, filas) => `<table><thead><tr>${cols.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>` +
  filas.map(f => `<tr>${f.map(c => `<td>${c}</td>`).join('')}</tr>`).join('') + '</tbody></table>';
const sumEx = document.querySelector('#det-excesos summary');
sumEx.textContent = D.excesos.length ? `Intervalos que superaron el límite (${D.excesos.length})` : 'Intervalos que superaron el límite (ninguno)';
document.getElementById('t-excesos').innerHTML = D.excesos.length
  ? tabla(['Fecha y hora', 'kW', '% contratada'], D.excesos.map(e => [fechaLarga(e.inicio), NF(e.kw), NF(e.pct)]))
  : '<p class="sub">No hubo intervalos por encima de ' + F0(D.limite) + ' kW en el período.</p>';
if (D.excesos.length) document.getElementById('det-excesos').open = true;
document.getElementById('t-top').innerHTML = tabla(['Fecha y hora', 'kW', '% contratada', 'Estado'],
  D.top.map(e => [fechaLarga(e.inicio), NF(e.kw), NF(e.pct), ESTADOS[estadoDe(e.kw)].txt]));
document.getElementById('t-diario').innerHTML = tabla(['Día', 'Hora del pico', 'kW', '% contratada', 'Estado'],
  D.diario.map(d => [new Date(d.dia + 'T00:00').toLocaleDateString('es-PY', {weekday:'short', day:'2-digit', month:'2-digit'}),
                     d.hora, NF(d.kw), NF(d.kw / D.contratada * 100), ESTADOS[d.estado].txt]));
document.getElementById('pie').textContent =
  `Fuente: Optimum.SM · Canal: ${D.canal} · ${F0(D.lecturas)} lecturas (${F0(D.huecos)} huecos). ` +
  `kW = valor del medidor (W) × ${NF(D.factor, 2)} ÷ 1000.`;

function dibujar(){ dibujarCurva(); dibujarDiario(); }
dibujar();
let rz; addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(dibujar, 120); });
</script>
</body>
</html>
"""


def resumen(res, pagina_rel):
    """Lo mínimo que necesita la portada para mostrar un suministro."""
    claves = ("nis", "nombre", "medidor", "contratada", "tolerancia", "limite", "desde", "hasta",
              "generado", "max_kw", "max_cuando", "max_pct", "margen_kw", "energia_kwh", "estado",
              "sobre_contratada", "huecos", "lecturas")
    r = {k: res[k] for k in claves}
    r["excesos"] = len(res["excesos"])
    r["diario"] = [[d["dia"], d["kw"]] for d in res["diario"]]
    r["pagina"] = pagina_rel
    return r


_ESTADO_TXT = {"normal": "Normal", "atencion": "Sobre la contratada (dentro de tolerancia)",
               "critico": "Supera la tolerancia"}


def _num(n, dec=0):
    """Formato paraguayo: 1.234,5"""
    return f"{n:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _mes_texto(aaaa_mm):
    try:
        a, m = aaaa_mm.split("-")
        return f"{_MESES[int(m) - 1]} {a}"
    except Exception:
        return html.escape(aaaa_mm)


def _mini_barras(diario, limite, contratada, ancho=260, alto=56):
    if not diario:
        return ""
    vmax = max([limite] + [kw for _, kw in diario]) * 1.05
    n = len(diario)
    banda = ancho / n
    bw = max(2.0, min(10.0, banda - 2))
    y = lambda v: alto - v / vmax * alto
    barras = []
    for i, (dia, kw) in enumerate(diario):
        color = "var(--critical)" if kw > limite else "var(--warning)" if kw > contratada else "var(--series)"
        x = banda * (i + 0.5) - bw / 2
        barras.append(f'<rect x="{x:.1f}" y="{y(kw):.1f}" width="{bw:.1f}" height="{alto - y(kw):.1f}" '
                      f'rx="1.5" fill="{color}"><title>{dia}: {_num(kw, 1)} kW</title></rect>')
    linea = (f'<line x1="0" x2="{ancho}" y1="{y(limite):.1f}" y2="{y(limite):.1f}" '
             f'stroke="var(--critical)" stroke-width="1.2" stroke-dasharray="4 3"/>')
    return (f'<svg viewBox="0 0 {ancho} {alto}" width="100%" height="{alto}" preserveAspectRatio="none" '
            f'role="img" aria-label="Demanda máxima diaria">{"".join(barras)}{linea}</svg>')


def generar_indice(resumenes, destino, historial=None, titulo="Monitoreo de potencia"):
    """
    Portada con una tarjeta por suministro.
    resumenes: lista de dicts de resumen(). historial: {nis: [(mes, ruta_relativa), ...]}
    """
    historial = historial or {}
    css = _PLANTILLA[_PLANTILLA.index("<style>"):_PLANTILLA.index("</style>") + 8]
    orden = {"critico": 0, "atencion": 1, "normal": 2}
    tarjetas = []
    for r in sorted(resumenes, key=lambda r: (orden.get(r["estado"], 3), r["nis"])):
        meses = historial.get(r["nis"], [])
        enlaces_hist = " · ".join(f'<a href="{html.escape(ruta)}">{_mes_texto(mes)}</a>' for mes, ruta in meses)
        margen = (f'Margen hasta el límite: <b>{_num(r["margen_kw"])} kW</b>' if r["margen_kw"] >= 0
                  else f'<b style="color:var(--critical-text)">Excede el límite en {_num(-r["margen_kw"])} kW</b>')
        tarjetas.append(f"""
    <article class="kpi suministro {r['estado']}">
      <div class="cab">
        <div><div class="l">NIS {html.escape(r['nis'])} · Medidor {html.escape(r['medidor'])}</div>
          <h2>{html.escape(r['nombre'] or 'Suministro ' + r['nis'])}</h2></div>
        <span class="pill {r['estado']}">{_ESTADO_TXT[r['estado']]}</span>
      </div>
      <div class="fila">
        <div><div class="l">Demanda máxima</div><div class="v">{_num(r['max_kw'])}<small>kW</small></div>
          <div class="d">{_num(r['max_pct'], 1)} % de la contratada</div></div>
        <div><div class="l">Contratada / límite</div><div class="v">{_num(r['contratada'])}<small>/ {_num(r['limite'])} kW</small></div>
          <div class="d">Tolerancia {_num(r['tolerancia'] * 100)} %</div></div>
      </div>
      <div class="d">Máximos diarios del mes</div>
      {_mini_barras(r['diario'], r['limite'], r['contratada'])}
      <div class="d">{margen} · Intervalos sobre el límite: <b>{r['excesos']}</b></div>
      <div class="d">Período {html.escape(r['desde'])} a {html.escape(r['hasta'])}</div>
      <a class="boton" href="{html.escape(r['pagina'])}">Ver detalle →</a>
      {f'<div class="d hist">Historial mensual: {enlaces_hist}</div>' if enlaces_hist else ''}
    </article>""")

    criticos = sum(1 for r in resumenes if r["estado"] == "critico")
    aviso = (f'<div class="estado critico"><div><strong>{criticos} suministro(s) superan la tolerancia</strong>'
             f'<span>Revisá el detalle de los marcados en rojo.</span></div></div>' if criticos else
             '<div class="estado normal"><div><strong>Todos los suministros dentro de la tolerancia</strong>'
             f'<span>{len(resumenes)} suministro(s) monitoreado(s).</span></div></div>')
    pagina = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(titulo)}</title>
{css}
<style>
.suministros{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}
.suministro{{display:flex;flex-direction:column;gap:8px;border-left-width:6px;padding:14px 16px}}
.suministro.normal{{border-left-color:var(--good)}} .suministro.atencion{{border-left-color:var(--warning)}}
.suministro.critico{{border-left-color:var(--critical)}}
.suministro h2{{font-size:17px;margin:2px 0 0}}
.cab{{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}}
.fila{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.pill{{font-size:11px;font-weight:650;padding:3px 8px;border-radius:99px;white-space:nowrap}}
.pill.normal{{color:var(--good-text);background:color-mix(in srgb,var(--good) 14%,transparent)}}
.pill.atencion{{color:var(--warning-text);background:color-mix(in srgb,var(--warning) 18%,transparent)}}
.pill.critico{{color:var(--critical-text);background:color-mix(in srgb,var(--critical) 14%,transparent)}}
.boton{{align-self:flex-start;margin-top:4px;background:var(--accent);color:#fff;text-decoration:none;
  padding:7px 14px;border-radius:7px;font-weight:600;font-size:13px}}
:root[data-theme="dark"] .boton{{color:#1a1a19}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]) .boton{{color:#1a1a19}}}}
.hist a{{color:var(--accent)}}
</style>
</head>
<body>
<div class="wrap">
  <header><div><h1>{html.escape(titulo)}</h1>
    <div class="sub">Demanda de potencia según Optimum.SM, comparada con la potencia contratada y su tolerancia.</div></div>
    <div class="sub">Actualizado: {datetime.now():%d/%m/%Y %H:%M}</div></header>
  {aviso}
  <section class="suministros">{''.join(tarjetas)}
  </section>
  <footer>Se actualiza automáticamente todos los días.</footer>
</div>
</body>
</html>
"""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina, encoding="utf-8")
    return destino


# -----------------------------------------------------------------------------
# Alertas
# -----------------------------------------------------------------------------
def _cargar_estado():
    try:
        return json.loads(ARCHIVO_ESTADO_ALERTAS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guardar_estado(estado):
    ARCHIVO_ESTADO_ALERTAS.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO_ESTADO_ALERTAS.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")


def _texto_alerta(res, nuevos):
    lineas = [
        f"ALERTA: el suministro NIS {res['nis']} superó la tolerancia de potencia.",
        "",
        f"Potencia contratada: {res['contratada']:,.0f} kW",
        f"Límite (+{res['tolerancia']*100:.0f} %): {res['limite']:,.0f} kW",
        f"Demanda máxima del período: {res['max_kw']:,.1f} kW ({res['max_pct']:.1f} %) el {res['max_cuando']}",
        "",
        f"Intervalos nuevos sobre el límite: {len(nuevos)}",
    ]
    for e in nuevos[:20]:
        lineas.append(f"  {e['inicio']}  {e['kw']:,.1f} kW  ({e['pct']:.1f} %)")
    if len(nuevos) > 20:
        lineas.append(f"  ... y {len(nuevos) - 20} más")
    lineas += ["", f"Período analizado: {res['desde']} a {res['hasta']}", f"Medidor: {res['medidor']}"]
    if URL_SITIO:
        lineas += ["", f"Ver detalle: {URL_SITIO.rstrip('/')}/perfil_{res['nis']}.html"]
    return "\n".join(lineas)


def _ventana(titulo, texto):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        messagebox.showwarning(titulo, texto, parent=root)
        root.destroy()
    except Exception as e:  # noqa: BLE001
        log(f"   (No se pudo mostrar la ventana de alerta: {e})")


def _email(asunto, cuerpo, adjunto=None):
    cfg = ALERTA_EMAIL
    if cfg["metodo"] == "outlook":
        import win32com.client  # pip install pywin32
        correo = win32com.client.Dispatch("Outlook.Application").CreateItem(0)
        correo.To = "; ".join(cfg["para"])
        correo.Subject = asunto
        correo.Body = cuerpo
        if adjunto:
            correo.Attachments.Add(str(adjunto))
        correo.Send()
    else:
        import smtplib
        from email.message import EmailMessage
        import keyring
        clave = keyring.get_password(cfg["smtp_servicio_credencial"], cfg["smtp_clave_credencial"])
        msg = EmailMessage()
        msg["From"] = cfg["smtp_remitente"] or cfg["smtp_usuario"]
        msg["To"] = ", ".join(cfg["para"])
        msg["Subject"] = asunto
        msg.set_content(cuerpo)
        if adjunto:
            msg.add_attachment(Path(adjunto).read_bytes(), maintype="text", subtype="html",
                               filename=Path(adjunto).name)
        with smtplib.SMTP(cfg["smtp_servidor"], cfg["smtp_puerto"], timeout=30) as s:
            s.starttls()
            if cfg["smtp_usuario"]:
                s.login(cfg["smtp_usuario"], clave or "")
            s.send_message(msg)


def revisar_alertas(res, pagina=None):
    """
    Avisa solo por intervalos sobre el límite que todavía no se hayan avisado.
    Devuelve el texto de la alerta si hubo una nueva (si no, None).
    """
    if not res["excesos"]:
        log(f"✅ Sin excesos: máximo {res['max_kw']:,.1f} kW ({res['max_pct']:.1f} % de la contratada), "
            f"límite {res['limite']:,.0f} kW.")
        return None

    estado = _cargar_estado()
    ya_avisados = set(estado.get(res["nis"], []))
    nuevos = [e for e in res["excesos"] if e["inicio"] not in ya_avisados]
    if not nuevos:
        log(f"⚠️  Hay {len(res['excesos'])} intervalo(s) sobre el límite, ya avisados antes.")
        return None

    asunto = f"ALERTA potencia NIS {res['nis']}: {res['max_kw']:,.0f} kW (límite {res['limite']:,.0f} kW)"
    texto = _texto_alerta(res, nuevos)
    log("🚨 " + asunto)
    print(texto, flush=True)

    if ALERTA_EMAIL["activar"]:
        try:
            _email(asunto, texto, pagina)
            log(f"   Correo enviado a: {', '.join(ALERTA_EMAIL['para'])}")
        except Exception as e:  # noqa: BLE001
            log(f"   No se pudo enviar el correo: {e}")
    if ALERTA_VENTANA:
        _ventana("Alerta de potencia - Optimum", texto)

    estado[res["nis"]] = sorted(ya_avisados | {e["inicio"] for e in nuevos})
    _guardar_estado(estado)
    return texto


# -----------------------------------------------------------------------------
# Punto de entrada
# -----------------------------------------------------------------------------
def procesar(archivo_excel, nis=None, abrir=ABRIR_PAGINA_AL_TERMINAR, destino=None,
             enlace_volver=None, alertar=True):
    archivo_excel = Path(archivo_excel)
    registros, info = leer_perfil(archivo_excel)
    nis = str(nis or info["punto"] or "").strip()
    if nis not in SUMINISTROS:
        raise KeyError(f"El NIS {nis} no está configurado en SUMINISTROS (analisis_perfil.py).")
    cfg = dict(SUMINISTROS[nis], nis=nis)

    log(f"Analizando {archivo_excel.name}: {len(registros)} lecturas")
    res = analizar(registros, info, cfg)
    pagina = generar_html(res, Path(destino) if destino else CARPETA_REPORTES / f"perfil_{nis}.html",
                          enlace_volver)
    log(f"Página generada: {pagina}")
    res["alerta_nueva"] = revisar_alertas(res, pagina) if alertar else None
    if abrir:
        webbrowser.open(pagina.as_uri())
    return res, pagina


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Uso: python analisis_perfil.py archivo.xlsx [NIS]")
    procesar(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
