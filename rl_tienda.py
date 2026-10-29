"""
Notificador de tiendas: Rocket League + sección de vehículos de Fortnite.

Revisa cada cierto tiempo:
  - La tienda de Rocket League (destacados, lotes y secciones especiales), leída de
    itemshop.gg, con RL Portal como respaldo automático si itemshop.gg falla.
  - La tienda de Fortnite, solo los artículos de autos: lotes, carrocerías, ruedas,
    propulsores, rastros y calcomanías (API pública de fortnite-api.com).

Avisa con una notificación de Windows cuando aparece algo nuevo, y con una aparte
cuando aparece algo de tu lista de deseos (config.json).

Uso:
  python rl_tienda.py            -> revisa ahora y luego cada N minutos (según config.json)
  python rl_tienda.py --una-vez  -> revisa una sola vez y termina
  python rl_tienda.py --listar   -> muestra la tienda actual en la consola, sin notificar
  python rl_tienda.py --probar   -> manda una notificación de prueba
"""

import base64
import html
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
ARCHIVO_CONFIG = CARPETA / "config.json"
ARCHIVO_ESTADO = CARPETA / "vistos.json"

URL_RL = "https://itemshop.gg/rocket-league"
URL_RL_RESPALDO = "https://www.rl-portal.re/shop"
URL_FN = "https://fortnite-api.com/v2/shop?language={idioma}"
URL_FN_WEB = "https://www.fortnite.com/item-shop"

CONFIG_INICIAL = {
    "minutos_entre_revisiones": 60,
    "idioma_fortnite": "es-419",
    "rocket_league": True,
    "fortnite": True,
    # Fuente de RL: "auto" (itemshop.gg y si falla RL Portal) o "rl-portal" (al revés)
    "fuente_rl": "auto",
    # Secciones de RL que no te interesan. "RLCS" = equipos de esports, "Shop" = cajas/cups
    "secciones_rl_ignoradas": ["RLCS", "Shop"],
    # Tipos de Fortnite a vigilar: lote, carroceria, rueda, propulsor, rastro, calcomania
    "tipos_fortnite": ["lote", "carroceria", "rueda", "propulsor", "rastro", "calcomania"],
    # Avisar de TODO lo nuevo (true) o solo de la lista de deseos (false)
    "avisar_todo_lo_nuevo": True,
    # Palabras a buscar en nombre, tipo o color (sin importar mayúsculas). Ej: "octane", "titanium white", "fennec"
    "lista_de_deseos": ["Octane", "Fennec", "Titanium White", "Black Market"],
    # --- Opciones del servidor web (notificador.py) ---
    "puerto": 8765,
    "abrir_navegador": True,
    # Revisión fija diaria (además de la periódica), en la zona horaria indicada (GMT-3 = -3)
    "hora_revision_fija": "16:05",
    "zona_horaria_gmt": -3,
    "avisos_windows": True,
    # Pega aquí la URL del webhook de Discord (vacío = desactivado)
    "discord_webhook_url": "",
    # Correo opcional. Para Gmail usa una "contraseña de aplicación" (vacío = desactivado)
    "correo_smtp": {"servidor": "smtp.gmail.com", "puerto": 587, "usuario": "",
                    "contrasena_aplicacion": "", "para": ""},
}

TIPOS_FN = {
    "body": "carroceria",
    "wheel": "rueda",
    "booster": "propulsor",
    "drifttrail": "rastro",
    "skin": "calcomania",
}
COLORES_RAREZA_FN = {
    "common": "#9d9d9d", "uncommon": "#69bb1e", "rare": "#2cc3fc", "epic": "#c359ff",
    "legendary": "#ea8d23", "mythic": "#ffd84b", "exotic": "#76d6e3",
}
NOMBRE_TIPO = {
    "lote": "Lote",
    "carroceria": "Carrocería",
    "rueda": "Ruedas",
    "propulsor": "Propulsor",
    "rastro": "Rastro",
    "calcomania": "Calcomanía",
}


# ---------- utilidades ----------

def descargar(url, cabeceras=None):
    pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (notificador-tienda-rl)",
                                                  **(cabeceras or {})})
    with urllib.request.urlopen(pedido, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def leer_json(ruta, por_defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return por_defecto


def guardar_json(ruta, datos):
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def cargar_config():
    if not ARCHIVO_CONFIG.exists():
        # La plantilla del repo, sin datos privados (config.ejemplo.json es el nombre viejo)
        plantillas = [CARPETA / "config.example.json", CARPETA / "config.ejemplo.json"]
        plantilla = next((x for x in plantillas if x.exists()), None)
        guardar_json(ARCHIVO_CONFIG, leer_json(plantilla, CONFIG_INICIAL) if plantilla else CONFIG_INICIAL)
        print(f"Creé {ARCHIVO_CONFIG.name}: edítalo para cambiar tu lista de deseos.")
    guardado = leer_json(ARCHIVO_CONFIG, {})
    config = dict(CONFIG_INICIAL)
    config.update(guardado)
    if set(config) - set(guardado):  # agrega opciones nuevas al archivo sin tocar las tuyas
        guardar_json(ARCHIVO_CONFIG, config)
    return config


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


# ---------- Rocket League ----------
# No hay API oficial de la tienda de RL, así que leemos sitios de seguimiento.
# Fuente principal: itemshop.gg. Respaldo: RL Portal. Si uno cae, se usa el otro.

def datos_next(pagina):
    """Junta los datos que las páginas hechas con Next.js traen incrustados."""
    trozos = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', pagina)
    return "".join(json.loads('"' + t + '"') for t in trozos)


def texto(valor):
    return "" if valor in (None, "$undefined") else str(valor).strip()


def numero(precio):
    try:
        return int(re.sub(r"[^\d]", "", str(precio)))
    except ValueError:
        return None


def articulo_rl(nombre, tipo, color, rareza, precio, seccion, hasta, url,
                imagen="", color_hex="", rareza_color="", mezcla=""):
    # El id no depende de la página, así cambiar de fuente no repite avisos.
    clave = f"{nombre}|{color}|{precio}".lower()
    return {
        "id": "rl:" + clave,
        "tienda": "Rocket League",
        "seccion": seccion,
        "nombre": nombre,
        "tipo": tipo,
        "color": color,
        "rareza": rareza,
        "precio": f"{precio} créditos" if precio else "",
        "hasta": hasta[:10],
        "hasta_iso": hasta,
        "url": url,
        # Datos extra para la interfaz web (notificador.py)
        "imagen": imagen,
        "color_hex": color_hex,
        "rareza_color": rareza_color,
        "mezcla": mezcla,  # "screen" = imagen con fondo negro que se funde con el fondo
        "precio_num": numero(precio),
        "moneda": "créditos",
    }


def rl_desde_itemshop():
    datos = datos_next(descargar(URL_RL))
    inicio = datos.find('"sections":[')
    if inicio < 0:
        raise RuntimeError("no encontré las secciones (¿cambió itemshop.gg?)")
    secciones, _ = json.JSONDecoder().raw_decode(datos, inicio + len('"sections":'))
    articulos = []
    for sec in secciones:
        titulo = texto(sec.get("title"))
        for c in sec.get("cards", []):
            pintura = c.get("paint")
            pintura = pintura if isinstance(pintura, dict) else {}
            rareza = texto(c.get("rarityName"))
            tipo = texto(c.get("subtitle"))
            if rareza and tipo.lower().startswith(rareza.lower() + " "):
                tipo = tipo[len(rareza) + 1:]  # "Common Body" -> "Body"
            if ":bundle:" in texto(c.get("id")):
                tipo = f"Lote ({tipo})"
            precio = (c.get("price") or {}).get("amount")
            hasta = texto((c.get("availability") or {}).get("outDate")) or texto(sec.get("endsAt"))
            articulos.append(articulo_rl(texto(c.get("name")), tipo, texto(pintura.get("name")), rareza,
                                         f"{precio:,}" if isinstance(precio, int) else "", titulo, hasta,
                                         texto(c.get("url")) or URL_RL,
                                         imagen=texto(c.get("image")) or texto(c.get("art")),
                                         color_hex=texto(pintura.get("color")),
                                         rareza_color=texto(c.get("rarityColor")),
                                         mezcla=texto(c.get("blend"))))
    return articulos


def rl_desde_portal():
    datos = datos_next(descargar(URL_RL_RESPALDO))
    inicios = [m.start() for m in re.finditer(r'\["\$","div","[^"]+",\{"className":"[^"]*shop-item-card', datos)]
    articulos = []
    for i, ini in enumerate(inicios):
        bloque = datos[ini:inicios[i + 1] if i + 1 < len(inicios) else ini + 6000]
        buscar = lambda patron: (re.search(patron, bloque) or [None, ""])[1]
        nombre = buscar(r'"h3",null,\{[^{}]*"children":"([^"]*)"')
        precio = buscar(r'"alt":"Credits"[^}]*\}\],\["\$","span",null,\{[^{}]*"children":"([\d,.]+)"')
        ref = buscar(r'"alt":"Credits"[^}]*\}\],"\$L(\w+)"')
        if not precio and ref:  # a veces el precio está guardado aparte, como referencia
            m = re.search(r'(?:^|\n)' + ref + r':\["\$","span",null,\{[^{}]*"children":"([\d,.]+)"', datos)
            precio = m[1] if m else ""
        if buscar(r'"p",null,\{[^{}]*"children":"([^"]*)"') == "Crate":
            continue  # cajas (cups), igual que la sección "Shop" de la fuente principal
        if not nombre or not precio:  # sin precio = artículos de esports/destacados sin venta directa
            continue
        pintura = buscar(r'"title":"[^"]*: ([^"]*)"')
        # Sin imagen a propósito: RL Portal solo las sirve desde su API (la interfaz
        # reutiliza la imagen guardada en el historial si el artículo ya se vio antes).
        articulos.append(articulo_rl(
            nombre,
            buscar(r'"p",null,\{[^{}]*"children":"([^"]*)"'),
            pintura,
            buscar(r'"--quality-color"[^{}]*\},"children":"([^"]*)"'),
            precio, "Tienda", "", URL_RL_RESPALDO,
            color_hex=buscar(r'rounded-full border border-white/50","style":\{"backgroundColor":"(#\w+)"') if pintura else "",
            rareza_color=buscar(r'"--quality-color":"(#\w+)"')))
    return articulos


def tienda_rocket_league(config):
    fuentes = [("itemshop.gg", rl_desde_itemshop), ("RL Portal", rl_desde_portal)]
    if config.get("fuente_rl") == "rl-portal":
        fuentes.reverse()
    ignoradas = {s.lower() for s in config.get("secciones_rl_ignoradas", [])}
    errores = []
    for nombre, leer in fuentes:
        try:
            articulos = [a for a in leer() if a["seccion"].lower() not in ignoradas]
            if articulos:
                return articulos
            errores.append(f"{nombre}: sin artículos")
        except Exception as err:
            errores.append(f"{nombre}: {err}")
        log(f"Falló {nombre}, pruebo con la otra fuente...")
    raise RuntimeError("; ".join(errores))


# ---------- Fortnite (vehículos) ----------

def tienda_fortnite(config):
    datos = json.loads(descargar(URL_FN.format(idioma=config["idioma_fortnite"])))
    tipos_buscados = set(config["tipos_fortnite"])
    articulos = []
    for e in datos.get("data", {}).get("entries", []):
        autos = e.get("cars") or []
        if not autos:
            continue
        tipos = [TIPOS_FN.get(a.get("type", {}).get("value", ""), "otro") for a in autos]
        es_lote = bool(e.get("bundle")) and len(autos) > 1
        tipo = "lote" if es_lote else tipos[0]
        if tipo not in tipos_buscados:
            continue
        nombre = (e.get("bundle") or {}).get("name") or autos[0].get("name", "?")
        if es_lote:
            detalle = ", ".join(sorted({NOMBRE_TIPO.get(t, t) for t in tipos}))
        else:
            detalle = NOMBRE_TIPO.get(tipo, tipo)
        rareza_fn = autos[0].get("rarity") or {}
        rareza = rareza_fn.get("displayValue", "")
        serie = autos[0].get("series") or {}
        if serie.get("colors"):
            rareza_color = "#" + serie["colors"][0][:6]
        else:
            rareza_color = COLORES_RAREZA_FN.get(rareza_fn.get("value", ""), "#9d9d9d")
        render = ((e.get("newDisplayAsset") or {}).get("renderImages") or [{}])[0].get("image")
        imagenes = autos[0].get("images") or {}
        imagen = render or (e.get("bundle") or {}).get("image") or imagenes.get("large") or imagenes.get("small") or ""
        articulos.append({
            "id": "fn:" + e.get("offerId", nombre),
            "tienda": "Fortnite",
            "seccion": (e.get("layout") or {}).get("name") or "Vehículos",
            "nombre": nombre,
            "tipo": detalle,
            "color": "",
            "rareza": rareza,
            "precio": f"{e.get('finalPrice', '?')} V-Bucks",
            "url": URL_FN_WEB,
            "hasta": (e.get("outDate") or "")[:10],
            "hasta_iso": e.get("outDate") or "",
            "imagen": imagen,
            "color_hex": "",
            "rareza_color": rareza_color,
            "precio_num": e.get("finalPrice") if isinstance(e.get("finalPrice"), int) else None,
            "moneda": "V-Bucks",
        })
    return articulos


# ---------- notificaciones ----------

def notificar(titulo, lineas, url):
    """Notificación nativa de Windows (sin instalar nada), usando PowerShell."""
    esc = lambda s: html.escape(s, quote=True)
    textos = "".join(f"<text>{esc(l)}</text>" for l in lineas[:2])
    xml = (f'<toast activationType="protocol" launch="{esc(url)}">'
           f'<visual><binding template="ToastGeneric"><text>{esc(titulo)}</text>{textos}</binding></visual>'
           f'<audio src="ms-winsoundevent:Notification.Default"/></toast>')
    xml_b64 = base64.b64encode(xml.encode("utf-8")).decode()
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null;"
        f"$x = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{xml_b64}'));"
        "$d = New-Object Windows.Data.Xml.Dom.XmlDocument; $d.LoadXml($x);"
        "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
        "[Windows.UI.Notifications.ToastNotification]::new($d))"
    )
    comando = base64.b64encode(script.encode("utf-16-le")).decode()
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", comando],
                       check=True, capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as err:  # si falla la notificación, al menos queda en consola
        log(f"No pude mostrar la notificación ({err})")
    log(f"{titulo} | " + " | ".join(lineas))


def resumen(a):
    partes = [a["nombre"]]
    if a["color"] and a["tienda"] == "Rocket League":
        partes.append(f"({a['color']})")
    partes.append(f"- {a['tipo']} - {a['precio']}")
    if a.get("hasta"):
        d = a["hasta"]
        partes.append(f"(hasta {d[8:10]}/{d[5:7]})")
    return " ".join(partes)


def coincide(a, deseos):
    texto = f"{a['nombre']} {a['tipo']} {a['color']} {a.get('rareza', '')} {a['seccion']}".lower()
    return [d for d in deseos if d.lower() in texto]


# ---------- ciclo principal ----------

def obtener_todo(config):
    articulos, fuentes = [], []
    if config["rocket_league"]:
        fuentes.append(("Rocket League", lambda: tienda_rocket_league(config)))
    if config["fortnite"]:
        fuentes.append(("Fortnite", lambda: tienda_fortnite(config)))
    for nombre, fn in fuentes:
        try:
            articulos += fn()
        except Exception as err:
            log(f"Error leyendo la tienda de {nombre}: {err}")
    return articulos


def revisar(config):
    articulos = obtener_todo(config)
    vistos = set(leer_json(ARCHIVO_ESTADO, []))
    nuevos = [a for a in articulos if a["id"] not in vistos]
    log(f"{len(articulos)} artículos en tienda, {len(nuevos)} nuevos")

    # 1) Lista de deseos: una notificación por artículo (o una sola si son muchos)
    deseados = [(a, coincide(a, config["lista_de_deseos"])) for a in nuevos]
    deseados = [(a, p) for a, p in deseados if p]
    if len(deseados) > 3:
        notificar(f"¡{len(deseados)} artículos de tu lista en la tienda!",
                  [", ".join(a["nombre"] for a, _ in deseados[:4]),
                   f"y {len(deseados) - 4} más" if len(deseados) > 4 else "Revisa la consola para el detalle"],
                  deseados[0][0]["url"])
        for a, p in deseados:
            print(f"    * {a['tienda']}: {resumen(a)}  [{', '.join(p)}]")
        deseados = []
    for a, palabras in deseados:
        if palabras:
            notificar(f"¡En tu lista! {a['tienda']}: {a['nombre']}",
                      [f"{a['tipo']} - {a['precio']}" + (f" - {a['color']}" if a["color"] else ""),
                       f"Coincide con: {', '.join(palabras)}"],
                      a["url"])

    # 2) Resumen de lo nuevo, una notificación por tienda
    if config["avisar_todo_lo_nuevo"]:
        for tienda, url in (("Rocket League", URL_RL), ("Fortnite", URL_FN_WEB)):
            grupo = [a for a in nuevos if a["tienda"] == tienda]
            if not grupo:
                continue
            lineas = [resumen(a) for a in grupo[:2]]
            if len(grupo) > 2:
                lineas[-1] += f"  (+{len(grupo) - 2} más)"
            titulo = f"Tienda {tienda}: {len(grupo)} nuevo{'s' if len(grupo) != 1 else ''}"
            notificar(titulo, lineas, url)
            for a in grupo:
                print("    -", resumen(a))

    # Guardamos solo lo que sigue en tienda, para avisar de nuevo si algo vuelve más adelante.
    if articulos:
        guardar_json(ARCHIVO_ESTADO, sorted(a["id"] for a in articulos))


def listar(config):
    for a in obtener_todo(config):
        marca = " <== LISTA DE DESEOS" if coincide(a, config["lista_de_deseos"]) else ""
        print(f"[{a['tienda']} / {a['seccion']}] {resumen(a)}{marca}")


def main():
    config = cargar_config()
    args = sys.argv[1:]
    if "--probar" in args:
        notificar("Notificador de tiendas", ["¡Las notificaciones funcionan!", "Clic para abrir la tienda de RL"], URL_RL)
    elif "--listar" in args:
        listar(config)
    elif "--una-vez" in args:
        revisar(config)
    else:
        minutos = max(5, int(config["minutos_entre_revisiones"]))
        log(f"Vigilando las tiendas cada {minutos} minutos. Ctrl+C para salir.")
        while True:
            try:
                revisar(config)
            except Exception as err:
                log(f"Error inesperado: {err}")
            time.sleep(minutos * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nListo, hasta luego.")
