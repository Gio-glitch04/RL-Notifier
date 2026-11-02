"""
Datos extra para el catálogo: historial de tienda y origen de cada artículo de Rocket League.

Fuentes (todas públicas; se respeta su robots.txt y se hacen pocos pedidos, con pausa):
  - itemshop.gg/rocket-league/catalogue: 1 página con los artículos que pasaron por la tienda
    (veces, primera y última vez, último precio, colores). Registra desde septiembre de 2026.
  - itemshop.gg/rocket-league/catalogue/<artículo>: historial completo de un artículo
    (fechas, precio, sección). Se pide solo al abrir su ficha.
  - Wiki de Rocket League en Fandom (API MediaWiki, permitida en su robots.txt): recompensas de
    cada Rocket Pass (páginas "Rocket Pass N" y "Season N") y subpáginas por origen
    (tienda de esports, recompensas competitivas, exclusivos de plataforma, packs).
  - rl.source.gs/packs/: qué trae cada pack de contenido descargable (DLC).

Las funciones devuelven datos ya limpios; notificador.py los guarda en tienda.db.
"""

import html
import json
import re
import time
import unicodedata
import urllib.parse
from datetime import datetime

from rl_tienda import datos_next, descargar

URL_ITEMSHOP_CATALOGO = "https://itemshop.gg/rocket-league/catalogue"
URL_WIKI_API = "https://rocketleague.fandom.com/api.php"
URL_PACKS = "https://rl.source.gs/packs/"
PAUSA = 1.5  # segundos entre pedidos al mismo sitio

# Ids de pintura que usa el juego (comprobados con la tienda: 4 = Sky Blue, 12 = Titanium White)
PINTURAS = {1: "Crimson", 2: "Lime", 3: "Black", 4: "Sky Blue", 5: "Cobalt", 6: "Burnt Sienna",
            7: "Forest Green", 8: "Purple", 9: "Pink", 10: "Orange", 11: "Grey", 12: "Titanium White",
            13: "Saffron", 14: "Gold"}

# Sufijo de los archivos de la wiki ("Ruinator wheel icon.png") -> tipo del catálogo
TIPOS_WIKI = {
    "wheel": "Wheels", "wheels": "Wheels", "decal": "Decal", "topper": "Topper", "antenna": "Antenna",
    "trail": "Trail", "rocket boost": "Rocket Boost", "boost": "Rocket Boost", "goal explosion": "Goal Explosion",
    "paint finish": "Paint Finish", "player banner": "Player Banner", "banner": "Player Banner",
    "avatar border": "Avatar Border", "engine audio": "Engine Audio", "car": "Body", "body": "Body",
    "player anthem": "Player Anthem",
}
TIPOS_SUBPAGINA = {"Antenna": "Antenna", "Decal": "Decal", "Goal Explosion": "Goal Explosion",
                   "Paint Finish": "Paint Finish", "Player Banner": "Player Banner", "Rocket Boost": "Rocket Boost",
                   "Topper": "Topper", "Vehicle": "Body", "Wheels": "Wheels", "Esports Shop": ""}
UA_WIKI = "RL-Notifier-local/1.0 (herramienta personal; pocos pedidos por semana)"


def slug(texto):
    """'Outlaw: Sally' -> 'outlaw-sally' (como las direcciones de rl.source.gs)."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    t = t.replace("&", " and ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def fecha_inglesa(texto):
    """'8 Oct 2026' -> '2026-10-08'."""
    try:
        return datetime.strptime(texto.strip(), "%d %b %Y").strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return ""


# ---------- itemshop.gg ----------

def historial_itemshop():
    """Resumen de todo lo que pasó por la tienda según itemshop.gg (un solo pedido)."""
    datos = datos_next(descargar(URL_ITEMSHOP_CATALOGO))
    resultado = {}
    for m in re.finditer(r'\{"id":\d+,"name":', datos):
        try:
            o, _ = json.JSONDecoder().raw_decode(datos, m.start())
        except ValueError:
            continue
        tienda = o.get("shop")
        if not isinstance(tienda, dict) or not isinstance(o.get("id"), int):
            continue
        url = o.get("url") or ""
        resultado[o["id"]] = {
            "producto_id": o["id"],
            "veces": tienda.get("timesSeen") or 0,
            "primera": tienda.get("firstSeen") or "",
            "ultima": tienda.get("lastSeen") or "",
            "ultimo_precio": tienda.get("lastPrice"),
            "en_tienda": 1 if tienda.get("inShop") else 0,
            "pinturas": [PINTURAS.get(p, f"Pintura {p}") for p in tienda.get("paints") or []],
            "url_catalogo": url,  # dirección en rl.source.gs (sirve para unir con el catálogo)
            "slug": url.rstrip("/").rsplit("/", 1)[-1] if url else "",
        }
    if not resultado:
        raise RuntimeError("itemshop.gg no trajo artículos (¿cambió la página?)")
    return list(resultado.values())


def historial_detalle_itemshop(slug_articulo):
    """Cada vez que un artículo estuvo en la tienda, según su ficha en itemshop.gg."""
    pagina = descargar(f"{URL_ITEMSHOP_CATALOGO}/{urllib.parse.quote(slug_articulo)}")
    datos = datos_next(pagina)
    inicio = datos.find('"item-history"')
    if inicio < 0:
        return []
    fin = datos.find('"section"', inicio + 20)
    tramo = datos[inicio:fin if fin > 0 else inicio + 60000]
    filas = []
    for fila in re.findall(r'\["\$","tr","\d+",\{.*?\}\]\]\}\]', tramo):
        celdas = re.findall(r'"td",null,\{[^{}]*"children":"([^"]*)"', fila)
        if len(celdas) >= 5:
            filas.append({"llegada": fecha_inglesa(celdas[0]), "salida": fecha_inglesa(celdas[1]) or celdas[1],
                          "duracion": celdas[2], "precio": celdas[3], "seccion": celdas[4]})
    return filas


# ---------- wiki (Fandom) ----------

def pedir_wiki(**params):
    params["format"] = "json"
    url = URL_WIKI_API + "?" + urllib.parse.urlencode(params)
    datos = json.loads(descargar(url, cabeceras={"User-Agent": UA_WIKI}))
    time.sleep(PAUSA)
    return datos


def textos_wiki(titulos):
    textos = {}
    for i in range(0, len(titulos), 50):
        d = pedir_wiki(action="query", titles="|".join(titulos[i:i + 50]), prop="revisions",
                       rvprop="content", rvslots="main")
        for p in d.get("query", {}).get("pages", {}).values():
            if p.get("revisions"):
                textos[p["title"]] = p["revisions"][0]["slots"]["main"]["*"]
    return textos


# Palabras en el nombre del archivo -> tipo ("UG66Wheel.webp", "Ruinator wheel icon.png", "... - Vehicle.png")
PALABRAS_TIPO = [("goalexplosion", "Goal Explosion"), ("paintfinish", "Paint Finish"),
                 ("avatarborder", "Avatar Border"), ("playerbanner", "Player Banner"), ("banner", "Player Banner"),
                 ("engineaudio", "Engine Audio"), ("engine", "Engine Audio"), ("anthem", "Player Anthem"),
                 ("rocketboost", "Rocket Boost"), ("boost", "Rocket Boost"), ("wheel", "Wheels"),
                 ("decal", "Decal"), ("topper", "Topper"), ("antenna", "Antenna"), ("trail", "Trail"),
                 ("vehicle", "Body"), ("body", "Body"), ("car", "Body")]
NO_ARTICULOS = re.compile(r"^(\d[\d,.]*\s*Credits|Title\b|\d+% .*XP|.*XP Boost|.*Blueprint\b|Tier\b)", re.I)


def tipo_de_archivo(archivo):
    a = re.sub(r"[^a-z]", "", archivo.lower().rsplit(".", 1)[0]).replace("icon", "")
    for palabra, tipo in PALABRAS_TIPO:
        if palabra in a:
            return tipo
    return ""


def limpiar_nombre(texto):
    texto = re.sub(r"\[\[File:[^\]]*\]\]", "", texto)  # p.ej. el logo de Fortnite
    texto = re.sub(r"\{\{[^}]*\}\}|'{2,3}|<[^>]+>", "", texto)
    texto = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", texto)
    return html.unescape(texto).strip(" |")


def articulos_en_texto(texto):
    """Lee tablas ('|[[File:X.png|thumbnail]]<br>Nombre') y galerías ('X.png|Nombre (Tier N)|...')."""
    encontrados = []
    for linea in texto.splitlines():
        linea = linea.strip()
        celda = re.match(r"^\|\s*\[\[File:([^|\]]+)[^\]]*\]\]\s*<br\s*/?>\s*(.+)$", linea)
        galeria = re.match(r"^([^|\[\]<>=]+\.(?:png|jpg|jpeg|gif|webp))\|([^|]+)", linea, re.I)
        if celda:
            archivo, nombre = celda[1], celda[2]
        elif galeria:
            archivo, nombre = galeria[1], galeria[2]
        else:
            continue
        nivel = re.search(r"\(\s*Tier\s*(\d+)\s*\)", nombre, re.I)
        nombre = re.sub(r"\s*\((?:Tier|Pro Tier)[^)]*\)\s*", " ", limpiar_nombre(nombre)).strip()
        nombre = re.sub(r"\s*\[[^\]]*\]\s*$", "", nombre)  # "Divine Intervention [Forest Green]"
        tipo = tipo_de_archivo(archivo)
        if nombre and tipo and not NO_ARTICULOS.match(nombre):
            encontrados.append({"nombre": nombre, "tipo": tipo, "nivel": int(nivel[1]) if nivel else None})
    return encontrados


def seccion_rocket_pass(texto):
    m = re.search(r"^==\s*Rocket Pass\s*==\s*$", texto, re.M)
    if not m:
        return ""
    fin = re.search(r"^==[^=].*==\s*$", texto[m.end():], re.M)
    return texto[m.end():m.end() + fin.start()] if fin else texto[m.end():]


def clasificar_seccion(seccion):
    """'Season 4 Rocket Pass' -> ('Rocket Pass', 'Temporada 4'). None si no es un origen útil."""
    s = seccion.strip()
    if m := re.match(r"Season (\d+) Rocket Pass", s, re.I):
        return "Rocket Pass", f"Temporada {m[1]}"
    if m := re.match(r"Rocket Pass (\d+)", s, re.I):
        return "Rocket Pass", f"Rocket Pass {m[1]} (antes del free-to-play)"
    if re.match(r"Esports Shop", s, re.I):
        return "Tienda de esports", ""
    if m := re.match(r"Competitive Season (\d+)", s, re.I):
        return "Recompensa competitiva", f"Temporada competitiva {m[1]}"
    if re.match(r"Platform Exclusive", s, re.I):
        return "Exclusivo de plataforma", ""
    if re.search(r"\bPack\b|^WWE$", s, re.I):
        return "Pack", s
    if re.match(r"Tournament", s, re.I):
        return "Torneos", ""
    return None


def origenes_wiki():
    """Lista de {nombre, tipo, origen, detalle, nivel} según la wiki."""
    resultado = []
    # 1) Recompensas de cada Rocket Pass: "Rocket Pass 1..9" (antes del free-to-play) y "Season 1..40"
    titulos = [f"Rocket Pass {n}" for n in range(1, 10)] + [f"Season {n}" for n in range(1, 41)]
    for titulo, texto in textos_wiki(titulos).items():
        if titulo.startswith("Season"):
            texto = seccion_rocket_pass(texto)
            detalle = "Temporada " + titulo.split()[-1]
        else:
            detalle = titulo + " (antes del free-to-play)"
        for a in articulos_en_texto(texto):
            resultado.append({**a, "origen": "Rocket Pass", "detalle": detalle})
    # 2) Subpáginas por origen ("Wheels/S4RP" -> "Data for [[Wheels#Season 4 Rocket Pass]]")
    categorias = [c["*"] for c in pedir_wiki(action="query", list="allcategories", aclimit=500)
                  .get("query", {}).get("allcategories", []) if c["*"].lower().endswith(" subpages")]
    subpaginas = []
    for c in categorias:
        d = pedir_wiki(action="query", list="categorymembers", cmtitle="Category:" + c, cmlimit=500, cmnamespace=0)
        subpaginas += [m["title"] for m in d.get("query", {}).get("categorymembers", [])]
    for titulo, texto in textos_wiki(sorted(set(subpaginas))).items():
        m = re.search(r"Data for \[\[[^#\]]*#([^\]|]+)", texto)
        clase = clasificar_seccion(m[1]) if m else None
        if not clase:
            continue  # listas por rareza u otras que no dicen de dónde sale el artículo
        tipo_pagina = TIPOS_SUBPAGINA.get(titulo.split("/")[0], "")
        for a in articulos_en_texto(texto):
            resultado.append({**a, "tipo": tipo_pagina or a["tipo"], "origen": clase[0], "detalle": clase[1]})
    # 3) Recompensas de torneo: página "Tournaments", una pestaña por temporada ("|-|S24=")
    for a in recompensas_torneo(textos_wiki(["Tournaments"]).get("Tournaments", "")):
        resultado.append(a)
    return resultado


def recompensas_torneo(texto):
    """Serie Accolade de cada temporada (se canjea con créditos de torneo): {nombre, tipo, origen, detalle, nivel}."""
    m = re.search(r"^==\s*Tournament Rewards\s*==\s*$", texto, re.M)
    if not m:
        return []
    fin = re.search(r"^==[^=].*==\s*$", texto[m.end():], re.M)
    texto = texto[m.end():m.end() + fin.start()] if fin else texto[m.end():]
    resultado = []
    pestanas = re.split(r"^\|-\|\s*S(\d+)\s*=\s*$", texto, flags=re.M)
    for temporada, cuerpo in zip(pestanas[1::2], pestanas[2::2]):
        serie = re.search(r"Accolade\s+([IVXLC]+)\s+Series", cuerpo)
        detalle = f"Temporada {temporada}" + (f" (Accolade {serie[1]})" if serie else "")
        for a in articulos_en_texto(cuerpo):
            resultado.append({**a, "nivel": None, "origen": "Torneos", "detalle": detalle})
    return resultado


# ---------- rl.source.gs: packs DLC ----------

def origenes_packs():
    """Lista de {url_catalogo, origen='Pack', detalle=nombre del pack}."""
    pagina = descargar(URL_PACKS)
    resultado = []
    for sec in re.finditer(r'<section id="[^"]+"[^>]*>(.*?)</section>', pagina, re.S):
        titulo = re.search(r'<h2[^>]*>(.*?)</h2>', sec[1], re.S)
        if not titulo:
            continue
        nombre = html.unescape(re.sub(r"<[^>]+>", "", titulo[1])).strip()
        for ruta in re.findall(r'href="(/items/[a-z0-9-]+/[a-z0-9-]+/)"', sec[1]):
            resultado.append({"url_catalogo": "https://rl.source.gs" + ruta, "origen": "Pack",
                              "detalle": f"{nombre} (DLC)"})
    return resultado


# ---------- rlshopnotify.com ----------
# Dirección pública que usa la propia página (la encontró Giovanni con F12). Un artículo por pedido,
# solo al abrir su ficha. Los ids son los mismos que los del catálogo (4962 = Ruinator).
URL_RLSHOPNOTIFY_API = "https://api.rlshopnotify.com/api/items/{}"
URL_RLSHOPNOTIFY_WEB = "https://rlshopnotify.com/items/{}"
UA_NOTIFICADOR = "RL-Notifier-local/1.0 (herramienta personal; un pedido al abrir una ficha)"


def historial_rlshopnotify(producto_id):
    """Cada aparición de un artículo en la tienda según rlshopnotify.com (con color y lotes)."""
    datos = json.loads(descargar(URL_RLSHOPNOTIFY_API.format(int(producto_id)),
                                 cabeceras={"User-Agent": UA_NOTIFICADOR, "Accept": "application/json"}))
    apariciones, vistas = [], set()
    for a in datos.get("appearances") or []:
        seccion = " · ".join(x for x in (a.get("shop_section"), a.get("subsection")) if x)
        apariciones.append({
            "id": a.get("appearance_id"),
            "llegada": (a.get("starts_at") or a.get("fetched_at") or "")[:10],
            "salida": (a.get("ends_at") or "")[:10],
            "precio": a.get("price_credits"),
            "seccion": seccion,
            "pintura": a.get("paint_name") or "",
            "lote": bool(a.get("bundle_listing") or a.get("bundle_subsection_row")),
        })
        # La API repite la misma rotación una vez por cada lectura diaria que hizo: se deja una sola
        clave = tuple(apariciones[-1][k] for k in ("llegada", "salida", "seccion", "pintura", "precio", "lote"))
        if clave in vistas:
            apariciones.pop()
        vistas.add(clave)
    return apariciones


# ---------- Wiki: packs de temporada y drops ----------
# Packs que se compran con dinero real (Rookie, Veteran, Elite, Rocketeer...): la lista sale de la página
# "Item Shop" de la wiki, que dice cuáles siguen a la venta; el contenido, de la página de cada pack
# (la wiki solo lo tiene para algunas temporadas). Drops: la página "Trade-in Items" lista todo lo que
# puede salir de un drop, con su rareza.

PACK_TEMPORADA = re.compile(r"^Season (\d+) (Rookie|Veteran|Elite|Rocketeer|Starter|Customization) Pack$")
# Rarezas de la wiki (nombres nuevos y viejos) -> nombre de la escala de RL
RAREZAS_WIKI = {"sport": "Uncommon", "uncommon": "Uncommon", "special": "Rare", "rare": "Rare",
                "deluxe": "Very Rare", "very rare": "Very Rare", "import": "Import", "exotic": "Exotic",
                "black market": "Black Market", "limited": "Limited", "premium": "Premium", "common": "Common"}
# Drops por rareza (cada uno da un artículo de su rareza o mayor)
DROPS = [("Sport", "Uncommon"), ("Special", "Rare"), ("Deluxe", "Very Rare"), ("Import", "Import"),
         ("Exotic", "Exotic"), ("Black Market", "Black Market")]
SECCIONES_TRADE_IN = {"Body": "Body", "Decal": "Decal", "Goal Explosion": "Goal Explosion",
                      "Paint Finish": "Paint Finish", "Player Banner": "Player Banner", "Rocket Boost": "Rocket Boost",
                      "Trail": "Trail", "Wheel": "Wheels", "Topper": "Topper", "Antenna": "Antenna"}
TIPOS_PACK = {"body": "Body", "vehicle": "Body", "car": "Body", "decal": "Decal", "animated decal": "Decal",
              "wheels": "Wheels", "wheel": "Wheels", "goal explosion": "Goal Explosion", "rocket boost": "Rocket Boost",
              "boost": "Rocket Boost", "trail": "Trail", "topper": "Topper", "antenna": "Antenna",
              "player banner": "Player Banner", "banner": "Player Banner", "avatar border": "Avatar Border",
              "engine audio": "Engine Audio", "paint finish": "Paint Finish", "player anthem": "Player Anthem"}
NOMBRES_PINTURA = {p.lower(): p for p in PINTURAS.values()}


def limpiar_celda(celda):
    """'[[Vehicle|Body]]' -> 'Body', '{{rarity|Import}}' -> 'Import', '[[Tygris]]' -> 'Tygris'."""
    c = re.sub(r"\{\{\s*rarity\s*\|\s*([^}|]+)\}\}", r"\1", celda, flags=re.I)
    c = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", c)
    c = re.sub(r"<[^>]+>|'''?|\{\{[^}]*\}\}", "", c)
    return html.unescape(c).strip()


def filas_tabla(texto):
    """Celdas de cada fila de las tablas de un wikitexto, sin las celdas que solo tienen una imagen."""
    filas = []
    for tabla in re.findall(r"\{\|(.*?)\n\|\}", texto, re.S):
        for fila in tabla.split("\n|-")[1:]:
            celdas = []
            for linea in fila.split("\n"):
                if not linea.startswith("|") or linea.startswith(("|+", "|}", "|-")):
                    continue
                for celda in linea[1:].split("||"):
                    if re.fullmatch(r"\s*\[\[File:[^\]]*\]\]\s*", celda):
                        continue
                    celdas.append(limpiar_celda(celda))
            if celdas:
                filas.append(celdas)
    return filas


def separar_pintura(nombre):
    """'Octane (Crimson)' -> ('Octane', 'Crimson'); 'Batmobile (2016)' queda igual."""
    m = re.fullmatch(r"(.*?)\s*\(([^)]+)\)", nombre)
    if m and m[2].lower() in NOMBRES_PINTURA:
        return m[1], NOMBRES_PINTURA[m[2].lower()]
    return nombre, ""


def lista_packs_temporada(texto_item_shop):
    """Packs de temporada según la página 'Item Shop': nombre, temporada, tipo, si sigue a la venta e imagen."""
    inicio = texto_item_shop.find("==Item Packs==")
    fin = texto_item_shop.find("===Item Bundles===", inicio)
    packs = {}
    for linea in texto_item_shop[inicio:fin if fin > 0 else None].split("\n"):
        m = re.match(r"\s*(?:File:)?([^|\[\]]+?)\s*\|\s*link=([^|]+?)\s*\|(.*)$", linea)
        if not m or not (t := PACK_TEMPORADA.match(m[2].strip())):
            continue
        packs[m[2].strip()] = {"nombre": m[2].strip(), "temporada": int(t[1]), "tipo": t[2], "archivo": m[1].strip(),
                               "disponible": "no longer available" not in m[3].lower()}
    return list(packs.values())


def contenido_pack(texto):
    """Artículos de la página de un pack (sin créditos ni títulos) + precio y fechas del recuadro."""
    articulos = []
    for celdas in filas_tabla(texto):
        if len(celdas) < 3:
            continue
        nombre, tipo, rareza = celdas[0], celdas[1], celdas[2]
        tipo_catalogo = TIPOS_PACK.get(tipo.lower())
        if not tipo_catalogo:
            continue  # créditos, títulos, etc.
        nombre, pintura = separar_pintura(nombre)
        articulos.append({"nombre": nombre, "pintura": pintura, "tipo": tipo_catalogo,
                          "rareza": RAREZAS_WIKI.get(rareza.lower(), rareza)})
    dato = lambda clave: (re.search(rf"^\|\s*{clave}\s*=\s*(.*)$", texto, re.M) or [None, ""])[1]
    fecha_de = lambda v: (re.search(r"\d{4}-\d{2}-\d{2}", v) or [""])[0]
    precio = re.sub(r"\s*or regional equivalent", " o equivalente regional", limpiar_celda(dato("price")))
    return articulos, precio, fecha_de(dato("released")), fecha_de(dato("retired"))


def packs_temporada():
    """Packs de temporada con contenido (cuando la wiki lo tiene), imagen, precio y fechas."""
    texto = textos_wiki(["Item Shop"]).get("Item Shop", "")
    packs = lista_packs_temporada(texto)
    if not packs:
        raise RuntimeError("no encontré la lista de packs en la página 'Item Shop' de la wiki")
    imagenes = {}
    archivos = sorted({"File:" + p["archivo"] for p in packs})
    for i in range(0, len(archivos), 50):
        d = pedir_wiki(action="query", titles="|".join(archivos[i:i + 50]), prop="imageinfo", iiprop="url")
        for pag in d.get("query", {}).get("pages", {}).values():
            if pag.get("imageinfo"):
                imagenes[pag["title"]] = pag["imageinfo"][0]["url"]
        for n in d.get("query", {}).get("normalized", []):  # "File:x.jpg" puede volver con otro nombre
            if n["to"] in imagenes:
                imagenes[n["from"]] = imagenes[n["to"]]
    paginas = textos_wiki([p["nombre"] for p in packs])
    for p in packs:
        p["imagen"] = imagenes.get("File:" + p["archivo"], "")
        p["contenido"], p["precio"], p["lanzado"], p["retirado"] = contenido_pack(paginas.get(p["nombre"], ""))
        p["url"] = "https://rocketleague.fandom.com/wiki/" + urllib.parse.quote(p["nombre"].replace(" ", "_"))
    return packs


def articulos_drops(texto):
    """Lo que puede salir de un drop, según 'Trade-in Items': {nombre, tipo, rareza}."""
    resultado = []
    secciones = re.split(r"^==\s*([^=]+?) Items\s*==\s*$", texto, flags=re.M)
    for titulo, cuerpo in zip(secciones[1::2], secciones[2::2]):
        tipo = SECCIONES_TRADE_IN.get(titulo.strip())
        if not tipo:
            continue
        for celdas in filas_tabla(cuerpo):
            rareza = next((RAREZAS_WIKI[c.lower()] for c in celdas[1:] if c.lower() in RAREZAS_WIKI), "")
            if not celdas[0] or not rareza:
                continue
            nombre = celdas[0]
            if tipo == "Decal" and len(celdas) >= 4 and celdas[1].lower() not in ("universal", "all", "any", ""):
                nombre = f"{celdas[1]}: {nombre}"  # como en la tienda: "Breakout: Chainsaw"
            resultado.append({"nombre": nombre, "tipo": tipo, "rareza": rareza})
    return resultado


def drops_wiki():
    return articulos_drops(textos_wiki(["Trade-in Items"]).get("Trade-in Items", ""))
