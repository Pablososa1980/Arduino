# Panel de Potencia — instalación en Hostinger

Panel web en PHP 8 + MySQL (sin frameworks ni librerías externas, sin CDN), pensado para
un plan compartido de Hostinger. Está armado sobre la misma base del panel SEP2.

## Qué hace

- **Usuarios y roles**
  - **Administrador:** ve todo y administra usuarios, suministros y tokens.
  - **Consulta:** solo ve los suministros que se le asignan y, si se le habilita, descarga el Excel.
- **Suministros:** se agregan desde el panel, con su NIS, nombre, prefijo del medidor y canal de Optimum. El script diario los toma solo.
- **Condiciones contractuales con vigencia:** factor, potencia contratada y tolerancia, con fecha "vigente desde". Si cambian, se agrega una condición nueva: los meses anteriores se siguen evaluando con la de su momento, y todo el histórico se recalcula solo.
- **Histórico:** se guardan las lecturas de 15 minutos en crudo (W). Con eso hay resumen mensual, detalle de cualquier mes, máximos diarios y excesos.
- **Alertas:** cada intervalo por encima de contratada × (1 + tolerancia) queda registrado y se avisa por correo una sola vez a los usuarios marcados con "Recibir alertas" que pueden ver ese suministro.
- **Auditoría:** ingresos, cambios, descargas y envíos del script.
- **API con token**, usada por `orquestador_diario.py`:
  - `GET api/supplies.php`: lista de suministros activos.
  - `POST api/readings-import.php`: lecturas en formato `optimum-readings-v1`. Es idempotente: reenviar el mismo período no duplica nada.

## Instalación (una sola vez)

1. **Sitio y dominio:** en hPanel, agregá el sitio con el dominio nuevo (sitio vacío), activá el SSL y **Forzar HTTPS**.
2. **Base de datos:** en *Bases de datos → Administración de MySQL*, creá una base y un usuario y anotá los nombres, que Hostinger forma como `u123456789_...`.
3. **Tablas:** en *phpMyAdmin*, elegí esa base → pestaña **Importar** → subí `sql/schema.sql`.
4. **Archivos:** en el *Administrador de archivos*, dentro de `public_html` del sitio, subí el contenido de esta carpeta `web/`: `index.php`, `.htaccess`, `api/`, `app/`, `assets/`, `config/`, `pages/` y `sql/`. Lo más simple es subir el `.zip` y usar "Extraer". Borrá la página por defecto de Hostinger si quedó.
5. **Configuración:**
   - En `config/`, copiá `config.example.php` como **`config.php`** y completá:
     - los datos de la base;
     - `base_url`, con tu dominio;
     - una `setup_key` larga y aleatoria.
   - `config.php` nunca va a GitHub.
6. **Primer administrador:** entrá a `https://tudominio.com`. Aparece la pantalla de instalación: poné la `setup_key` y creá tu usuario.
7. **Primer suministro:** el panel te lleva a "Nuevo suministro". Cargá el NIS **1379190**, el factor **1815,78**, la potencia contratada **1520** y la tolerancia **10**, con la fecha desde la que rige.
8. **Token del script:** en *Tokens → Generar token*, copiá el token. Se muestra una sola vez.
9. **PC del script:** en `orquestador_diario.py`, poné `WEB["url_base"] = "https://tudominio.com"` y después ejecutá:
   ```
   python orquestador_diario.py --configurar
   ```
   Te pide el token y prueba la conexión.

## Alertas por correo

1. En hPanel → *Correos*, creá la casilla `alertas@tudominio.com`.
2. En `config.php`, poné `'mail' => ['enabled' => true, 'from' => 'alertas@tudominio.com', ...]`.
3. En *Usuarios*, marcá "Recibir alertas" en quien corresponda. El usuario necesita un correo cargado.

Los correos se envían con `mail()` del hosting. **Está pendiente de probar en Hostinger:** la primera vez, revisá que llegue y que no caiga en spam.

## Seguridad

- **Permisos:** se validan en el servidor. Un usuario de consulta que pegue la URL de un suministro ajeno, o la de descarga sin permiso, recibe un 403.
- **Formularios y contraseñas:** todos los formularios llevan CSRF. Las contraseñas se guardan con `password_hash`.
- **Intentos de ingreso:** tras 10 intentos fallidos desde una misma IP, se bloquea por 15 minutos.
- **Carpetas internas:** `.htaccess` bloquea `app/`, `config/`, `pages/` y `sql/`, fuerza HTTPS y pide a los buscadores que no indexen el sitio.
- **Tokens:** de los tokens se guarda solo el hash SHA-256. Si se pierde uno, se revoca y se genera otro.
- **Administradores:** el panel no deja quitar el rol ni desactivar al último administrador activo.
