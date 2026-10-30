"use strict";
// Versión en la nube: la página no tiene servidor. Lee los JSON que publica GitHub Actions
// (carpeta datos/) y, para cambiar alertas o pedir una revisión, usa la API de GitHub con una
// clave personal que se guarda solo en este navegador.
//
// app.js llama a api("/api/...") igual que en la versión de PC; aquí se responde cada ruta.

const nube = { estado: null, catalogo: null, sinonimos: {} };
const URL_CATALOGO = "https://rl.source.gs";
const ESCALA_RAREZAS = ["Common", "Uncommon", "Rare", "Very Rare", "Import", "Exotic", "Black Market"];
const RAREZAS_ESPECIALES = ["Limited", "Premium", "Legacy"];
const CAMPOS_TEXTO = ["nombre", "color", "tipo", "rareza"];
const TIENDAS = ["Rocket League", "Fortnite"];
const POR_PAGINA = 120;
const MINUTOS_ESPERA = 15; // después de esto se deja de esperar a GitHub

// ---------- almacenamiento local (puede no estar disponible) ----------
function leerLocal(clave) {
  try { return JSON.parse(localStorage.getItem(clave) || "null"); } catch (e) { return null; }
}
function guardarLocal(clave, valor) {
  try {
    if (valor == null) localStorage.removeItem(clave);
    else localStorage.setItem(clave, JSON.stringify(valor));
  } catch (e) { /* sin almacenamiento: solo esta vez */ }
}

// ---------- utilidades iguales a notificador.py ----------
const normalizar = (s) => String(s ?? "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

function categoriaDe(tipo) {
  const t = normalizar(tipo).trim();
  if (!t) return "";
  if (t.includes("bundle") || t.startsWith("lote") || t.includes(",")) return "Lote";
  if (t.includes("decal") || t.includes("calcomania")) return "Calcomanía";
  return nube.sinonimos[t] || "";
}

function coincide(al, a) {
  let hay = false;
  for (const campo of CAMPOS_TEXTO) {
    const buscado = normalizar(al[campo]).trim();
    if (!buscado) continue;
    hay = true;
    const valor = normalizar(a[campo]).trim();
    if (campo === "tipo" && categoriaDe(al.tipo)) {
      if (categoriaDe(al.tipo) !== categoriaDe(a.tipo)) return false;
    } else if (campo === "nombre" && al.exacto) {
      if (buscado !== valor) return false;
    } else if (!valor.includes(buscado)) return false;
  }
  if (al.tienda) {
    hay = true;
    if (al.tienda !== a.tienda) return false;
  }
  if (al.precio_max != null) {
    hay = true;
    if (a.precio_num == null || a.precio_num > al.precio_max) return false;
  }
  return hay;
}

function describirAlerta(al) {
  const partes = CAMPOS_TEXTO.filter((c) => al[c]).map((c) => `${c}${c === "nombre" && al.exacto ? " (exacto)" : ""}: ${al[c]}`);
  partes.push(al.tienda ? `tienda: ${al.tienda}` : "tiendas: ambas");
  if (al.precio_max != null) partes.push(`precio ≤ ${al.precio_max}`);
  return partes.join(", ") || "(vacía)";
}

function limpiarAlerta(d) {
  const al = {};
  for (const c of CAMPOS_TEXTO) al[c] = String(d[c] ?? "").trim().slice(0, 100);
  al.tipo = categoriaDe(al.tipo) || al.tipo;
  al.tienda = TIENDAS.includes(d.tienda) ? d.tienda : "";
  if (d.precio_max === null || d.precio_max === undefined || d.precio_max === "") al.precio_max = null;
  else if (/^\s*\d+\s*$/.test(String(d.precio_max))) al.precio_max = parseInt(d.precio_max, 10);
  else throw new Error("El precio máximo debe ser un número");
  al.activa = [false, 0, "0"].includes(d.activa) ? 0 : 1;
  al.exacto = [true, 1, "1"].includes(d.exacto) ? 1 : 0;
  if (!CAMPOS_TEXTO.some((c) => al[c]) && !al.tienda && al.precio_max == null) throw new Error("La alerta necesita al menos un criterio");
  return al;
}

// El catálogo no tiene color ni precio: se marcan las alertas por nombre (o tipo) sin esos filtros
function alertasDeCatalogo(f, alertas) {
  const a = { nombre: f.nombre_completo || f.nombre, tipo: f.tipo, rareza: f.rareza, tienda: "Rocket League" };
  return alertas.filter((al) => al.activa && !al.color && al.precio_max == null && (al.nombre || al.tipo) && coincide(al, a)).map((al) => al.id);
}

// ---------- GitHub ----------
const claveGitHub = () => leerLocal("claveGitHub") || "";

function pedirClave(motivo) {
  const actual = claveGitHub();
  const texto = `${motivo ? motivo + "\n\n" : ""}Pega tu clave de GitHub (token "fine-grained" solo para el repo ${nube.estado.nube.repo}, `
    + `con permisos Contents y Actions en "Read and write"). Se guarda solo en este navegador.`
    + (actual ? "\n\nDeja vacío para borrar la clave guardada." : "");
  const nueva = prompt(texto, "");
  if (nueva === null) return actual;
  guardarLocal("claveGitHub", nueva.trim() || null);
  pintarClave();
  return nueva.trim();
}

async function github(ruta, metodo = "GET", cuerpo) {
  let clave = claveGitHub() || pedirClave("Para cambiar alertas o pedir una revisión hace falta tu clave de GitHub.");
  if (!clave) throw new Error("Sin clave de GitHub no se pueden guardar cambios.");
  const r = await fetch(`https://api.github.com/repos/${nube.estado.nube.repo}${ruta}`, {
    method: metodo,
    headers: { Authorization: `Bearer ${clave}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
      ...(cuerpo ? { "Content-Type": "application/json" } : {}) },
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    cache: "no-store",
  });
  if (r.status === 401 || r.status === 403) {
    throw new Error("GitHub rechazó la clave (¿venció o le faltan permisos Contents/Actions?). Usa 🔑 para cambiarla.");
  }
  const datos = r.status === 204 ? {} : await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`GitHub: ${datos.message || r.status}`);
  return datos;
}

const aBase64 = (texto) => btoa(String.fromCharCode(...new TextEncoder().encode(texto)));
const deBase64 = (b64) => new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\s/g, "")), (c) => c.charCodeAt(0)));

async function lanzar(accion) {
  const n = nube.estado.nube;
  await github(`/actions/workflows/${n.workflow}/dispatches`, "POST", { ref: n.rama_codigo, inputs: { accion } });
  guardarLocal("accionPendiente", { accion, desde: new Date().toISOString() });
}

// Cambia alertas.json en la rama de datos, siempre sobre la versión más nueva
async function cambiarAlertas(cambio, mensaje) {
  const n = nube.estado.nube;
  const ruta = `/contents/${n.archivo_alertas}`;
  const actual = await github(`${ruta}?ref=${encodeURIComponent(n.rama_datos)}`);
  const alertas = JSON.parse(deBase64(actual.content || "") || "[]");
  const resultado = cambio(alertas);
  const texto = "[\n" + alertas.map((a) => JSON.stringify(a)).join(",\n") + "\n]\n";
  await github(ruta, "PUT", { message: mensaje, content: aBase64(texto), sha: actual.sha, branch: n.rama_datos });
  guardarLocal("alertasPendientes", { alertas, desde: new Date().toISOString() });
  await lanzar("exportar").catch(() => { /* la próxima revisión horaria también la publica */ });
  return resultado;
}

// ---------- alertas: lo publicado + cambios recién hechos que GitHub todavía no publicó ----------
const camposAlerta = (al) => JSON.stringify(["id", "nombre", "color", "tipo", "rareza", "tienda", "precio_max", "activa", "exacto"].map((k) => al[k] ?? null));

function articuloAlerta(al, enTienda, historial) {
  const categoria = categoriaDe(al.tipo);
  const enVenta = [...enTienda, ...historial].find((a) => a.imagen && coincide(al, a));
  const nombre = normalizar(al.nombre).trim();
  const vacio = { imagen: "", mezcla: "", titulo: "", rareza: "", rareza_color: "", catalogo_id: "" };
  if (!nombre) return { ...vacio, titulo: categoria || "Cualquier artículo", imagen: enVenta ? enVenta.imagen : "", mezcla: enVenta ? enVenta.mezcla || "" : "" };
  let filas = (nube.catalogo ? nube.catalogo.articulos : []).filter((f) => f._norm === nombre);
  if (!filas.length && !al.exacto && nube.catalogo) filas = nube.catalogo.articulos.filter((f) => f._norm.includes(nombre)).sort((a, b) => a._norm.length - b._norm.length).slice(0, 50);
  if (categoria) filas = filas.filter((f) => f.categoria === categoria);
  else filas = [...filas].sort((a, b) => (a.tipo !== "Body") - (b.tipo !== "Body"));
  const cat = filas[0];
  const imagen = (enVenta && enVenta.imagen) || (cat && cat.imagen) || "";
  let mezcla = (enVenta && enVenta.mezcla) || "";
  if (!mezcla && imagen.includes("cdn.source.gs/rocket-league/img/")) mezcla = "screen";
  const fuente = cat || enVenta || {};
  return { imagen, mezcla, titulo: (cat && (cat.nombre_completo || cat.nombre)) || (enVenta && enVenta.nombre) || al.nombre,
    rareza: fuente.rareza || "", rareza_color: fuente.rareza_color || "", catalogo_id: cat ? cat.id : "" };
}

function aplicarPendientes(datos) {
  const pend = leerLocal("alertasPendientes");
  if (!pend) return;
  const publicadas = new Map(datos.alertas.map((al) => [al.id, al]));
  const iguales = pend.alertas.length === datos.alertas.length && pend.alertas.every((al) => publicadas.has(al.id) && camposAlerta(publicadas.get(al.id)) === camposAlerta(al));
  const viejo = Date.now() - new Date(pend.desde) > MINUTOS_ESPERA * 60000;
  if (iguales || viejo) return guardarLocal("alertasPendientes", null);
  const historial = nube.historialTienda || [];
  datos.alertas = pend.alertas.map((al) => {
    const pub = publicadas.get(al.id);
    const mismoArticulo = pub && pub.nombre === al.nombre && pub.tipo === al.tipo && pub.exacto === al.exacto;
    const articulo = mismoArticulo ? pub.articulo : articuloAlerta(al, datos.articulos, historial);
    return { ...al, articulo, imagen: articulo.imagen, mezcla: articulo.mezcla };
  });
  datos.pendiente = true;
}

function recalcularAlertas(datos) {
  for (const a of datos.articulos) a.alertas = datos.alertas.filter((al) => al.activa && coincide(al, a)).map((al) => al.id);
  for (const al of datos.alertas) {
    al.coincidencias = datos.articulos.filter((a) => a.alertas.includes(al.id)).length;
    al.descripcion = describirAlerta(al);
  }
}

// ---------- lectura de los JSON publicados ----------
async function leerDatos(nombre) {
  const r = await fetch(`datos/${nombre}?v=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`No pude leer ${nombre} (${r.status})`);
  return r.json();
}

async function cargarCatalogoNube() {
  if (!nube.catalogo) {
    nube.catalogo = await leerDatos("catalogo.json");
    nube.catalogo.conFicha = new Set(nube.catalogo.fichas || []);
    for (const f of nube.catalogo.articulos) {
      f.url = f.url || URL_CATALOGO + f.id;
      f._norm = normalizar(f.nombre_completo || f.nombre);
      f._variante = normalizar(f.variante);
    }
  }
  return nube.catalogo;
}

async function estadoNube() {
  const datos = await leerDatos("estado.json");
  nube.sinonimos = datos.sinonimos || {};
  nube.estado = datos;
  if (leerLocal("alertasPendientes")) {
    await cargarCatalogoNube().catch(() => null);
    if (!nube.historialTienda) nube.historialTienda = await leerDatos("historial.json").then((h) => h.filter((a) => !a.en_tienda && a.imagen)).catch(() => []);
  }
  aplicarPendientes(datos);
  recalcularAlertas(datos);
  // Revisión pedida a GitHub que todavía no terminó
  const accion = leerLocal("accionPendiente");
  if (accion) {
    const listo = datos.nube.generado > accion.desde;
    const viejo = Date.now() - new Date(accion.desde) > MINUTOS_ESPERA * 60000;
    if (listo || viejo) guardarLocal("accionPendiente", null);
    else {
      datos.revision.revisando = true;
      datos.revision.accion = accion.accion;
    }
  }
  pintarClave();
  return datos;
}

// ---------- catálogo (los filtros que en la PC hace el servidor) ----------
function ordenPase(detalle) {
  const m = /(\d+)/.exec(detalle || "");
  return [detalle.startsWith("Rocket Pass") ? 0 : 1, m ? +m[1] : 0];
}

function ordenarCatalogo(filas, orden) {
  if (!orden) return filas;
  const [campo, sentido] = orden.split("-");
  const nombre = (f) => f._norm;
  const porNombre = (a, b) => (nombre(a) < nombre(b) ? -1 : nombre(a) > nombre(b) ? 1 : 0);
  filas = [...filas].sort(porNombre);
  if (campo === "nombre") return sentido === "desc" ? filas.reverse() : filas;
  if (campo === "rareza") {
    const puesto = (f) => {
      const r = f.rareza || "";
      if (ESCALA_RAREZAS.includes(r)) { const n = ESCALA_RAREZAS.indexOf(r); return [0, sentido === "desc" ? -n : n]; }
      if (RAREZAS_ESPECIALES.includes(r)) return [1, RAREZAS_ESPECIALES.indexOf(r)];
      return [2, 0];
    };
    return filas.sort((a, b) => { const x = puesto(a), y = puesto(b); return x[0] - y[0] || x[1] - y[1]; });
  }
  const con = filas.filter((f) => f.ultimo_precio != null), sin = filas.filter((f) => f.ultimo_precio == null);
  con.sort((a, b) => (sentido === "desc" ? b.ultimo_precio - a.ultimo_precio : a.ultimo_precio - b.ultimo_precio));
  return con.concat(sin);
}

async function catalogoNube(p) {
  const c = await cargarCatalogoNube();
  const alertas = (estado.datos || nube.estado).alertas;
  const q = normalizar(p.get("q")).trim();
  const tipo = p.get("tipo"), rareza = p.get("rareza"), vista = p.get("vista"), origen = p.get("origen"), pase = p.get("pase");
  let filas = c.articulos;
  for (const palabra of q.split(/\s+/).filter(Boolean)) filas = filas.filter((f) => f._norm.includes(palabra) || f._variante.includes(palabra));
  if (tipo) filas = filas.filter((f) => f.tipo === tipo);
  if (rareza) filas = filas.filter((f) => f.rareza === rareza);
  if (q) filas = [...filas].sort((a, b) => (b._norm === q) - (a._norm === q));
  if (origen === "desconocido") filas = filas.filter((f) => !f.origenes.length);
  else if (origen) filas = filas.filter((f) => f.origenes.some((o) => o.origen === origen));
  if (pase) filas = filas.filter((f) => f.origenes.some((o) => o.origen === "Rocket Pass" && o.detalle === pase));
  if (vista === "nunca") filas = filas.filter((f) => !f.ultima_vez);
  else if (vista === "visto") filas = filas.filter((f) => f.ultima_vez);
  else if (vista === "hoy") filas = filas.filter((f) => f.en_tienda);
  else if (vista === "alerta") filas = filas.filter((f) => alertasDeCatalogo(f, alertas).length);
  filas = ordenarCatalogo(filas, p.get("orden") || "");
  const total = filas.length;
  let pagina = Math.max(0, parseInt(p.get("pagina"), 10) || 0);
  const cantidad = parseInt(p.get("cantidad"), 10) || 0;
  if (cantidad) {
    filas = filas.slice(0, cantidad);
    pagina = Math.max(0, Math.floor((filas.length - 1) / POR_PAGINA));
  } else filas = filas.slice(pagina * POR_PAGINA, (pagina + 1) * POR_PAGINA);
  return {
    ...c, articulos: filas.map((f) => ({ ...f, alertas: alertasDeCatalogo(f, alertas) })),
    total, pagina, por_pagina: POR_PAGINA, actualizando: false,
  };
}

const claveFicha = (id) => id.toLowerCase().replace(/[^a-z0-9-]+/g, "_").replace(/^_+|_+$/g, "");

async function fichaNube(id) {
  const c = await cargarCatalogoNube();
  if (c.conFicha.has(claveFicha(id))) {
    const f = await leerDatos(`fichas/${claveFicha(id)}.json`);
    f.url = f.url || URL_CATALOGO + f.id;
    return f;
  }
  // Sin ficha completa: lo que dice el catálogo (el historial detallado se arma para artículos con alerta)
  const f = c.articulos.find((x) => x.id === id);
  if (!f) throw new Error("Ese artículo no está en el catálogo");
  return {
    ...f, historial: [], propio: [],
    historial_nota: "El historial detallado se arma para los artículos con alerta. Crea una y aparecerá tras la próxima revisión.",
    url_itemshop: f.slug_itemshop ? `https://itemshop.gg/rocket-league/catalogue/${f.slug_itemshop}` : "",
    url_rlshopnotify: f.producto_id ? `https://rlshopnotify.com/items/${f.producto_id}` : "",
  };
}

// ---------- rutas ----------
async function api(ruta, metodo = "GET", cuerpo) {
  const [camino, consulta] = ruta.split("?");
  const p = new URLSearchParams(consulta || "");
  if (metodo === "GET") {
    if (camino === "/api/estado") return estadoNube();
    if (camino === "/api/historial") return leerDatos("historial.json");
    if (camino === "/api/catalogo") return catalogoNube(p);
    if (camino === "/api/catalogo/ficha") return fichaNube(p.get("id") || "");
  }
  if (camino === "/api/alertas" && metodo === "POST") {
    const al = limpiarAlerta(cuerpo);
    return cambiarAlertas((lista) => {
      const id = Math.max(Date.now(), ...lista.map((a) => a.id + 1));
      lista.push({ id, ...al, creada: new Date().toISOString().slice(0, 19) + "Z" });
      return { id };
    }, `Alerta nueva: ${describirAlerta(al)}`);
  }
  const m = /^\/api\/alertas\/(\d+)$/.exec(camino);
  if (m && metodo === "PUT") {
    const al = limpiarAlerta(cuerpo), id = +m[1];
    return cambiarAlertas((lista) => {
      const i = lista.findIndex((a) => a.id === id);
      if (i < 0) throw new Error("Esa alerta ya no existe");
      lista[i] = { ...lista[i], ...al };
      return { ok: true };
    }, `Alerta editada: ${describirAlerta(al)}`);
  }
  if (m && metodo === "DELETE") {
    const id = +m[1];
    return cambiarAlertas((lista) => {
      const i = lista.findIndex((a) => a.id === id);
      if (i >= 0) lista.splice(i, 1);
      return { ok: true };
    }, `Alerta borrada (${id})`);
  }
  if (camino === "/api/revisar") return lanzar("revisar").then(() => ({ ok: true }));
  if (camino === "/api/catalogo/actualizar") return lanzar("catalogo").then(() => ({ ok: true }));
  if (camino === "/api/probar-aviso") return lanzar("probar").then(() => ({ discord: "pedido a GitHub, llega en 1 o 2 minutos" }));
  throw new Error("No existe");
}

// ---------- botón de la clave ----------
function pintarClave() {
  const b = document.querySelector("#btn-clave");
  if (!b) return;
  const hay = !!claveGitHub();
  b.textContent = hay ? "🔑 Conectado" : "🔑 Conectar GitHub";
  b.title = hay ? "Clave de GitHub guardada en este navegador. Clic para cambiarla o borrarla." : "Hace falta para cambiar alertas o pedir una revisión";
}

document.addEventListener("DOMContentLoaded", () => {
  const b = document.querySelector("#btn-clave");
  if (b) b.addEventListener("click", () => nube.estado && pedirClave(""));
  pintarClave();
});
