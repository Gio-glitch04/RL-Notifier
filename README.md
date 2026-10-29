# Notificador de tiendas: Rocket League + Rocket League en Fortnite

Reemplazo personal de RL Garage que funciona solo en tu PC. Muestra la tienda de Rocket League
y la sección de vehículos de Fortnite en una página local, guarda el historial y te avisa cuando
aparece algo de tus alertas.

Solo necesita Python 3 (nada que instalar con pip).

## Cómo usarlo

1. Doble clic en `iniciar_notificador.bat`.
2. Se abre el navegador en <http://127.0.0.1:8765>. Deja abierta la ventana negra: mientras siga abierta,
   el notificador revisa la tienda solo.

En la página:

- **Rocket League** y **Rocket League en Fortnite**: la tienda actual, con imagen, color, rareza, tipo,
  precio y tiempo restante. Buscador y filtros arriba. Los artículos que coinciden con una alerta
  tienen borde amarillo y la marca **★ Alerta**.
- **Catálogo**: todos los artículos de Rocket League (unos 9.300), aunque nunca hayan salido en la tienda,
  por ejemplo ruedas de pase como Ruinator o Haunted Hoss. Cada tarjeta muestra:
  - **Origen**: Rocket Pass (cuál y en qué nivel), pack DLC, tienda de esports, recompensa competitiva,
    exclusivo de plataforma o torneos. Si no figura en ninguna lista dice "desconocido" (suelen ser cajas,
    drops, eventos o lotes de la tienda).
  - **Última vez en tienda**, con precio y cuántas veces apareció.
  Clic en la imagen o el nombre abre la **ficha**: colores vistos, cada paso por la tienda (fecha, precio,
  sección) y lo que registró este notificador. **+ Alerta** crea una alerta por nombre exacto (puedes agregar un color).
  Filtros por tipo, rareza, origen, Rocket Pass y "Nunca vistos en la tienda".
  Orden por nombre (A-Z / Z-A), rareza (de Common a Black Market o al revés; Limited, Premium y Legacy
  siempre al final) o precio (último precio conocido en la tienda; los que no tienen precio, al final).
  La página recuerda el orden. "+ Alerta" abre el formulario en una ventana: al guardar o cancelar, el
  catálogo queda en el mismo lugar, con los mismos artículos cargados.
- **Historial**: todo lo que se vio alguna vez, con primera y última vez y cuántas veces volvió.
- **Alertas**: crea, edita, desactiva o borra alertas (sin límite). Cada alerta puede filtrar por nombre,
  color, categoría (Ruedas, Carrocería, Calcomanía…), rareza, tienda y precio máximo; todo lo que
  completes tiene que coincidir. La categoría distingue, por ejemplo, las ruedas Dodge Viper GTS-R de la
  carrocería del mismo nombre, y vale igual para la tienda de RL, la de Fortnite y el catálogo.
  Por defecto una alerta vale para **ambas tiendas** (Rocket League y Rocket League en Fortnite).
  Cada alerta muestra la imagen del artículo (de la tienda, el historial o el catálogo) y se pueden ver
  como **tarjetas** o como **lista**; la página recuerda la elección.
  El botón **+ Alerta** de cada tarjeta la crea ya rellenada. Con **Nombre exacto**, "Ruinator" no
  coincide con "Ruinator: Inverted".
- **Revisar ahora**: revisa la tienda en el momento.
- **Probar aviso**: manda un aviso de prueba por todos los canales configurados.

## Cuándo revisa

- Al abrir el notificador, después cada `minutos_entre_revisiones` (60 por defecto).
- Además, todos los días a las `hora_revision_fija` (16:05) en la zona `zona_horaria_gmt` (-3).

Cada alerta avisa **una sola vez** por artículo. Si el artículo sale de la tienda y vuelve más adelante,
avisa de nuevo.

## Avisos (en `config.json`)

| Canal | Qué poner | Si está vacío |
|---|---|---|
| Windows | `"avisos_windows": true` | — |
| Discord | `"discord_webhook_url"`: en tu servidor de Discord, *Editar canal → Integraciones → Webhooks → Nuevo webhook → Copiar URL* | desactivado |
| Correo | `"correo_smtp"`: `usuario` (tu Gmail), `contrasena_aplicacion` (crear en myaccount.google.com → Seguridad → Contraseñas de aplicaciones, requiere verificación en dos pasos), `para` (a quién avisar) | desactivado |

Los secretos van **solo** en `config.json`. Después de cambiarlo no hace falta reiniciar: se lee en cada revisión
(salvo el `puerto`).

`"avisar_todo_lo_nuevo": true` además manda una notificación de Windows con el resumen de lo nuevo en cada tienda.

## De dónde salen los datos del catálogo

| Dato | Fuente | Cada cuánto |
|---|---|---|
| Lista de artículos, imagen, rareza | rl.source.gs (15 descargas) | semanal o botón **Actualizar catálogo** |
| Origen: Rocket Pass y otras listas | wiki de Rocket League en Fandom (API, unos 25 pedidos) | semanal |
| Origen: packs DLC | rl.source.gs/packs | semanal |
| Veces, última vez, precio y colores en la tienda | itemshop.gg (1 pedido) | diario |
| Historial detallado de un artículo | itemshop.gg (1 pedido) | al abrir su ficha (se guarda 12 h) |

Límites: el historial de itemshop.gg empieza en septiembre de 2026 (antes de eso no hay "última vez").
La wiki llega hasta la temporada 24 del Rocket Pass; si aún no cargó una temporada nueva, esos artículos
salen como "desconocido". Los lotes de la tienda no figuran como origen.

## Archivos

- `notificador.py`: servidor web, base de datos, alertas, avisos y horario.
- `web/`: la página (HTML, CSS y JS).
- `origenes.py`: origen e historial de tienda para el catálogo (wiki, itemshop.gg, packs).
- `rl_tienda.py`: lectura de las tiendas (itemshop.gg con RL Portal de respaldo, y fortnite-api.com).
  Sigue funcionando solo, en consola: `python rl_tienda.py --listar`, `--una-vez`, `--probar`.
- `tienda.db`: base de datos (se crea sola). Bórrala para empezar de cero.
- `config.json`: configuración (no se sube a git porque guarda el webhook y el correo; si falta, se crea
  copiando `config.example.json`, que es la plantilla sin datos privados). La `lista_de_deseos` se importó como alertas la primera vez;
  desde entonces las alertas se manejan en la página.
