# Monitoreo de potencia: Optimum.SM → Hostinger

Todos los días, en tu PC (con acceso a la red de ANDE):

1. `descargar_perfil_carga.py` entra a Optimum.SM y baja el Perfil de Carga (Excel) de cada suministro.
2. `analisis_perfil.py` calcula la demanda en kW (valor × factor), la compara con la potencia contratada y su tolerancia, y arma las páginas.
3. `orquestador_diario.py` coordina todo, avisa si hay excesos y sube las páginas a Hostinger por FTPS.

## Archivos

| Archivo | Para qué |
|---|---|
| `orquestador_diario.py` | El script que corre todos los días. Arriba de todo está la configuración de Hostinger. |
| `analisis_perfil.py` | `SUMINISTROS`: NIS, factor, potencia contratada y tolerancia. También la configuración de alertas por correo. |
| `descargar_perfil_carga.py` | La automatización de Optimum (también se puede usar sola, desde Spyder). |
| `ejecutar_orquestador.bat` | Lo que ejecuta el Programador de tareas. Activa Anaconda si existe. |
| `crear_tarea_programada.bat` | Crea la tarea diaria (doble clic, una sola vez). |

## Puesta en marcha (una sola vez)

1. **Instalar dependencias** (en la consola de Anaconda):
   ```
   pip install playwright keyring
   ```
   Si querés alertas por Outlook, instalá también `pywin32`.

2. **Hostinger, en hPanel:**
   - En *Archivos → Cuentas FTP*, anotá el **host**, el **usuario** y el **puerto** (21). Si no recordás la contraseña FTP, cambiala ahí.
   - Recomendado: en *Seguridad → Directorios protegidos con contraseña*, protegé la carpeta `public_html/potencia` con usuario y contraseña. Las páginas muestran datos de consumo de un cliente y no deberían quedar públicas. Ya incluyen `noindex` para que Google no las indexe, pero eso no impide que alguien con el enlace las vea.

3. **Completar la configuración** al principio de `orquestador_diario.py`: `HOSTINGER` (host, usuario, carpeta) y `URL_SITIO`.

4. **Guardar las contraseñas y probar la conexión:**
   ```
   python orquestador_diario.py --configurar
   ```
   La contraseña de Optimum se reutiliza si ya la guardó el script del MDC. La del FTP se guarda en el Administrador de credenciales de Windows y nunca queda escrita en los archivos.

5. **Prueba completa a mano:**
   ```
   python orquestador_diario.py
   ```
   Al terminar debería verse en `https://tudominio.com/potencia/`.

6. **Programar la tarea:**
   ```
   python orquestador_diario.py --crear-tarea
   ```
   Genera `ejecutar_orquestador.bat` con tu Python y crea la tarea diaria a las 07:15. Para otra hora: `--crear-tarea 06:30`. Desde la consola de Spyder: `%run orquestador_diario.py --crear-tarea`.
   (Si pudiste bajar `crear_tarea_programada.bat`, el doble clic hace lo mismo.)

## Cosas a saber

- **La PC tiene que estar encendida y con tu sesión iniciada** a la hora de la tarea. La contraseña guardada pertenece a tu usuario de Windows y Optimum solo se alcanza desde la red de ANDE. Si la PC estaba apagada, en el *Programador de tareas* (propiedades de la tarea → *Configuración*) marcá "Ejecutar la tarea lo antes posible si no se ejecutó a la hora programada".
- **El día 1 de cada mes** se baja además el mes anterior completo, que queda en el historial (`historial/perfil_<NIS>_<AAAA-MM>.html`).
- **Alertas:** si algún intervalo de 15 minutos supera contratada × (1 + tolerancia):
  - Al terminar la corrida aparece un aviso en la PC.
  - Si activás `ALERTA_EMAIL` en `analisis_perfil.py`, se manda también un correo con el enlace a la página.
  - Cada exceso se avisa una sola vez (`reportes/alertas_enviadas.json`).
- **Registros:** `logs/orquestador_AAAA-MM-DD.log`, que se guardan 60 días, y `logs/tarea_programada.log`.
- **Otras opciones:**
  - `--sin-subir`: hace todo menos la subida.
  - `--sin-descargar`: usa el último Excel ya bajado.
  - `--solo-subir`: solo sube a Hostinger lo que ya está generado.
- **Agregar otro suministro:** sumalo a `SUMINISTROS` en `analisis_perfil.py`, con su NIS, factor, contratada y tolerancia. Aparece solo en la portada.
