"""
Versión en la nube del notificador: corre en GitHub Actions y publica la página en GitHub Pages.

Reutiliza todo notificador.py. La base SQLite se arma en cada corrida a partir de archivos JSON
(carpeta datos/, que es la rama "datos" del repo) y al terminar se vuelve a guardar en JSON.
La página no tiene servidor: lee los JSON que se exportan a sitio/datos/.

Uso (lo llama .github/workflows/nube.yml):
  python nube.py revisar     -> lee las tiendas, avisa por Discord, guarda y exporta
  python nube.py probar      -> manda un aviso de prueba a Discord, guarda y exporta
  python nube.py catalogo    -> fuerza la actualización del catálogo, guarda y exporta
  python nube.py exportar    -> solo vuelve a armar la página (p. ej. tras cambiar alertas)
  python nube.py importar tienda.db -> pasa una base local (versión de PC) a datos/

Variables de entorno: DISCORD_WEBHOOK (secreto de GitHub), GITHUB_REPOSITORY.
"""

import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import notificador as n
import rl_tienda as fuentes
from rl_tienda import log

CARPETA = Path(__file__).resolve().parent
DATOS = CARPETA / "datos"  # copia de trabajo de la rama "datos"
SITIO = CARPETA / "sitio"  # lo que se publica en GitHub Pages
ARCHIVO_ALERTAS = "alertas.json"  # lo escribe la página; el robot solo lo lee
TABLAS = ("articulos", "catalogo", "origenes", "historial_externo", "historial_rsn", "resumen_historial",
          "historial_detalle", "avisos", "meta")
MINUTO_CRON = 7  # .github/workflows/nube.yml revisa a los :07 de cada hora
FICHAS_POR_CORRIDA = 25  # historiales detallados que se piden a itemshop.gg / rlshopnotify en cada corrida
HORAS_CACHE_FICHA_NUBE = 24
COLUMNAS_ALERTA = ("id", "nombre", "color", "tipo", "rareza", "tienda", "precio_max", "activa", "exacto", "creada")


# ---------- configuración ----------

def escribir_config():
    """config.json de esta corrida: la plantilla del repo + el webhook del secreto. No se sube a git."""
    config = fuentes.leer_json(CARPETA / "config.example.json", {})
    config.update({
        "avisos_windows": False,
        "abrir_navegador": False,
        "lista_de_deseos": [],
        "discord_webhook_url": os.environ.get("DISCORD_WEBHOOK", "").strip(),
        "minutos_entre_revisiones": 60,
    })
    fuentes.guardar_json(fuentes.ARCHIVO_CONFIG, config)
    return config


# ---------- JSON <-> SQLite ----------

def escribir_tabla(ruta, columnas, filas):
    """Una fila por línea: así git guarda solo lo que cambió entre corridas."""
    lineas = ",\n".join(json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in filas)
    ruta.write_text('{"columnas":' + json.dumps(columnas, ensure_ascii=False) + ',\n"filas":[\n'
                    + lineas + "\n]}\n", encoding="utf-8")


def leer_tabla(ruta):
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if isinstance(datos, list):  # formato de lista de objetos (alertas.json)
        columnas = sorted({k for d in datos for k in d})
        return columnas, [[d.get(c) for c in columnas] for d in datos]
    return datos["columnas"], datos["filas"]


def cargar_en(con, tabla, columnas, filas):
    existentes = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
    usar = [i for i, c in enumerate(columnas) if c in existentes]
    if not usar:
        return
    nombres = ", ".join(columnas[i] for i in usar)
    con.execute(f"DELETE FROM {tabla}")
    con.executemany(f"INSERT OR REPLACE INTO {tabla} ({nombres}) VALUES ({','.join('?' * len(usar))})",
                    [[f[i] for i in usar] for f in filas])


def preparar():
    """Base SQLite temporal con lo que hay en datos/. Devuelve la config de esta corrida."""
    config = escribir_config()
    n.ARCHIVO_DB = Path(tempfile.mkdtemp()) / "tienda.db"
    n.HORAS_CACHE_FICHA = HORAS_CACHE_FICHA_NUBE
    n.MAX_CANTIDAD = 10 ** 6
    with n.conectar() as con:
        con.executescript(n.ESQUEMA)
    n.iniciar_db(config)  # columnas nuevas, igual que en la versión de PC
    DATOS.mkdir(exist_ok=True)
    with n.conectar() as con:
        for tabla in TABLAS + ("alertas",):
            archivo = DATOS / (ARCHIVO_ALERTAS if tabla == "alertas" else f"{tabla}.json")
            if archivo.exists():
                cargar_en(con, tabla, *leer_tabla(archivo))
        # Avisos de alertas que se borraron desde la página
        con.execute("DELETE FROM avisos WHERE alerta_id NOT IN (SELECT id FROM alertas)")
    n.iniciar_db(config)  # normaliza la categoría de alertas recién cargadas
    return config


def guardar():
    """De vuelta a datos/*.json (menos alertas.json, que es de la página)."""
    with n.conectar() as con:
        for tabla in TABLAS:
            cursor = con.execute(f"SELECT * FROM {tabla}")
            columnas = [d[0] for d in cursor.description]
            filas = [list(f) for f in cursor]
            filas.sort(key=lambda f: [str(x) for x in f[:3]])  # orden estable para diffs chicos
            escribir_tabla(DATOS / f"{tabla}.json", columnas, filas)
    if not (DATOS / ARCHIVO_ALERTAS).exists():
        (DATOS / ARCHIVO_ALERTAS).write_text("[]\n", encoding="utf-8")


def importar(ruta_db):
    """Pasa la base de la versión de PC (tienda.db) a datos/, alertas incluidas."""
    DATOS.mkdir(exist_ok=True)
    origen = sqlite3.connect(f"file:{ruta_db}?mode=ro", uri=True)
    origen.row_factory = sqlite3.Row
    for tabla in TABLAS:
        cursor = origen.execute(f"SELECT * FROM {tabla}")
        columnas = [d[0] for d in cursor.description]
        filas = sorted((list(f) for f in cursor), key=lambda f: [str(x) for x in f[:3]])
        escribir_tabla(DATOS / f"{tabla}.json", columnas, filas)
    alertas = [{c: f[c] for c in COLUMNAS_ALERTA} for f in origen.execute("SELECT * FROM alertas ORDER BY id")]
    escribir_alertas(alertas)
    log(f"Importé {len(alertas)} alertas y {len(TABLAS)} tablas desde {ruta_db}")


def escribir_alertas(alertas):
    (DATOS / ARCHIVO_ALERTAS).write_text(
        "[\n" + ",\n".join(json.dumps(a, ensure_ascii=False) for a in alertas) + "\n]\n", encoding="utf-8")


# ---------- estado de la revisión (lo que en la PC vive en memoria) ----------

def guardar_estado_revision(config):
    with n.conectar() as con:
        n.meta(con, "nube_ultima", n.Estado.ultima or n.ahora())
        n.meta(con, "nube_resumen", n.Estado.resumen)
        n.meta(con, "nube_errores", json.dumps(n.Estado.errores, ensure_ascii=False))
        n.meta(con, "nube_discord", "1" if config.get("discord_webhook_url") else "0")


def cargar_estado_revision(config):
    with n.conectar() as con:
        n.Estado.ultima = n.meta(con, "nube_ultima")
        n.Estado.resumen = n.meta(con, "nube_resumen") or "Todavía no se revisó"
        n.Estado.errores = json.loads(n.meta(con, "nube_errores") or "[]")
        discord = n.meta(con, "nube_discord") == "1"
    ahora = datetime.now(timezone.utc)
    proxima = ahora.replace(minute=MINUTO_CRON, second=0, microsecond=0)
    if proxima <= ahora:
        proxima += timedelta(hours=1)
    n.Estado.proxima_periodica = proxima
    n.Estado.proxima_fija = n.proxima_hora_fija(config, ahora)
    return discord


# ---------- fichas ----------

def clave_ficha(catalogo_id):
    """Nombre de archivo de una ficha (la página usa la misma regla)."""
    return re.sub(r"[^a-z0-9-]+", "_", catalogo_id.lower()).strip("_")


def ids_con_ficha():
    """Artículos que merecen ficha completa: con alerta, en la tienda hoy o vistos por el notificador."""
    ids = set()
    for vista in ("alerta", "hoy"):
        ids |= {f["id"] for f in n.catalogo_api({"vista": [vista], "cantidad": [str(n.MAX_CANTIDAD)]})["articulos"]}
    with n.conectar() as con:
        ids |= set(n.vistos_propios(con))
    return ids


def refrescar_fichas(ids, cuantas=FICHAS_POR_CORRIDA):
    """Pide el historial detallado de las fichas más viejas (unas pocas por corrida, sin saturar los sitios)."""
    with n.conectar() as con:
        filas = {f["id"]: f["producto_id"] for f in con.execute("SELECT id, producto_id FROM catalogo")}
        def pedido(cid):
            return n.meta(con, f"rsn:{filas.get(cid)}") or ""
        orden = sorted((cid for cid in ids if filas.get(cid)), key=pedido)
    limite = (datetime.now(timezone.utc) - timedelta(hours=HORAS_CACHE_FICHA_NUBE)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hechas = 0
    for cid in orden:
        if hechas >= cuantas:
            break
        with n.conectar() as con:
            if (n.meta(con, f"rsn:{filas[cid]}") or "") >= limite:
                continue
        try:
            n.ficha_api({"id": [cid]})
        except Exception as err:
            log(f"Ficha {cid}: {err}")
        hechas += 1
        time.sleep(1)
    log(f"Fichas: {hechas} historiales actualizados de {len(orden)} artículos con ficha")


# ---------- exportar la página ----------

def escribir(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def exportar(config):
    discord = cargar_estado_revision(config)
    if SITIO.exists():
        shutil.rmtree(SITIO)
    shutil.copytree(CARPETA / "web", SITIO)
    (SITIO / ".nojekyll").write_text("", encoding="utf-8")
    salida = SITIO / "datos"

    estado = n.estado_api()
    estado["canales"] = {"discord": discord}
    estado["revision"]["revisando"] = False
    repo = os.environ.get("GITHUB_REPOSITORY", "Gio-glitch04/RL-Notifier")
    estado["nube"] = {
        "generado": n.ahora(), "repo": repo, "rama_datos": "datos",
        "rama_codigo": os.environ.get("RAMA_CODIGO", "main-web"), "workflow": "nube.yml",
        "archivo_alertas": ARCHIVO_ALERTAS,
    }
    estado["sinonimos"] = n.SINONIMOS_CATEGORIA
    escribir(salida / "estado.json", estado)
    escribir(salida / "historial.json", n.historial_api())

    catalogo = n.catalogo_api({"cantidad": [str(n.MAX_CANTIDAD)]})
    for f in catalogo["articulos"]:
        f.pop("alertas", None)  # la página las calcula con las alertas del momento
        f.pop("actualizado", None)
        f.pop("clave", None)
        if f.get("url") == n.URL_CATALOGO_BASE + f["id"]:
            f.pop("url")  # la página la arma igual: rl.source.gs + id
        for o in f["origenes"]:
            o.pop("catalogo_id", None)
    ids = ids_con_ficha()
    catalogo["fichas"] = sorted(clave_ficha(i) for i in ids)
    catalogo.update(actualizando=False, progreso="", error="")
    escribir(salida / "catalogo.json", catalogo)

    for cid in ids:
        try:
            escribir(salida / "fichas" / f"{clave_ficha(cid)}.json", n.ficha_api({"id": [cid]}, consultar_fuentes=False))
        except Exception as err:
            log(f"No pude armar la ficha {cid}: {err}")
    log(f"Página exportada en {SITIO}: {len(estado['articulos'])} en tienda, "
        f"{len(catalogo['articulos'])} en el catálogo, {len(ids)} fichas")


# ---------- acciones ----------

def main():
    accion = sys.argv[1] if len(sys.argv) > 1 else "revisar"
    if accion == "importar":
        return importar(sys.argv[2])
    config = preparar()
    if accion == "revisar":
        n.revisar()
        guardar_estado_revision(config)
        if n.catalogo_vencido():
            n.actualizar_catalogo()
        elif n.historial_vencido():
            try:
                n.actualizar_historial_externo()
            except Exception as err:
                log(f"No pude leer el historial de itemshop.gg: {err}")
        refrescar_fichas(ids_con_ficha())
    elif accion == "catalogo":
        n.actualizar_catalogo()
    elif accion == "probar":
        resultado = n.prueba_aviso()
        with n.conectar() as con:  # el botón de la página acaba de guardar (o cambiar) el webhook
            n.meta(con, "nube_discord", "1" if config.get("discord_webhook_url") else "0")
        log(f"Aviso de prueba: {resultado}")
        if resultado.get("discord") != "ok":
            print(f"::warning::Discord: {resultado.get('discord')}")
    elif accion != "exportar":
        sys.exit(f"Acción desconocida: {accion}")
    guardar()
    exportar(config)


if __name__ == "__main__":
    main()
