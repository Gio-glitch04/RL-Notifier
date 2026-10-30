"""Prueba temporal: ¿responden las fuentes desde los servidores de GitHub Actions?"""
import json, sys, traceback
sys.path.insert(0, ".")
import rl_tienda, origenes

def probar(nombre, fn):
    try:
        r = fn()
        print(f"OK    {nombre}: {r}")
    except Exception as e:
        print(f"FALLA {nombre}: {type(e).__name__}: {e}")

cfg = {"idioma_fortnite": "es-419", "tipos_fortnite": ["lote", "carroceria", "ruedas", "propulsor", "rastro", "calcomania"], "secciones_rl_ignoradas": []}
probar("itemshop.gg tienda", lambda: f"{len(rl_tienda.rl_desde_itemshop())} artículos")
probar("RL Portal tienda", lambda: f"{len(rl_tienda.rl_desde_portal())} artículos")
probar("fortnite-api", lambda: f"{len(rl_tienda.tienda_fortnite(cfg))} vehículos")
probar("rl.source.gs catálogo", lambda: f"{len(json.loads(rl_tienda.descargar('https://rl.source.gs/items/wheels/index.json')))} ruedas")
probar("itemshop.gg historial", lambda: f"{len(origenes.historial_itemshop())} entradas")
probar("rlshopnotify API", lambda: f"{len(json.dumps(origenes.historial_rlshopnotify(4962)))} bytes (Ruinator)")
probar("Fandom wiki API", lambda: f"{len(origenes.textos_wiki(['Ruinator']))} páginas")
