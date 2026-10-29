"""
Notificador con interfaz web local (tipo RL Garage) para la tienda de Rocket League
y la sección de vehículos de Fortnite.

- Guarda los artículos y su historial en tienda.db (SQLite).
- Sirve una página en http://127.0.0.1:<puerto> (por defecto 8765) con la tienda,
  filtros y la gestión de alertas.
- Revisa cada N minutos y además a una hora fija del día, en un hilo de fondo.
- Avisa por notificación de Windows, Discord (webhook) y correo (opcional).

Uso:
  python notificador.py                 -> arranca el servidor y abre el navegador
  python notificador.py --sin-navegador -> arranca sin abrir el navegador

Solo usa la biblioteca estándar de Python. Las fuentes de datos están en rl_tienda.py.
"""

import json
import re
import smtplib
import sqlite3
import sys
import threading
import unicodedata
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import rl_tienda as fuentes
from rl_tienda import log

CARPETA = Path(__file__).resolve().parent
ARCHIVO_DB = CARPETA / "tienda.db"
CARPETA_WEB = CARPETA / "web"
ARCHIVOS_WEB = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/estilos.css": ("estilos.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
TIENDAS = ("Rocket League", "Fortnite")
CAMPOS_TEXTO = ("nombre", "color", "tipo", "rareza")

# Para importar la lista de deseos: a qué campo va cada palabra
PINTURAS = {"titanium white", "black", "crimson", "sky blue", "cobalt", "burnt sienna", "saffron", "lime",
            "forest green", "orange", "purple", "pink", "grey", "gold", "rose", "white"}
# Catálogo completo de Rocket League: rl.source.gs publica un índice JSON por categoría
# (15 descargas por actualización, con pausa entre cada una; su robots.txt solo excluye /api/).
URL_CATALOGO = "https://rl.source.gs/items/{}/index.json"
URL_CATALOGO_BASE = "https://rl.source.gs"
CATEGORIAS = {
    "bodies": "Body", "wheels": "Wheels", "decals": "Decal", "goal-explosions": "Goal Explosion",
    "rocket-boosts": "Rocket Boost", "trails": "Trail", "toppers": "Topper", "antennas": "Antenna",
    "engine-audio": "Engine Audio", "paint-finishes": "Paint Finish", "player-anthems": "Player Anthem",
    "player-banners": "Player Banner", "avatar-borders": "Avatar Border", "blueprints": "Blueprint",
    "crates": "Crate",
}
# Rareza del catálogo -> nombre y color como los muestra la tienda
RAREZAS_CATALOGO = {
    "Common": ("Common", "#b8bcc4"), "Uncommon": ("Uncommon", "#7fc4f5"), "Rare": ("Rare", "#4c8cff"),
    "VeryRare": ("Very Rare", "#9b5cf0"), "Import": ("Import", "#e0413e"), "Exotic": ("Exotic", "#ffd24a"),
    "BlackMarket": ("Black Market", "#d63cff"), "Limited": ("Limited", "#f08d3a"),
    "Premium": ("Premium", "#38d39f"), "Legacy": ("Legacy", "#9aa3b2"),
}
DIAS_ENTRE_CATALOGOS = 7
RAREZAS = {"common", "uncommon", "rare", "very rare", "import", "exotic", "black market", "limited",
           "legendary", "premium"}


def ahora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fecha(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def normalizar(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# ---------- base de datos ----------

ESQUEMA = """
CREATE TABLE IF NOT EXISTS articulos (
    id TEXT PRIMARY KEY, tienda TEXT, seccion TEXT, nombre TEXT, tipo TEXT, color TEXT, color_hex TEXT,
    rareza TEXT, rareza_color TEXT, precio TEXT, precio_num INTEGER, moneda TEXT, imagen TEXT, url TEXT,
    hasta TEXT, primera_vez TEXT, ultima_vez TEXT, aparicion TEXT, en_tienda INTEGER DEFAULT 0,
    apariciones INTEGER DEFAULT 0, mezcla TEXT DEFAULT '', orden INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT DEFAULT '', color TEXT DEFAULT '',
    tipo TEXT DEFAULT '', rareza TEXT DEFAULT '', tienda TEXT DEFAULT '', precio_max INTEGER,
    activa INTEGER DEFAULT 1, creada TEXT, exacto INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS catalogo (
    id TEXT PRIMARY KEY, producto_id INTEGER, nombre TEXT, nombre_norm TEXT, variante TEXT, tipo TEXT,
    rareza TEXT, calidad TEXT, rareza_color TEXT, imagen TEXT, url TEXT, actualizado TEXT
);
CREATE INDEX IF NOT EXISTS catalogo_nombre ON catalogo (nombre_norm);
CREATE TABLE IF NOT EXISTS avisos (
    alerta_id INTEGER, articulo_id TEXT, aparicion TEXT, enviado TEXT,
    PRIMARY KEY (alerta_id, articulo_id, aparicion)
);
CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
"""


def conectar():
    con = sqlite3.connect(ARCHIVO_DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def meta(con, clave, valor=None):
    if valor is None:
        fila = con.execute("SELECT valor FROM meta WHERE clave=?", (clave,)).fetchone()
        return fila["valor"] if fila else None
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (clave, valor))


def iniciar_db(config):
    with conectar() as con:
        con.executescript(ESQUEMA)
        columnas = {f["name"] for f in con.execute("PRAGMA table_info(articulos)")}
        for col, tipo in (("mezcla", "TEXT DEFAULT ''"), ("orden", "INTEGER DEFAULT 0")):
            if col not in columnas:  # bases creadas con una versión anterior
                con.execute(f"ALTER TABLE articulos ADD COLUMN {col} {tipo}")
        if "exacto" not in {f["name"] for f in con.execute("PRAGMA table_info(alertas)")}:
            con.execute("ALTER TABLE alertas ADD COLUMN exacto INTEGER DEFAULT 0")
        if not meta(con, "deseos_importados"):
            for palabra in config.get("lista_de_deseos", []):
                p = palabra.strip()
                campo = "color" if p.lower() in PINTURAS else "rareza" if p.lower() in RAREZAS else "nombre"
                con.execute(f"INSERT INTO alertas ({campo}, creada) VALUES (?, ?)", (p, ahora()))
            meta(con, "deseos_importados", ahora())
            log(f"Importé {len(config.get('lista_de_deseos', []))} alertas desde lista_de_deseos")


def alertas_activas(con):
    return [dict(f) for f in con.execute("SELECT * FROM alertas WHERE activa=1")]


def coincide(alerta, a):
    hay_criterio = False
    for campo in CAMPOS_TEXTO:
        buscado = normalizar(alerta.get(campo)).strip()
        if buscado:
            hay_criterio = True
            valor = normalizar(a.get(campo)).strip()
            if campo == "nombre" and alerta.get("exacto"):
                if buscado != valor:  # "Ruinator" no coincide con "Ruinator: Inverted"
                    return False
            elif buscado not in valor:
                return False
    if alerta.get("tienda"):
        hay_criterio = True
        if alerta["tienda"] != a.get("tienda"):
            return False
    if alerta.get("precio_max") is not None:
        hay_criterio = True
        if a.get("precio_num") is None or a["precio_num"] > alerta["precio_max"]:
            return False
    return hay_criterio


def describir_alerta(al):
    partes = [f"{c}{' (exacto)' if c == 'nombre' and al.get('exacto') else ''}: {al[c]}"
              for c in CAMPOS_TEXTO if al.get(c)]
    if al.get("tienda"):
        partes.append(f"tienda: {al['tienda']}")
    if al.get("precio_max") is not None:
        partes.append(f"precio ≤ {al['precio_max']}")
    return ", ".join(partes) or "(vacía)"


def guardar_tienda(con, tienda, articulos, momento):
    """Actualiza el historial de una tienda. Devuelve los artículos que acaban de aparecer."""
    nuevos, ids = [], set()
    for orden, a in enumerate(articulos):
        if a["id"] in ids:
            continue
        ids.add(a["id"])
        previo = con.execute("SELECT * FROM articulos WHERE id=?", (a["id"],)).fetchone()
        imagen = a.get("imagen") or (previo["imagen"] if previo else "")
        if not imagen:  # p.ej. con RL Portal: reutiliza la imagen de otro color del mismo artículo
            fila = con.execute("SELECT imagen FROM articulos WHERE tienda=? AND nombre=? AND imagen<>'' "
                               "ORDER BY ultima_vez DESC LIMIT 1", (tienda, a["nombre"])).fetchone()
            imagen = fila["imagen"] if fila else ""
        if not imagen and tienda == "Rocket League":  # o la del catálogo
            fila = con.execute("SELECT imagen FROM catalogo WHERE nombre_norm=? AND imagen<>'' LIMIT 1",
                               (normalizar(a["nombre"]),)).fetchone()
            imagen = fila["imagen"] if fila else ""
        hasta = a.get("hasta_iso") or (previo["hasta"] if previo and previo["en_tienda"] else "")
        datos = (a["tienda"], a["seccion"], a["nombre"], a["tipo"], a.get("color", ""), a.get("color_hex", ""),
                 a.get("rareza", ""), a.get("rareza_color", ""), a["precio"], a.get("precio_num"),
                 a.get("moneda", ""), imagen, a["url"], hasta, a.get("mezcla", ""), orden)
        if previo is None:
            con.execute("INSERT INTO articulos (tienda, seccion, nombre, tipo, color, color_hex, rareza, "
                        "rareza_color, precio, precio_num, moneda, imagen, url, hasta, mezcla, orden, id, "
                        "primera_vez, ultima_vez, aparicion, en_tienda, apariciones) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1)",
                        datos + (a["id"], momento, momento, momento))
            nuevos.append(a["id"])
        else:
            volvio = not previo["en_tienda"]
            con.execute("UPDATE articulos SET tienda=?, seccion=?, nombre=?, tipo=?, color=?, color_hex=?, "
                        "rareza=?, rareza_color=?, precio=?, precio_num=?, moneda=?, imagen=?, url=?, hasta=?, mezcla=?, orden=?, "
                        "ultima_vez=?, en_tienda=1, aparicion=?, apariciones=apariciones+? WHERE id=?",
                        datos + (momento, momento if volvio else previo["aparicion"], int(volvio), a["id"]))
            if volvio:
                nuevos.append(a["id"])
    marcas = ",".join("?" * len(ids))
    con.execute(f"UPDATE articulos SET en_tienda=0 WHERE tienda=? AND en_tienda=1 AND id NOT IN ({marcas})",
                (tienda, *ids))
    return nuevos


# ---------- avisos ----------

def hasta_texto(iso):
    d = fecha(iso)
    if not d:
        return ""
    local = d.astimezone(zona(fuentes.cargar_config()))
    return local.strftime("%d/%m %H:%M")


def zona(config):
    return timezone(timedelta(hours=float(config.get("zona_horaria_gmt", -3))))


def titulo_articulo(a):
    return a["nombre"] + (f" ({a['color']})" if a.get("color") else "")


def aviso_windows(config, avisos, prueba=False):
    if not config.get("avisos_windows", True):
        return "desactivado"
    prefijo = "[PRUEBA] " if prueba else ""
    if len(avisos) > 3:
        fuentes.notificar(f"{prefijo}¡{len(avisos)} artículos de tus alertas en la tienda!",
                          [", ".join(a["nombre"] for a, _ in avisos[:4]),
                           f"Mira el detalle en http://127.0.0.1:{config['puerto']}"],
                          f"http://127.0.0.1:{config['puerto']}")
        return "ok"
    for a, als in avisos:
        fuentes.notificar(f"{prefijo}¡Alerta! {a['tienda']}: {titulo_articulo(a)}",
                          [f"{a['tipo']} - {a['precio']}" + (f" - hasta {hasta_texto(a['hasta'])}" if a.get("hasta") else ""),
                           "Coincide con: " + "; ".join(describir_alerta(al) for al in als)],
                          a["url"])
    return "ok"


def publicar_json(url, datos, cabeceras=None):
    pedido = urllib.request.Request(url, data=json.dumps(datos).encode("utf-8"), method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "DiscordBot (notificador-rl-local, 1.0)",
        **(cabeceras or {})})
    with urllib.request.urlopen(pedido, timeout=30) as r:
        return r.status


def aviso_discord(config, avisos, prueba=False):
    url = (config.get("discord_webhook_url") or "").strip()
    if not url:
        return "sin configurar"
    embeds = []
    for a, als in avisos:
        try:
            color = int((a.get("rareza_color") or "#5865f2").lstrip("#")[:6], 16)
        except ValueError:
            color = 0x5865F2
        campos = [{"name": "Precio", "value": a["precio"] or "?", "inline": True}]
        d = fecha(a.get("hasta"))
        if d:
            t = int(d.timestamp())
            campos.append({"name": "Disponible hasta", "value": f"<t:{t}:f> (<t:{t}:R>)", "inline": True})
        campos.append({"name": "Alerta", "value": "; ".join(describir_alerta(al) for al in als)[:1000],
                       "inline": False})
        embed = {
            "title": (("[PRUEBA] " if prueba else "") + titulo_articulo(a))[:250],
            "url": a["url"] if a.get("url", "").startswith("http") else None,
            "description": " · ".join(x for x in (a["tienda"], a.get("tipo"), a.get("rareza")) if x),
            "color": color,
            "fields": campos,
            "footer": {"text": f"Notificador RL · {a.get('seccion', '')}"},
        }
        if a.get("imagen", "").startswith("http"):
            embed["image"] = {"url": a["imagen"]}
        embeds.append({k: v for k, v in embed.items() if v is not None})
    try:
        for i in range(0, len(embeds), 10):
            publicar_json(url, {"username": "Notificador RL",
                                "content": "🧪 Aviso de prueba" if prueba else "🔔 ¡Artículos de tus alertas en la tienda!",
                                "embeds": embeds[i:i + 10]})
        return "ok"
    except urllib.error.HTTPError as err:
        return f"error {err.code}: {err.read().decode('utf-8', 'replace')[:200]}"
    except Exception as err:
        return f"error: {err}"


def aviso_correo(config, avisos, prueba=False):
    c = config.get("correo_smtp") or {}
    if not (c.get("usuario") and c.get("contrasena_aplicacion") and c.get("para")):
        return "sin configurar"
    msg = EmailMessage()
    msg["Subject"] = ("[PRUEBA] " if prueba else "") + (
        f"Tienda: {titulo_articulo(avisos[0][0])}" if len(avisos) == 1 else f"Tienda: {len(avisos)} artículos de tus alertas")
    msg["From"] = c["usuario"]
    msg["To"] = c["para"]
    texto, filas = [], []
    for a, als in avisos:
        hasta = hasta_texto(a.get("hasta"))
        texto.append(f"- {a['tienda']}: {titulo_articulo(a)} - {a['tipo']} - {a['precio']}"
                     + (f" - hasta {hasta}" if hasta else "") + f"\n  {a['url']}")
        img = f'<img src="{escape(a["imagen"])}" width="160" style="display:block">' if a.get("imagen") else ""
        filas.append(f'<tr><td style="padding:8px">{img}</td><td style="padding:8px;font-family:sans-serif">'
                     f'<b><a href="{escape(a["url"])}">{escape(titulo_articulo(a))}</a></b><br>'
                     f'{escape(a["tienda"])} · {escape(a.get("tipo", ""))} · {escape(a.get("rareza", ""))}<br>'
                     f'<b>{escape(a["precio"])}</b>' + (f' · hasta {escape(hasta)}' if hasta else "") +
                     f'<br><small>Alerta: {escape("; ".join(describir_alerta(al) for al in als))}</small></td></tr>')
    msg.set_content("\n".join(texto))
    msg.add_alternative(f"<table>{''.join(filas)}</table>", subtype="html")
    try:
        with smtplib.SMTP(c.get("servidor", "smtp.gmail.com"), int(c.get("puerto", 587)), timeout=30) as s:
            s.starttls()
            s.login(c["usuario"], c["contrasena_aplicacion"])
            s.send_message(msg)
        return "ok"
    except Exception as err:
        return f"error: {err}"


def enviar_avisos(config, avisos, prueba=False):
    resultado = {
        "windows": aviso_windows(config, avisos, prueba),
        "discord": aviso_discord(config, avisos, prueba),
        "correo": aviso_correo(config, avisos, prueba),
    }
    log("Avisos: " + ", ".join(f"{k}={v}" for k, v in resultado.items()))
    return resultado


# ---------- revisión ----------

class Estado:
    lock = threading.Lock()
    revisando = False
    ultima = None
    resumen = "Todavía no se revisó"
    errores = []
    proxima_periodica = None
    proxima_fija = None


def revisar():
    """Lee las tiendas, actualiza la base y manda avisos de alertas nuevas."""
    if not Estado.lock.acquire(blocking=False):
        return
    Estado.revisando = True
    try:
        config = fuentes.cargar_config()
        momento = ahora()
        lecturas, errores = {}, []
        if config.get("rocket_league", True):
            try:
                lecturas["Rocket League"] = fuentes.tienda_rocket_league(config)
            except Exception as err:
                errores.append(f"Rocket League: {err}")
        if config.get("fortnite", True):
            try:
                lecturas["Fortnite"] = fuentes.tienda_fortnite(config)
            except Exception as err:
                errores.append(f"Fortnite: {err}")
        with conectar() as con:
            primera = meta(con, "primera_revision") is None
            nuevos = {t: guardar_tienda(con, t, arts, momento) for t, arts in lecturas.items() if arts}
            if primera and lecturas:
                meta(con, "primera_revision", momento)
            # Alertas: todo lo que está en tienda, sin repetir avisos de la misma aparición
            en_tienda = [dict(f) for f in con.execute("SELECT * FROM articulos WHERE en_tienda=1")]
            pendientes = {}
            for al in alertas_activas(con):
                for a in en_tienda:
                    if coincide(al, a) and not con.execute(
                            "SELECT 1 FROM avisos WHERE alerta_id=? AND articulo_id=? AND aparicion=?",
                            (al["id"], a["id"], a["aparicion"])).fetchone():
                        pendientes.setdefault(a["id"], (a, []))[1].append(al)
            avisos = list(pendientes.values())
        if avisos:
            enviar_avisos(config, avisos)
            with conectar() as con:
                for a, als in avisos:
                    for al in als:
                        con.execute("INSERT OR IGNORE INTO avisos VALUES (?,?,?,?)",
                                    (al["id"], a["id"], a["aparicion"], ahora()))
        # Resumen de todo lo nuevo (solo Windows), como el modo de consola
        if config.get("avisar_todo_lo_nuevo") and config.get("avisos_windows", True) and not primera:
            for tienda, ids in nuevos.items():
                if ids:
                    grupo = [a for a in lecturas[tienda] if a["id"] in ids]
                    fuentes.notificar(f"Tienda {tienda}: {len(ids)} nuevo{'s' if len(ids) != 1 else ''}",
                                      [fuentes.resumen(a) for a in grupo[:2]],
                                      f"http://127.0.0.1:{config['puerto']}")
        total = sum(len(v) for v in lecturas.values())
        Estado.resumen = (f"{total} artículos leídos, {sum(len(v) for v in nuevos.values())} nuevos, "
                          f"{len(avisos)} con aviso de alerta")
        Estado.errores = errores
        Estado.ultima = momento
        log(Estado.resumen + ("; errores: " + "; ".join(errores) if errores else ""))
    except Exception as err:
        Estado.errores = [f"Error inesperado: {err}"]
        log(f"Error inesperado en la revisión: {err}")
    finally:
        Estado.revisando = False
        Estado.lock.release()


class EstadoCatalogo:
    lock = threading.Lock()
    actualizando = False
    progreso = ""
    error = ""


def actualizar_catalogo():
    """Descarga el catálogo completo (una categoría por vez, con pausa entre pedidos)."""
    if not EstadoCatalogo.lock.acquire(blocking=False):
        return
    EstadoCatalogo.actualizando, EstadoCatalogo.error = True, ""
    momento, total, errores = ahora(), 0, []
    try:
        for i, (categoria, tipo) in enumerate(CATEGORIAS.items(), 1):
            EstadoCatalogo.progreso = f"{i}/{len(CATEGORIAS)}: {tipo}"
            if i > 1:
                threading.Event().wait(1.5)  # sin saturar el sitio
            try:
                filas = json.loads(fuentes.descargar(URL_CATALOGO.format(categoria))).get("rows") or []
            except Exception as err:
                errores.append(f"{tipo}: {err}")
                continue
            with conectar() as con:
                for it in filas:
                    if not it.get("n") or not it.get("h"):
                        continue
                    rareza, color = RAREZAS_CATALOGO.get(it.get("f"), (it.get("f") or "", "#9aa3b2"))
                    con.execute("INSERT OR REPLACE INTO catalogo VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                        it["h"], it.get("d"), it["n"], normalizar(it["n"]), it.get("k") or "", tipo, rareza,
                        it.get("q") or "", color, it.get("i") or "", URL_CATALOGO_BASE + it["h"], momento))
            total += len(filas)
        with conectar() as con:
            if total:
                meta(con, "catalogo_actualizado", momento)
            # Si una categoría falló, se conserva lo que ya había de ella
            n = con.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0]
        EstadoCatalogo.error = "; ".join(errores)
        log(f"Catálogo actualizado: {total} artículos descargados, {n} en total"
            + (f"; errores: {EstadoCatalogo.error}" if errores else ""))
    except Exception as err:
        EstadoCatalogo.error = str(err)
        log(f"Error actualizando el catálogo: {err}")
    finally:
        EstadoCatalogo.actualizando, EstadoCatalogo.progreso = False, ""
        EstadoCatalogo.lock.release()


def catalogo_vencido():
    with conectar() as con:
        ultima = fecha(meta(con, "catalogo_actualizado") or "")
    return ultima is None or datetime.now(timezone.utc) - ultima > timedelta(days=DIAS_ENTRE_CATALOGOS)


def actualizar_catalogo_en_fondo():
    threading.Thread(target=actualizar_catalogo, daemon=True).start()


def proxima_hora_fija(config, desde):
    try:
        h, m = (int(x) for x in str(config.get("hora_revision_fija", "16:05")).split(":"))
    except ValueError:
        return None
    local = desde.astimezone(zona(config))
    objetivo = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if objetivo <= local:
        objetivo += timedelta(days=1)
    return objetivo.astimezone(timezone.utc)


REVISAR_YA = threading.Event()


def programador():
    config = fuentes.cargar_config()
    Estado.proxima_periodica = datetime.now(timezone.utc)  # primera revisión al arrancar
    Estado.proxima_fija = proxima_hora_fija(config, datetime.now(timezone.utc))
    while True:
        n = datetime.now(timezone.utc)
        toca_fija = Estado.proxima_fija is not None and n >= Estado.proxima_fija
        if REVISAR_YA.is_set() or n >= Estado.proxima_periodica or toca_fija:
            REVISAR_YA.clear()
            revisar()
            config = fuentes.cargar_config()
            n = datetime.now(timezone.utc)
            Estado.proxima_periodica = n + timedelta(minutes=max(5, int(config.get("minutos_entre_revisiones", 60))))
            if toca_fija or Estado.proxima_fija is None:
                Estado.proxima_fija = proxima_hora_fija(config, n)
            if not EstadoCatalogo.actualizando and catalogo_vencido():  # una vez por semana
                actualizar_catalogo_en_fondo()
        REVISAR_YA.wait(timeout=20)


# ---------- API ----------

def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def estado_api():
    config = fuentes.cargar_config()
    with conectar() as con:
        alertas = [dict(f) for f in con.execute("SELECT * FROM alertas ORDER BY id")]
        articulos = [dict(f) for f in con.execute(
            "SELECT * FROM articulos WHERE en_tienda=1 ORDER BY tienda, orden")]
        primera = meta(con, "primera_revision") or ""
    limite_nuevo = iso(datetime.now(timezone.utc) - timedelta(hours=24))
    for a in articulos:
        a["alertas"] = [al["id"] for al in alertas if al["activa"] and coincide(al, a)]
        a["nuevo"] = a["aparicion"] > primera and a["aparicion"] >= limite_nuevo
    for al in alertas:
        al["coincidencias"] = sum(1 for a in articulos if al["id"] in a["alertas"])
        al["descripcion"] = describir_alerta(al)
    c = config.get("correo_smtp") or {}
    return {
        "articulos": articulos,
        "alertas": alertas,
        "revision": {
            "revisando": Estado.revisando, "ultima": Estado.ultima, "resumen": Estado.resumen,
            "errores": Estado.errores, "proxima_periodica": iso(Estado.proxima_periodica),
            "proxima_fija": iso(Estado.proxima_fija),
            "minutos": config.get("minutos_entre_revisiones"), "hora_fija": config.get("hora_revision_fija"),
            "zona": config.get("zona_horaria_gmt"),
        },
        "canales": {
            "windows": bool(config.get("avisos_windows", True)),
            "discord": bool((config.get("discord_webhook_url") or "").strip()),
            "correo": bool(c.get("usuario") and c.get("contrasena_aplicacion") and c.get("para")),
        },
    }


def patron_like(palabra):
    return "%" + palabra.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def catalogo_api(consulta):
    q = normalizar(consulta.get("q", [""])[0]).strip()
    tipo, rareza = consulta.get("tipo", [""])[0], consulta.get("rareza", [""])[0]
    vista = consulta.get("vista", [""])[0]  # "", "nunca", "visto", "hoy", "alerta"
    try:
        pagina = max(0, int(consulta.get("pagina", ["0"])[0] or 0))
    except ValueError:
        pagina = 0
    por_pagina = 120
    sql, args = "SELECT * FROM catalogo WHERE 1=1", []
    for palabra in q.split():
        sql += " AND (nombre_norm LIKE ? ESCAPE '\\' OR lower(variante) LIKE ? ESCAPE '\\')"
        args += [patron_like(palabra)] * 2
    if tipo:
        sql += " AND tipo=?"
        args.append(tipo)
    if rareza:
        sql += " AND rareza=?"
        args.append(rareza)
    sql += " ORDER BY (nombre_norm=?) DESC, producto_id DESC"
    args.append(q)
    with conectar() as con:
        filas = [dict(f) for f in con.execute(sql, args)]
        vistos = {}
        for f in con.execute("SELECT nombre, MAX(ultima_vez) AS ultima, MAX(en_tienda) AS hoy, "
                             "SUM(apariciones) AS veces FROM articulos WHERE tienda='Rocket League' "
                             "GROUP BY lower(nombre)"):
            vistos[normalizar(f["nombre"])] = dict(f)
        alertas = alertas_activas(con)
        tipos = [r[0] for r in con.execute("SELECT DISTINCT tipo FROM catalogo ORDER BY tipo")]
        rarezas = [r[0] for r in con.execute("SELECT DISTINCT rareza FROM catalogo ORDER BY rareza")]
        total_catalogo = con.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0]
        actualizado = meta(con, "catalogo_actualizado")
    for f in filas:
        v = vistos.get(f["nombre_norm"])
        f["ultima_vez"] = v["ultima"] if v else None
        f["en_tienda"] = bool(v and v["hoy"])
        f["veces"] = v["veces"] if v else 0

    def alertas_de(f):
        # El catálogo no tiene color ni precio: se marcan las alertas por nombre (o tipo) sin esos filtros
        a = {"nombre": f["nombre"], "tipo": f["tipo"], "rareza": f["rareza"], "tienda": "Rocket League"}
        return [al["id"] for al in alertas if not al.get("color") and al.get("precio_max") is None
                and (al.get("nombre") or al.get("tipo")) and coincide(al, a)]

    if vista == "nunca":
        filas = [f for f in filas if not f["ultima_vez"]]
    elif vista == "visto":
        filas = [f for f in filas if f["ultima_vez"]]
    elif vista == "hoy":
        filas = [f for f in filas if f["en_tienda"]]
    elif vista == "alerta":
        filas = [f for f in filas if alertas_de(f)]
    total = len(filas)
    filas = filas[pagina * por_pagina:(pagina + 1) * por_pagina]
    for f in filas:
        f["alertas"] = alertas_de(f)
        f.pop("nombre_norm", None)
    return {"articulos": filas, "total": total, "pagina": pagina, "por_pagina": por_pagina,
            "tipos": tipos, "rarezas": rarezas, "total_catalogo": total_catalogo, "actualizado": actualizado,
            "actualizando": EstadoCatalogo.actualizando, "progreso": EstadoCatalogo.progreso,
            "error": EstadoCatalogo.error}


def historial_api():
    with conectar() as con:
        return [dict(f) for f in con.execute("SELECT * FROM articulos ORDER BY ultima_vez DESC, nombre")]


def limpiar_alerta(datos):
    alerta = {c: str(datos.get(c) or "").strip()[:100] for c in CAMPOS_TEXTO}
    alerta["tienda"] = datos.get("tienda") if datos.get("tienda") in TIENDAS else ""
    precio = datos.get("precio_max")
    try:
        alerta["precio_max"] = int(precio) if precio not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("El precio máximo debe ser un número")
    alerta["activa"] = 0 if datos.get("activa") in (False, 0, "0") else 1
    alerta["exacto"] = 1 if datos.get("exacto") in (True, 1, "1") else 0
    if not any(alerta[c] for c in CAMPOS_TEXTO) and not alerta["tienda"] and alerta["precio_max"] is None:
        raise ValueError("La alerta necesita al menos un criterio")
    return alerta


def prueba_aviso():
    config = fuentes.cargar_config()
    with conectar() as con:
        fila = con.execute("SELECT * FROM articulos WHERE en_tienda=1 AND imagen<>'' "
                           "ORDER BY precio_num DESC LIMIT 1").fetchone()
    a = dict(fila) if fila else {
        "id": "prueba", "tienda": "Rocket League", "seccion": "Prueba", "nombre": "Octane", "tipo": "Body",
        "color": "Titanium White", "rareza": "Import", "rareza_color": "#e4524f", "precio": "1,000 créditos",
        "imagen": "", "url": fuentes.URL_RL, "hasta": ""}
    return enviar_avisos(config, [(a, [{"nombre": "ejemplo de alerta"}])], prueba=True)


class Manejador(BaseHTTPRequestHandler):
    server_version = "NotificadorRL/1.0"

    def log_message(self, formato, *args):  # silencio en consola
        pass

    def responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        if not isinstance(cuerpo, bytes):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def permitido(self, escribe=False):
        # Solo desde este equipo (evita "DNS rebinding") y, para cambios, solo pedidos JSON de la propia página
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        if escribe:
            origen = self.headers.get("Origin")
            if origen and not re.match(r"^http://(127\.0\.0\.1|localhost):\d+$", origen):
                return False
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                return False
        return True

    def leer_cuerpo(self):
        largo = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(largo) or b"{}") if largo else {}

    def do_GET(self):
        if not self.permitido():
            return self.responder(403, {"error": "prohibido"})
        ruta = self.path.split("?")[0]
        try:
            if ruta in ARCHIVOS_WEB:
                nombre, tipo = ARCHIVOS_WEB[ruta]
                return self.responder(200, (CARPETA_WEB / nombre).read_bytes(), tipo)
            if ruta == "/api/estado":
                return self.responder(200, estado_api())
            if ruta == "/api/historial":
                return self.responder(200, historial_api())
            if ruta == "/api/catalogo":
                return self.responder(200, catalogo_api(parse_qs(urlsplit(self.path).query)))
            self.responder(404, {"error": "no existe"})
        except Exception as err:
            self.responder(500, {"error": str(err)})

    def do_POST(self):
        if not self.permitido(escribe=True):
            return self.responder(403, {"error": "prohibido"})
        ruta = self.path.split("?")[0]
        try:
            if ruta == "/api/alertas":
                al = limpiar_alerta(self.leer_cuerpo())
                with conectar() as con:
                    cur = con.execute("INSERT INTO alertas (nombre, color, tipo, rareza, tienda, precio_max, "
                                      "activa, exacto, creada) VALUES (?,?,?,?,?,?,?,?,?)",
                                      (al["nombre"], al["color"], al["tipo"], al["rareza"], al["tienda"],
                                       al["precio_max"], al["activa"], al["exacto"], ahora()))
                return self.responder(200, {"id": cur.lastrowid})
            if ruta == "/api/revisar":
                REVISAR_YA.set()
                return self.responder(200, {"ok": True})
            if ruta == "/api/catalogo/actualizar":
                actualizar_catalogo_en_fondo()
                return self.responder(200, {"ok": True})
            if ruta == "/api/probar-aviso":
                return self.responder(200, prueba_aviso())
            self.responder(404, {"error": "no existe"})
        except ValueError as err:
            self.responder(400, {"error": str(err)})
        except Exception as err:
            self.responder(500, {"error": str(err)})

    def id_alerta(self):
        m = re.fullmatch(r"/api/alertas/(\d+)", self.path.split("?")[0])
        return int(m[1]) if m else None

    def do_PUT(self):
        if not self.permitido(escribe=True):
            return self.responder(403, {"error": "prohibido"})
        n = self.id_alerta()
        if n is None:
            return self.responder(404, {"error": "no existe"})
        try:
            al = limpiar_alerta(self.leer_cuerpo())
            with conectar() as con:
                con.execute("UPDATE alertas SET nombre=?, color=?, tipo=?, rareza=?, tienda=?, precio_max=?, "
                            "activa=?, exacto=? WHERE id=?",
                            (al["nombre"], al["color"], al["tipo"], al["rareza"], al["tienda"],
                             al["precio_max"], al["activa"], al["exacto"], n))
            self.responder(200, {"ok": True})
        except ValueError as err:
            self.responder(400, {"error": str(err)})

    def do_DELETE(self):
        if not self.permitido(escribe=True):
            return self.responder(403, {"error": "prohibido"})
        n = self.id_alerta()
        if n is None:
            return self.responder(404, {"error": "no existe"})
        with conectar() as con:
            con.execute("DELETE FROM alertas WHERE id=?", (n,))
            con.execute("DELETE FROM avisos WHERE alerta_id=?", (n,))
        self.responder(200, {"ok": True})


class Servidor(ThreadingHTTPServer):
    # En Windows, reutilizar la dirección dejaría abrir dos notificadores en el mismo puerto
    allow_reuse_address = False
    daemon_threads = True


def main():
    config = fuentes.cargar_config()
    puerto = int(config.get("puerto", 8765))
    url = f"http://127.0.0.1:{puerto}/"
    abrir = config.get("abrir_navegador", True) and "--sin-navegador" not in sys.argv
    try:
        servidor = Servidor(("127.0.0.1", puerto), Manejador)
    except OSError:
        log(f"El puerto {puerto} ya está en uso: seguramente el notificador ya está abierto.")
        if abrir:
            webbrowser.open(url)
        return
    iniciar_db(config)
    threading.Thread(target=programador, daemon=True).start()
    log(f"Notificador abierto en {url}  (cierra esta ventana o Ctrl+C para salir)")
    if abrir:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nListo, hasta luego.")


if __name__ == "__main__":
    main()
