"use strict";

const estado = { datos: null, historial: null, vista: "Rocket League", editando: null, catalogo: null };
const $ = (s) => document.querySelector(s);

// ---------- utilidades ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const colorSeguro = (c) => (/^#[0-9a-f]{3,8}$/i.test(c || "") ? c : "");
const urlSegura = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
const norm = (s) => String(s ?? "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

function restante(iso) {
  if (!iso) return { texto: "", pronto: false };
  const ms = new Date(iso) - Date.now();
  if (isNaN(ms)) return { texto: "", pronto: false };
  if (ms <= 0) return { texto: "Terminó", pronto: true };
  const min = Math.floor(ms / 60000), d = Math.floor(min / 1440), h = Math.floor((min % 1440) / 60), m = min % 60;
  const texto = d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
  return { texto, pronto: ms < 6 * 3600 * 1000 };
}

function fechaCorta(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("es", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function haceCuanto(iso) {
  if (!iso) return "nunca";
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return "recién";
  if (min < 60) return `hace ${min} min`;
  return `hace ${Math.floor(min / 60)} h ${min % 60} min`;
}

function mostrarAviso(texto, ms = 4500) {
  const a = $("#aviso");
  a.textContent = texto;
  a.hidden = false;
  clearTimeout(mostrarAviso.t);
  mostrarAviso.t = setTimeout(() => (a.hidden = true), ms);
}

async function api(ruta, metodo = "GET", cuerpo) {
  const opciones = { method: metodo, headers: {} };
  if (metodo !== "GET") {
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(cuerpo || {});
  }
  const r = await fetch(ruta, opciones);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}

// ---------- carga ----------
async function cargar() {
  try {
    estado.datos = await api("/api/estado");
  } catch (e) {
    $("#estado-revision").textContent = "No pude conectar con el notificador. ¿Está abierta su ventana?";
    return;
  }
  pintarCabecera();
  llenarFiltros();
  pintar();
  clearTimeout(cargar.t);
  cargar.t = setTimeout(cargar, estado.datos.revision.revisando ? 2000 : 60000);
}

function llenarCategorias() {
  const sel = $("#form-alerta").tipo;
  if (sel.dataset.listo || !estado.datos.categorias) return;
  for (const c of estado.datos.categorias) sel.add(new Option(c, c));
  sel.dataset.listo = "1";
}

function pintarCabecera() {
  llenarCategorias();
  const r = estado.datos.revision;
  const partes = [];
  if (r.revisando) partes.push("Revisando la tienda…");
  else partes.push(`Última revisión: ${haceCuanto(r.ultima)}${r.ultima ? ` (${fechaCorta(r.ultima)})` : ""}`);
  const proximas = [r.proxima_periodica, r.proxima_fija].filter(Boolean).sort();
  if (proximas.length && !r.revisando) partes.push(`próxima: ${fechaCorta(proximas[0])}`);
  partes.push(`cada ${r.minutos} min + fija ${r.hora_fija} (GMT${r.zona >= 0 ? "+" : ""}${r.zona})`);
  let texto = partes.join(" · ");
  if (r.errores && r.errores.length) texto += ` · ⚠ ${r.errores.join("; ")}`;
  $("#estado-revision").textContent = texto;
  $("#btn-revisar").disabled = r.revisando;
  $("#btn-revisar").textContent = r.revisando ? "Revisando…" : "Revisar ahora";

  const c = estado.datos.canales;
  const nombres = { windows: "Windows", discord: "Discord", correo: "Correo" };
  $("#canales").innerHTML = Object.entries(nombres)
    .map(([k, n]) => `<span class="canal ${c[k] ? "on" : ""}" title="${c[k] ? "Activo" : "Sin configurar (config.json)"}">${c[k] ? "✓" : "✗"} ${n}</span>`)
    .join("");

  const arts = estado.datos.articulos;
  $("#cuenta-rl").textContent = arts.filter((a) => a.tienda === "Rocket League").length;
  $("#cuenta-fn").textContent = arts.filter((a) => a.tienda === "Fortnite").length;
  $("#cuenta-alertas").textContent = estado.datos.alertas.length;
}

function articulosVista() {
  if (estado.vista === "historial") return estado.historial || [];
  return estado.datos.articulos.filter((a) => a.tienda === estado.vista);
}

function llenarFiltros() {
  const lista = articulosVista();
  for (const [id, campo] of [["#f-tipo", "tipo"], ["#f-rareza", "rareza"], ["#f-color", "color"]]) {
    const sel = $(id);
    const actual = sel.value;
    const valores = [...new Set(lista.map((a) => a[campo]).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    sel.length = 1;
    for (const v of valores) sel.add(new Option(v, v));
    sel.value = valores.includes(actual) ? actual : "";
    sel.hidden = valores.length === 0;
  }
}

function filtrar(lista) {
  const q = norm($("#f-buscar").value.trim());
  const tipo = $("#f-tipo").value, rareza = $("#f-rareza").value, color = $("#f-color").value;
  const soloAlerta = $("#f-alerta").checked;
  const alertas = new Set();
  if (soloAlerta && estado.vista === "historial") {
    // en el historial las coincidencias se calculan aquí (el servidor solo las marca en lo que está en tienda)
    for (const a of estado.datos.articulos) if (a.alertas.length) alertas.add(a.id);
  }
  return lista.filter((a) => {
    if (q && !norm(`${a.nombre} ${a.color} ${a.tipo} ${a.rareza} ${a.seccion}`).includes(q)) return false;
    if (tipo && a.tipo !== tipo) return false;
    if (rareza && a.rareza !== rareza) return false;
    if (color && a.color !== color) return false;
    if (soloAlerta && !(a.alertas ? a.alertas.length : alertas.has(a.id))) return false;
    return true;
  });
}

function ordenar(lista) {
  const orden = $("#f-orden").value;
  const precio = (a) => (a.precio_num ?? -1);
  const copia = [...lista];
  if (orden === "precio-desc") copia.sort((a, b) => precio(b) - precio(a));
  else if (orden === "precio-asc") copia.sort((a, b) => precio(a) - precio(b));
  else if (orden === "termina") copia.sort((a, b) => (a.hasta || "9").localeCompare(b.hasta || "9"));
  else if (orden === "nombre") copia.sort((a, b) => a.nombre.localeCompare(b.nombre));
  return copia;
}

// ---------- vistas ----------
function pintar() {
  const esTienda = estado.vista === "Rocket League" || estado.vista === "Fortnite";
  $("#vista-tienda").hidden = !esTienda;
  $("#vista-historial").hidden = estado.vista !== "historial";
  $("#vista-alertas").hidden = estado.vista !== "alertas";
  $("#vista-catalogo").hidden = estado.vista !== "catalogo";
  $("#filtros").hidden = estado.vista === "alertas" || estado.vista === "catalogo";
  if (esTienda) pintarTienda();
  else if (estado.vista === "historial") pintarHistorial();
  else if (estado.vista === "catalogo") { if (!estado.catalogo) cargarCatalogo(); }
  else pintarAlertas();
}

function tarjeta(a) {
  const rareza = colorSeguro(a.rareza_color) || "#8a94a8";
  const img = urlSegura(a.imagen);
  const r = restante(a.hasta);
  const conAlerta = a.alertas && a.alertas.length;
  const nombresAlertas = conAlerta
    ? estado.datos.alertas.filter((al) => a.alertas.includes(al.id)).map((al) => al.descripcion).join("\n")
    : "";
  const vbucks = a.moneda === "V-Bucks";
  return `
  <article class="tarjeta ${conAlerta ? "con-alerta" : ""}" style="--rareza:${rareza}">
    <div class="tarjeta-img">
      ${img ? `<img src="${esc(img)}" alt="${esc(a.nombre)}" loading="lazy" referrerpolicy="no-referrer" class="${a.mezcla === "screen" ? "mezcla-screen" : ""}">` : `<span class="sin-imagen">Sin imagen</span>`}
      <div class="etiquetas">
        <span>${a.rareza ? `<span class="etiqueta rareza">${esc(a.rareza)}</span>` : ""}</span>
        <span>
          ${a.nuevo ? `<span class="etiqueta nuevo">Nuevo</span>` : ""}
          ${conAlerta ? `<span class="etiqueta marca-alerta" title="${esc(nombresAlertas)}">★ Alerta</span>` : ""}
        </span>
      </div>
    </div>
    <div class="franja"></div>
    <div class="cuerpo">
      <h3>${esc(a.nombre)}</h3>
      ${a.color ? `<span class="pintura"><span class="punto" style="background:${colorSeguro(a.color_hex) || "transparent"}"></span>${esc(a.color)}</span>` : ""}
      <span class="tipo">${esc(a.tipo)}</span>
      <div class="pie">
        <span class="precio"><i class="moneda ${vbucks ? "vbucks" : ""}">${vbucks ? "V" : "C"}</i>${esc(a.precio_num != null ? a.precio_num.toLocaleString("es") : a.precio)}</span>
        <span class="reloj ${r.pronto ? "pronto" : ""}" data-hasta="${esc(a.hasta || "")}" title="${a.hasta ? "Hasta " + esc(fechaCorta(a.hasta)) : ""}">${r.texto ? "⏱ " + esc(r.texto) : ""}</span>
      </div>
    </div>
    <div class="botones-tarjeta">
      ${urlSegura(a.url) ? `<a class="btn btn-chico" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">Ver ↗</a>` : ""}
      <button class="btn btn-chico" data-crear-alerta="${esc(a.id)}">+ Alerta</button>
    </div>
  </article>`;
}

function pintarTienda() {
  const lista = ordenar(filtrar(articulosVista()));
  const cont = $("#vista-tienda");
  if (!lista.length) {
    cont.innerHTML = `<div class="vacio">${estado.datos.revision.ultima ? "No hay artículos con estos filtros." : "Esperando la primera revisión…"}</div>`;
    return;
  }
  if ($("#f-orden").value !== "seccion") {
    cont.innerHTML = `<div class="rejilla">${lista.map(tarjeta).join("")}</div>`;
    return;
  }
  const grupos = new Map();
  for (const a of lista) {
    if (!grupos.has(a.seccion)) grupos.set(a.seccion, []);
    grupos.get(a.seccion).push(a);
  }
  cont.innerHTML = [...grupos].map(([seccion, arts]) => {
    const fin = arts.map((a) => a.hasta).filter(Boolean).sort()[0];
    const r = restante(fin);
    return `<section class="seccion">
      <div class="seccion-cabecera"><h2>${esc(seccion)}</h2>
        <span class="reloj ${r.pronto ? "pronto" : ""}" data-hasta="${esc(fin || "")}">${r.texto ? "⏱ " + esc(r.texto) : ""}</span>
        <span class="sutil">${arts.length} artículo${arts.length === 1 ? "" : "s"}</span></div>
      <div class="rejilla">${arts.map(tarjeta).join("")}</div>
    </section>`;
  }).join("");
}

async function pintarHistorial() {
  if (!estado.historial) {
    $("#historial-cuerpo").innerHTML = `<tr><td colspan="10" class="vacio">Cargando…</td></tr>`;
    try {
      estado.historial = await api("/api/historial");
    } catch (e) {
      $("#historial-cuerpo").innerHTML = `<tr><td colspan="10" class="vacio">${esc(e.message)}</td></tr>`;
      return;
    }
    llenarFiltros();
  }
  let lista = filtrar(estado.historial);
  if ($("#f-orden").value !== "seccion") lista = ordenar(lista);
  $("#historial-cuerpo").innerHTML = lista.slice(0, 1000).map((a) => `
    <tr class="${a.en_tienda ? "" : "fuera"}">
      <td>${urlSegura(a.imagen) ? `<img src="${esc(a.imagen)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}</td>
      <td><b>${esc(a.nombre)}</b>${a.color ? ` <span class="sutil">· ${esc(a.color)}</span>` : ""}${a.en_tienda ? ` <span class="etiqueta nuevo">En tienda</span>` : ""}</td>
      <td>${esc(a.tipo)}</td>
      <td><span class="punto-rareza" style="background:${colorSeguro(a.rareza_color) || "transparent"}"></span>${esc(a.rareza)}</td>
      <td>${a.tienda === "Fortnite" ? "RL en Fortnite" : "Rocket League"}</td>
      <td>${esc(a.precio)}</td>
      <td>${esc(fechaCorta(a.primera_vez))}</td>
      <td>${esc(fechaCorta(a.ultima_vez))}</td>
      <td>${a.apariciones}</td>
      <td><button class="btn btn-chico" data-crear-alerta="${esc(a.id)}">+ Alerta</button></td>
    </tr>`).join("") || `<tr><td colspan="10" class="vacio">Nada con estos filtros.</td></tr>`;
}

function pintarAlertas() {
  const alertas = estado.datos.alertas;
  $("#lista-alertas").innerHTML = alertas.length ? alertas.map((al) => `
    <li class="${al.activa ? "" : "inactiva"}">
      <input type="checkbox" title="Activa" data-activar="${al.id}" ${al.activa ? "checked" : ""}>
      <div class="desc">${esc(al.descripcion)}<br>
        <span class="coinc ${al.coincidencias ? "si" : ""}">${al.coincidencias ? `★ ${al.coincidencias} en la tienda ahora` : "Nada en la tienda ahora"}</span></div>
      <button class="btn btn-chico" data-editar="${al.id}">Editar</button>
      <button class="btn btn-chico btn-peligro" data-borrar="${al.id}">Borrar</button>
    </li>`).join("") : `<li class="sutil">Todavía no tienes alertas.</li>`;
}

// ---------- formulario de alertas ----------
function llenarFormulario(al) {
  const f = $("#form-alerta");
  f.id.value = al && al.id ? al.id : "";
  const tipo = (al && al.tipo) || "";
  if (tipo && ![...f.tipo.options].some((o) => o.value === tipo)) f.tipo.add(new Option(tipo, tipo)); // alerta vieja
  for (const c of ["nombre", "color", "tipo", "rareza", "tienda"]) f[c].value = (al && al[c]) || "";
  f.precio_max.value = al && al.precio_max != null ? al.precio_max : "";
  f.activa.checked = !al || al.activa === undefined ? true : !!al.activa;
  f.exacto.checked = !!(al && al.exacto);
  $("#form-titulo").textContent = al && al.id ? "Editar alerta" : "Nueva alerta";
  $("#btn-cancelar").hidden = !(al && (al.id || al.nombre));
  $("#form-error").hidden = true;
}

$("#form-alerta").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const cuerpo = {
    nombre: f.nombre.value, color: f.color.value, tipo: f.tipo.value, rareza: f.rareza.value,
    tienda: f.tienda.value, precio_max: f.precio_max.value, activa: f.activa.checked, exacto: f.exacto.checked,
  };
  try {
    if (f.id.value) await api(`/api/alertas/${f.id.value}`, "PUT", cuerpo);
    else await api("/api/alertas", "POST", cuerpo);
    mostrarAviso(f.id.value ? "Alerta actualizada" : "Alerta creada. Se avisará en la próxima revisión.");
    llenarFormulario(null);
    await cargar();
  } catch (e) {
    $("#form-error").textContent = e.message;
    $("#form-error").hidden = false;
  }
});

$("#btn-cancelar").addEventListener("click", () => llenarFormulario(null));

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("[data-editar],[data-borrar],[data-crear-alerta],[data-activar]");
  if (!t) return;
  if (t.dataset.editar) {
    llenarFormulario(estado.datos.alertas.find((a) => a.id == t.dataset.editar));
    $("#form-alerta").scrollIntoView({ behavior: "smooth" });
  } else if (t.dataset.borrar) {
    const al = estado.datos.alertas.find((a) => a.id == t.dataset.borrar);
    if (!confirm(`¿Borrar la alerta "${al.descripcion}"?`)) return;
    await api(`/api/alertas/${al.id}`, "DELETE").catch((e) => mostrarAviso(e.message));
    await cargar();
  } else if (t.dataset.activar) {
    const al = estado.datos.alertas.find((a) => a.id == t.dataset.activar);
    await api(`/api/alertas/${al.id}`, "PUT", { ...al, activa: t.checked }).catch((e) => mostrarAviso(e.message));
    await cargar();
  } else if (t.dataset.crearAlerta) {
    const a = estado.datos.articulos.find((x) => x.id === t.dataset.crearAlerta)
      || (estado.historial || []).find((x) => x.id === t.dataset.crearAlerta)
      || (estado.catalogo ? estado.catalogo.articulos : []).find((x) => x.id === t.dataset.crearAlerta);
    if (!a) return;
    cambiarVista("alertas");
    // Alerta exacta por nombre; el color queda para completar si se quiere uno concreto
    llenarFormulario({ nombre: a.nombre_completo || a.nombre, color: a.color || "", tienda: a.tienda || "Rocket League",
      tipo: a.categoria || "", exacto: 1 });
    if (!a.color) $("#form-alerta").color.focus();
  }
});

// ---------- botones y pestañas ----------
function cambiarVista(vista) {
  estado.vista = vista;
  document.querySelectorAll(".pestana").forEach((p) => p.classList.toggle("activa", p.dataset.vista === vista));
  if (vista === "historial") estado.historial = null; // se vuelve a pedir para tenerlo al día
  if (vista === "catalogo") estado.catalogo = null; // se vuelve a pedir (historial y alertas al día)
  if (vista !== "alertas" && vista !== "catalogo") llenarFiltros();
  pintar();
}

document.querySelectorAll(".pestana").forEach((p) => p.addEventListener("click", () => cambiarVista(p.dataset.vista)));
for (const id of ["#f-buscar", "#f-tipo", "#f-rareza", "#f-color", "#f-orden", "#f-alerta"]) {
  $(id).addEventListener("input", pintar);
}

$("#btn-revisar").addEventListener("click", async () => {
  $("#btn-revisar").disabled = true;
  try {
    await api("/api/revisar", "POST");
    mostrarAviso("Revisando la tienda…");
    setTimeout(cargar, 1500);
  } catch (e) {
    mostrarAviso(e.message);
    $("#btn-revisar").disabled = false;
  }
});

$("#btn-probar").addEventListener("click", async () => {
  const b = $("#btn-probar");
  b.disabled = true;
  try {
    const r = await api("/api/probar-aviso", "POST");
    mostrarAviso(`Aviso de prueba:\nWindows: ${r.windows}\nDiscord: ${r.discord}\nCorreo: ${r.correo}`, 9000);
  } catch (e) {
    mostrarAviso(e.message);
  } finally {
    b.disabled = false;
  }
});

// ---------- catálogo ----------
async function cargarCatalogo(mas = false) {
  const pagina = mas && estado.catalogo ? estado.catalogo.pagina + 1 : 0;
  const params = new URLSearchParams({
    q: $("#c-buscar").value.trim(), tipo: $("#c-tipo").value, rareza: $("#c-rareza").value,
    vista: $("#c-vista").value, origen: $("#c-origen").value, pase: $("#c-pase").value, pagina,
  });
  const pedido = (cargarCatalogo.n = (cargarCatalogo.n || 0) + 1);
  let datos;
  try {
    datos = await api(`/api/catalogo?${params}`);
  } catch (e) {
    $("#c-estado").textContent = e.message;
    return;
  }
  if (pedido !== cargarCatalogo.n) return; // llegó una búsqueda más nueva
  if (mas && estado.catalogo) datos.articulos = estado.catalogo.articulos.concat(datos.articulos);
  estado.catalogo = datos;
  for (const [id, valores, fijas] of [["#c-tipo", datos.tipos, 1], ["#c-rareza", datos.rarezas, 1],
    ["#c-origen", datos.origenes, 2], ["#c-pase", datos.pases, 1]]) {
    const sel = $(id), actual = sel.value;
    sel.length = fijas;
    for (const v of valores) sel.add(new Option(v, v));
    sel.value = actual;
  }
  pintarCatalogo();
  clearTimeout(cargarCatalogo.t);
  if (datos.actualizando) cargarCatalogo.t = setTimeout(() => estado.vista === "catalogo" && cargarCatalogo(), 3000);
}

function tarjetaCatalogo(a) {
  const rareza = colorSeguro(a.rareza_color) || "#8a94a8";
  const img = urlSegura(a.imagen);
  const conAlerta = a.alertas && a.alertas.length;
  const visto = a.en_tienda ? `<span class="etiqueta hoy">En tienda hoy</span>`
    : a.ultima_vez ? "" : `<span class="etiqueta nunca">Nunca visto</span>`;
  return `
  <article class="tarjeta ${conAlerta ? "con-alerta" : ""}" style="--rareza:${rareza}">
    <div class="tarjeta-img" data-ficha="${esc(a.id)}" title="Ver ficha">
      ${img ? `<img src="${esc(img)}" alt="${esc(a.nombre)}" loading="lazy" referrerpolicy="no-referrer">` : `<span class="sin-imagen">Sin imagen</span>`}
      <div class="etiquetas">
        <span>${a.rareza ? `<span class="etiqueta rareza">${esc(a.rareza)}</span>` : ""}</span>
        <span>${visto}${conAlerta ? ` <span class="etiqueta marca-alerta">★ Alerta</span>` : ""}</span>
      </div>
    </div>
    <div class="franja"></div>
    <div class="cuerpo">
      <h3 data-ficha="${esc(a.id)}">${esc(a.nombre_completo || a.nombre)}</h3>
      <span class="tipo">${esc(a.tipo)}${a.calidad && a.calidad !== a.rareza ? ` · ${esc(a.calidad)}` : ""}</span>
      ${textoOrigen(a)}
      <span class="visto">${a.ultima_vez
        ? `Última vez en tienda: ${esc(fechaDia(a.ultima_vez))}${a.ultimo_precio != null ? ` · ${esc(a.ultimo_precio.toLocaleString("es"))} créditos` : ""} · ${a.veces} ${a.veces === 1 ? "vez" : "veces"}`
        : "Sin registro en la tienda"}</span>
    </div>
    <div class="botones-tarjeta">
      ${urlSegura(a.url) ? `<a class="btn btn-chico" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">Ver ↗</a>` : ""}
      <button class="btn btn-chico" data-crear-alerta="${esc(a.id)}">+ Alerta</button>
    </div>
  </article>`;
}

function pintarCatalogo() {
  const c = estado.catalogo;
  let texto;
  if (!c.total_catalogo) texto = c.actualizando ? `Descargando el catálogo (${c.progreso})…` : "El catálogo todavía no se descargó.";
  else {
    texto = `${c.total.toLocaleString("es")} de ${c.total_catalogo.toLocaleString("es")} artículos · catálogo del ${fechaCorta(c.actualizado)}`
      + (c.historial_actualizado ? ` · tienda (itemshop.gg, desde sep. 2026) del ${fechaCorta(c.historial_actualizado)}` : "")
      + " · origen: wiki de Rocket League";
    if (c.actualizando) texto += ` · actualizando (${c.progreso})…`;
  }
  if (c.error) texto += ` · ⚠ ${c.error}`;
  $("#c-estado").textContent = texto;
  $("#btn-catalogo").disabled = c.actualizando;
  $("#c-rejilla").innerHTML = c.articulos.length ? c.articulos.map(tarjetaCatalogo).join("")
    : `<div class="vacio">${c.total_catalogo ? "Nada con estos filtros." : ""}</div>`;
  $("#c-mas").hidden = c.articulos.length >= c.total;
}

$("#c-buscar").addEventListener("input", () => {
  clearTimeout(cargarCatalogo.espera);
  cargarCatalogo.espera = setTimeout(() => cargarCatalogo(), 250);
});
for (const id of ["#c-tipo", "#c-rareza", "#c-vista", "#c-origen", "#c-pase"]) $(id).addEventListener("input", () => cargarCatalogo());

// ---------- origen y ficha ----------
function fechaDia(iso) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return isNaN(d) ? iso : d.toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" });
}

function describirOrigen(o) {
  return [o.origen, o.detalle, o.nivel ? `nivel ${o.nivel}` : ""].filter(Boolean).join(" · ");
}

function textoOrigen(a) {
  if (!a.origenes || !a.origenes.length) return `<span class="origen desconocido">Origen: desconocido</span>`;
  const extra = a.origenes.length > 1 ? ` (+${a.origenes.length - 1})` : "";
  return `<span class="origen" title="${esc(a.origenes.map(describirOrigen).join("\n"))}">${esc(describirOrigen(a.origenes[0]))}${extra}</span>`;
}

async function abrirFicha(id) {
  const fondo = $("#ficha-fondo"), caja = $("#ficha");
  caja.innerHTML = `<div class="vacio">Cargando ficha…</div>`;
  fondo.hidden = false;
  let a;
  try {
    a = await api(`/api/catalogo/ficha?${new URLSearchParams({ id })}`);
  } catch (e) {
    caja.innerHTML = `<div class="vacio">${esc(e.message)}</div>`;
    return;
  }
  estado.fichaActual = a;
  const rareza = colorSeguro(a.rareza_color) || "#8a94a8";
  const img = urlSegura(a.imagen);
  const dato = (t, v) => (v || v === 0 ? `<div class="dato"><dt>${esc(t)}</dt><dd>${esc(v)}</dd></div>` : "");
  const historial = a.historial.length ? `
      <div class="tabla-envoltura"><table class="tabla">
        <thead><tr><th>Llegó</th><th>Se fue</th><th>Duración</th><th>Precio</th><th>Sección</th></tr></thead>
        <tbody>${a.historial.map((h) => `<tr><td>${esc(fechaDia(h.llegada))}</td><td>${esc(fechaDia(h.salida) || h.salida)}</td>
          <td>${esc(h.duracion)}</td><td>${esc(h.precio)}</td><td>${esc(h.seccion)}</td></tr>`).join("")}</tbody>
      </table></div>` : `<p class="sutil">${a.slug_itemshop ? "Sin apariciones registradas." : "itemshop.gg no lo registró en la tienda (sus datos empiezan en septiembre de 2026)."}</p>`;
  const propio = a.propio.length ? `
    <section><h3>Visto por este notificador</h3>
      <div class="tabla-envoltura"><table class="tabla">
        <thead><tr><th>Color</th><th>Precio</th><th>Sección</th><th>Primera vez</th><th>Última vez</th><th>Veces</th></tr></thead>
        <tbody>${a.propio.map((r) => `<tr><td>${esc(r.color || "—")}</td><td>${esc(r.precio)}</td><td>${esc(r.seccion)}</td>
          <td>${esc(fechaCorta(r.primera_vez))}</td><td>${esc(fechaCorta(r.ultima_vez))}${r.en_tienda ? " (hoy)" : ""}</td><td>${r.apariciones}</td></tr>`).join("")}</tbody>
      </table></div></section>` : "";
  caja.innerHTML = `
    <div class="ficha-cabeza" style="--rareza:${rareza}">
      <div class="ficha-img">${img ? `<img src="${esc(img)}" alt="" referrerpolicy="no-referrer">` : `<span class="sin-imagen">Sin imagen</span>`}</div>
      <div>
        <h2 id="ficha-nombre">${esc(a.nombre_completo || a.nombre)}</h2>
        <p class="sutil">${esc(a.tipo)} · <span style="color:${rareza}">${esc(a.rareza)}</span>${a.calidad && a.calidad !== a.rareza ? ` (${esc(a.calidad)})` : ""}
          ${a.en_tienda ? ` · <span class="etiqueta hoy">En tienda hoy</span>` : ""}</p>
        <dl class="datos">
          ${dato("Última vez en tienda", a.ultima_vez ? fechaDia(a.ultima_vez) : "Sin registro")}
          ${dato("Primera vez", a.primera_vez ? fechaDia(a.primera_vez) : "")}
          ${dato("Veces en tienda", a.ultima_vez ? a.veces : "")}
          ${dato("Último precio", a.ultimo_precio != null ? `${a.ultimo_precio.toLocaleString("es")} créditos` : "")}
          ${dato("Colores vistos", a.pinturas.length ? a.pinturas.join(", ") : "")}
        </dl>
        <div class="fila-botones izq">
          <button class="btn btn-principal btn-chico" data-crear-alerta-ficha="1">+ Alerta</button>
          ${urlSegura(a.url) ? `<a class="btn btn-chico" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">rl.source.gs ↗</a>` : ""}
          ${urlSegura(a.url_itemshop) ? `<a class="btn btn-chico" href="${esc(a.url_itemshop)}" target="_blank" rel="noopener noreferrer">itemshop.gg ↗</a>` : ""}
        </div>
      </div>
      <button class="btn btn-chico ficha-cerrar" data-cerrar-ficha="1" aria-label="Cerrar">✕</button>
    </div>
    <div class="ficha-cuerpo">
      <section><h3>Origen</h3>
        ${a.origenes.length ? `<ul class="lista-origen">${a.origenes.map((o) => `<li>${esc(describirOrigen(o))} <span class="sutil">(${esc(o.fuente)})</span></li>`).join("")}</ul>`
          : `<p class="sutil">Desconocido: no figura en los Rocket Pass, packs ni otras listas de la wiki. Puede venir de cajas, drops, eventos, Twitch, lotes de la tienda u otros.</p>`}
      </section>
      <section><h3>Historial en la tienda (itemshop.gg)</h3>${a.historial_error ? `<p class="error">${esc(a.historial_error)}</p>` : ""}${historial}</section>
      ${propio}
    </div>`;
}

function cerrarFicha() {
  $("#ficha-fondo").hidden = true;
  estado.fichaActual = null;
}

document.addEventListener("click", (ev) => {
  const abrir = ev.target.closest("[data-ficha]");
  if (abrir) return abrirFicha(abrir.dataset.ficha);
  if (ev.target.closest("[data-cerrar-ficha]") || ev.target === $("#ficha-fondo")) return cerrarFicha();
  if (ev.target.closest("[data-crear-alerta-ficha]") && estado.fichaActual) {
    const a = estado.fichaActual;
    cerrarFicha();
    cambiarVista("alertas");
    llenarFormulario({ nombre: a.nombre_completo || a.nombre, tienda: "Rocket League", tipo: a.categoria || "", exacto: 1 });
    $("#form-alerta").color.focus();
  }
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !$("#ficha-fondo").hidden) cerrarFicha(); });
$("#c-mas").addEventListener("click", () => cargarCatalogo(true));
$("#btn-catalogo").addEventListener("click", async () => {
  await api("/api/catalogo/actualizar", "POST").catch((e) => mostrarAviso(e.message));
  mostrarAviso("Actualizando el catálogo (tarda unos 30 segundos)…");
  setTimeout(() => cargarCatalogo(), 800);
});

// Actualiza los relojes cada 30 s sin volver a pintar todo
setInterval(() => {
  document.querySelectorAll(".reloj[data-hasta]").forEach((el) => {
    const r = restante(el.dataset.hasta);
    el.textContent = r.texto ? "⏱ " + r.texto : "";
    el.classList.toggle("pronto", r.pronto);
  });
  if (estado.datos) pintarCabecera();
}, 30000);

cargar();
