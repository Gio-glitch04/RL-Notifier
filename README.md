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
  por ejemplo ruedas de pase como Ruinator o Haunted Hoss. Marca si están en la tienda hoy, cuándo los
  viste por última vez (según tu historial) y tiene **+ Alerta** para crear una alerta por nombre exacto
  (puedes agregar un color). Filtro "Nunca vistos en la tienda" para buscar rarezas.
  Se descarga solo la primera vez y luego una vez por semana; también con el botón **Actualizar catálogo**.
  Fuente: rl.source.gs (15 descargas por actualización, con pausa entre cada una).
- **Historial**: todo lo que se vio alguna vez, con primera y última vez y cuántas veces volvió.
- **Alertas**: crea, edita, desactiva o borra alertas (sin límite). Cada alerta puede filtrar por nombre,
  color, tipo, rareza, tienda y precio máximo; todo lo que completes tiene que coincidir.
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

## Archivos

- `notificador.py`: servidor web, base de datos, alertas, avisos y horario.
- `web/`: la página (HTML, CSS y JS).
- `rl_tienda.py`: lectura de las tiendas (itemshop.gg con RL Portal de respaldo, y fortnite-api.com).
  Sigue funcionando solo, en consola: `python rl_tienda.py --listar`, `--una-vez`, `--probar`.
- `tienda.db`: base de datos (se crea sola). Bórrala para empezar de cero.
- `config.json`: configuración (no se sube a git porque guarda el webhook y el correo; si falta, se crea
  copiando `config.ejemplo.json`, que es la plantilla sin datos privados). La `lista_de_deseos` se importó como alertas la primera vez;
  desde entonces las alertas se manejan en la página.
