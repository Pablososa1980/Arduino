# Monitoreo de potencia: Optimum.SM → panel web (Hostinger)

```
PC con acceso a la red de ANDE                      Hostinger (tu dominio .com)
┌──────────────────────────────────┐   HTTPS   ┌────────────────────────────────┐
│ orquestador_diario.py (diario)   │ ────────► │ Panel PHP + MySQL (carpeta web/)│
│  ├ descargar_perfil_carga.py     │ curl.exe  │  usuarios y roles, histórico,   │
│  │  (Optimum 10.1.0.126)         │ + token   │  suministros, alertas por correo│
│  └ analisis_perfil.py (lee Excel)│           └────────────────────────────────┘
└──────────────────────────────────┘
```

- Todos los días, la PC descarga de Optimum el Perfil de Carga de cada suministro activo y envía las lecturas al panel.
- El panel calcula los kW (valor × factor ÷ 1000), los compara con la potencia contratada y su tolerancia, guarda el histórico y avisa por correo si se supera el límite.
- La subida usa `curl.exe` porque atraviesa el proxy corporativo de ANDE con la sesión de Windows. Es el mismo método que ya funciona en el panel SEP2. Por FTP, en cambio, no pasaría.

## Archivos

| Archivo | Para qué |
|---|---|
| `orquestador_diario.py` | El script diario. Arriba de todo: `WEB["url_base"]` (la dirección del panel). |
| `descargar_perfil_carga.py` | La automatización de Optimum. También se usa sola, desde Spyder. |
| `analisis_perfil.py` | Lee el Excel de Optimum. También genera un HTML local si se usa solo. |
| `web/` | El panel para subir a Hostinger. Las instrucciones están en `web/LEEME.md`. |

## Puesta en marcha

1. **Panel:** instalalo en Hostinger siguiendo `web/LEEME.md`: base de datos, archivos, administrador, suministro y token.
2. **Dependencias en la PC** (consola de Anaconda):
   ```
   pip install playwright keyring
   ```
3. **Dirección del panel:** en `orquestador_diario.py`, poné `WEB["url_base"]`.
4. **Contraseña y token:** guardá la contraseña de Optimum (si no está) y el token del panel:
   ```
   python orquestador_diario.py --configurar
   ```
5. **Prueba a mano:**
   ```
   python orquestador_diario.py
   ```
   Después revisá el panel.
6. **Tarea diaria:** se crea a las 07:15; para otra hora, agregá `HH:MM` al final:
   ```
   python orquestador_diario.py --crear-tarea
   ```

## Cargar histórico

Para llenar el panel con meses anteriores, una sola vez:

- Desde Optimum, de a un mes por vez:
  ```
  python orquestador_diario.py --mes 2026-10
  python orquestador_diario.py --mes 2026-09
  ```
- Con un Excel que ya tengas descargado:
  ```
  python orquestador_diario.py --archivo perfil_1379190_20261120.xlsx --nis 1379190
  ```

## Agregar un suministro

En el panel: *Suministros → Agregar suministro*. Cargás el NIS, el factor, la potencia contratada y la tolerancia. Desde la corrida siguiente, el script lo descarga solo; no hace falta tocar ningún archivo.

### Modelos de medidor

| Medidor | Prefijo del medidor | Canal del MDC | Unidad del Excel |
|---|---|---|---|
| EGM (por defecto) | `EGM` | `Sum Li Active Power + (QI+QIV) (last average 1)- 0 x` | W (potencia) |
| Actaris ACE6000 | inicio del número de serie (p. ej. `0175`) o `Todos` | `Sum Li Active Power + (QI+QIV) (time integral 5) - 0` | Wh por intervalo (energía) |

El ACE6000 no guarda potencia sino la energía de cada intervalo de 15 minutos. El script la convierte a potencia media del intervalo antes de enviarla: W = Wh ÷ 0,25 h = Wh × 4 (2,9 Wh → 11,6 W). Después se aplica el factor como siempre: kW = W × factor ÷ 1000. La conversión es automática, según la columna *Unidad* del Excel. Los dos canales aparecen como sugerencia en el formulario del suministro.

La primera vez, probalo solo con ese suministro: `python orquestador_diario.py --nis NIS_NUEVO`.

## Cosas a saber

- **La PC tiene que estar encendida y con sesión iniciada** a la hora de la tarea. La contraseña y el token guardados pertenecen a tu usuario de Windows, y Optimum solo se alcanza desde la red de ANDE.
- **Días 1 a 5 de cada mes:** además del mes en curso, se reenvía el mes anterior completo, para no perder sus últimas horas. Es seguro: el panel no duplica lecturas.
- **Registros:** `logs/orquestador_AAAA-MM-DD.log` (se guardan 60 días) y `logs/tarea_programada.log`.
- **Errores:** si algo falla, el script termina con código 1 y el detalle queda en el log. En el panel, *Auditoría* muestra qué envíos llegaron.
- **Otras opciones:**
  - `--sin-subir`: descarga pero no envía.
  - `--sin-descargar`: reenvía el último Excel.
  - `--nis N`: procesa un solo suministro.
