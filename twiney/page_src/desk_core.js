
/* ===================== TED — TWINEY EXECUTION DESK ===================== */
/* state is kept in separate objects: market/engine snapshot (state), broker (state.account/trading),
   UI layout (LAY), voice (VOICE), tabs (TABS). Panels re-render only when their own slice changed. */


function panelHTML(id, html){ const p = P[id]; if (p.last === html) return false; p.last = html; p.pc.innerHTML = html; return true; }

/* ---------- docking */
function emptyLayout(){ return {zones: {TL: [], TC: [], TR: [], TX: [], BL: [], BC: [], BR: [], BX: []}, active: {}, sizes: {c1: 250, c3: 430, c4: 300, r2: {L: 300, C: 300, R: 300, X: 300}}, floats: {}, hidden: [], max: null}; }
function normalize(l){
  const out = Object.assign(emptyLayout(), JSON.parse(JSON.stringify(l || {})));
  for (const z of ZONES) out.zones[z] = (out.zones[z] || []).filter(id => P[id]);
  // bottom heights are per column now; an older layout had one height for the whole bottom row
  const r2 = out.sizes.r2;
  if (typeof r2 === "number" || !r2) out.sizes.r2 = {L: r2 || 300, C: r2 || 300, R: r2 || 300, X: r2 || 300};
  const placed = new Set([].concat(...ZONES.map(z => out.zones[z])).concat(Object.keys(out.floats || {})));
  // a panel new in a build docks itself once (ALERTS beside the watchlist, EQUITY FLOW beside the option flow), so it is
  // not lost behind the PANELS menu; a panel you hid yourself stays hidden
  const NEW_PANELS = {myalerts: "TL", eqflow: "BC", urgency: "BC", bigmoney: "BC", conviction: "BC", bigtape: "BX", options: "BC", ochart: "BC"};
  out.seen = Array.isArray(out.seen) ? out.seen : Object.keys(P).filter(id => !(id in NEW_PANELS));
  for (const id of Object.keys(NEW_PANELS)) if (P[id] && !out.seen.includes(id)){ out.seen.push(id); if (!placed.has(id)){ out.zones[NEW_PANELS[id]].push(id); placed.add(id); } }
  out.hidden = Object.keys(P).filter(id => !placed.has(id));
  return out;
}
function zoneOf(id){ for (const z of ZONES) if (LAY.zones[z].includes(id)) return z; return null; }
function applyLayout(){
  const work = document.getElementById("work");
  const s = LAY.sizes;
  const has = z => LAY.zones[z].length > 0;
  // four columns; each column has its own split between its top and bottom window
  const COLS = [["L", "TL", "BL", "c1"], ["C", "TC", "BC", null], ["R", "TR", "BR", "c3"], ["X", "TX", "BX", "c4"]];
  const shown = {};
  for (const [c, top, bot, wk] of COLS){
    const col = work.querySelector(`.col[data-col="${c}"]`), t = has(top), b = has(bot);
    shown[c] = t || b;
    col.classList.toggle("empty", !shown[c]);
    if (wk) col.style.width = (s[wk] || 300) + "px";
    const zt = col.querySelector(`.zone[data-zone="${top}"]`), zb = col.querySelector(`.zone[data-zone="${bot}"]`), gh = col.querySelector(".gut.h");
    gh.style.display = t && b ? "" : "none";
    zt.classList.toggle("fill", t); zb.classList.toggle("fill", b && !t);
    zb.style.height = t && b ? (s.r2[c] || 300) + "px" : "";
  }
  // a width gutter sits between two columns that are both on screen
  const on = ["L", "C", "R", "X"].filter(c => shown[c]);
  document.getElementById("g1").style.display = shown.L && on.length > 1 ? "" : "none";
  document.getElementById("g2").style.display = shown.R ? "" : "none";
  document.getElementById("g3").style.display = shown.X && (shown.R || shown.C || shown.L) ? "" : "none";
  for (const z of ZONES){
    const zel = work.querySelector(`.zone[data-zone="${z}"]`), tabs = zel.querySelector(".ztabs"), body = zel.querySelector(".zbody");
    const ids = LAY.zones[z];
    zel.classList.toggle("empty", !ids.length);
    if (!ids.includes(LAY.active[z])) LAY.active[z] = ids[0] || null;
    tabs.innerHTML = ids.map(id => `<span class="ztab ${LAY.active[z] === id ? "on" : ""}" draggable="true" data-p="${id}">${PANELS[id]}${SYMBOL_LINKED.has(id) ? ` <span class="sym">${esc(curSym || "")}</span>` : ""}
        <span class="ctl"><span data-act="max" title="maximize / restore">⤢</span><span data-act="float" title="undock (floating window)">⧉</span><span data-act="hide" title="hide (Panels menu brings it back)">✕</span></span></span>`).join("");
    // SPLIT: two windows in this spot, one above the other (the tab you pick goes top, the other stays below)
    const split = !!(LAY.split && LAY.split[z]) && ids.length > 1;
    LAY.second = LAY.second || {};
    if (split && (!ids.includes(LAY.second[z]) || LAY.second[z] === LAY.active[z])) LAY.second[z] = ids.find(x => x !== LAY.active[z]);
    const second = split ? LAY.second[z] : null;
    for (const id of ids){ const p = P[id]; if (p.el.parentElement !== body) body.appendChild(p.el); p.el.classList.toggle("on", LAY.active[z] === id || id === second); p.el.classList.remove("float"); p.el.style.cssText = "";
      if (split && id === LAY.active[z]) Object.assign(p.el.style, {bottom: "auto", height: "50%"});
      if (split && id === second) Object.assign(p.el.style, {top: "50%", height: "50%", borderTop: "2px solid #2a3548"}); }
    tabs.querySelectorAll(".ztab").forEach(t => t.classList.toggle("on2", t.dataset.p === second));
    if (ids.length > 1) tabs.insertAdjacentHTML("beforeend", `<span class="zsplit ${split ? "on" : ""}" data-zsplit="${z}" title="${split ? "one window here" : "split: two windows here, one above the other"}">${split ? "▭" : "⬓"}</span>`);
  }
  // floating
  for (const [id, f] of Object.entries(LAY.floats || {})){
    const p = P[id]; if (!p) continue;
    if (!p.el.querySelector(":scope > .ztabs")){ const t = document.createElement("div"); t.className = "ztabs"; p.el.prepend(t); }
    p.el.querySelector(":scope > .ztabs").innerHTML = `<span class="ztab on" draggable="true" data-p="${id}">${PANELS[id]}${SYMBOL_LINKED.has(id) ? ` <span class="sym">${esc(curSym || "")}</span>` : ""}<span class="ctl"><span data-act="dock" title="dock it: pick the spot (it stays there)">DOCK ▾</span><span data-act="hide" title="hide">✕</span></span></span>`;
    p.el.classList.add("on", "float"); work.appendChild(p.el);
    Object.assign(p.el.style, {left: f.l + "px", top: f.t + "px", width: f.w + "px", height: f.h + "px"});
  }
  for (const id of LAY.hidden){ const p = P[id]; p.el.classList.remove("on", "float"); if (p.el.parentElement !== pool) pool.appendChild(p.el); }
  // a docked panel that has a stray float tab strip
  for (const id of Object.keys(P)) if (!(LAY.floats || {})[id]){ const t = P[id].el.querySelector(":scope > .ztabs"); if (t) t.remove(); }
  // maximize
  document.querySelectorAll(".pnl.max").forEach(e => e.classList.remove("max"));
  if (LAY.max && P[LAY.max]){ const p = P[LAY.max]; work.appendChild(p.el); p.el.classList.add("on", "max"); }
  renderPanelsMenu();
  Object.values(charts).forEach(c => drawChart(c));
  saveLayoutLocal();
}
function movePanel(id, zone, floatPos){
  for (const z of ZONES) LAY.zones[z] = LAY.zones[z].filter(x => x !== id);
  delete LAY.floats[id]; LAY.hidden = LAY.hidden.filter(x => x !== id);
  if (zone === "float") LAY.floats[id] = floatPos || {l: 80, t: 60, w: 520, h: 360};
  else if (zone){ LAY.zones[zone].push(id); LAY.active[zone] = id; }
  else LAY.hidden.push(id);
  if (LAY.max === id && zone !== "max") LAY.max = null;
  applyLayout();
}
function showPanel(id){ if (LAY.hidden.includes(id)){ movePanel(id, LAY.zones.TC.length ? "BC" : "TC"); } else { const z = zoneOf(id); if (z){ LAY.active[z] = id; applyLayout(); } } }
function saveLayoutLocal(){ store.set("lay", LAY); store.set("layName", layoutName);
  if (typeof OC !== "undefined" && OC.link && typeof rememberPlace === "function" && (zoneOf("obook") || zoneOf("otape") || (LAY.floats || {}).obook || (LAY.floats || {}).otape)) rememberPlace(); }
/* drag a panel tab into another zone (or out to float) */
let dragId = null;
document.addEventListener("dragstart", e => { const t = e.target.closest(".ztab"); if (!t){ return; } dragId = t.dataset.p; e.dataTransfer.setData("text/plain", dragId); e.dataTransfer.effectAllowed = "move"; });
document.addEventListener("dragend", () => { dragId = null; document.querySelectorAll(".zone.drop").forEach(z => z.classList.remove("drop")); });
document.getElementById("work").addEventListener("dragover", e => { if (!dragId) return; e.preventDefault(); const z = e.target.closest(".zone"); document.querySelectorAll(".zone.drop").forEach(x => x.classList.remove("drop")); if (z) z.classList.add("drop"); });
document.getElementById("work").addEventListener("drop", e => {
  if (!dragId) return; e.preventDefault();
  const z = e.target.closest(".zone");
  if (z) movePanel(dragId, z.dataset.zone);
  else { const r = document.getElementById("work").getBoundingClientRect(); movePanel(dragId, "float", {l: e.clientX - r.left - 100, t: e.clientY - r.top - 10, w: 520, h: 360}); }
  dragId = null;
});
// drop onto an empty zone: zones with no panels are display:none, so offer all 8 zones while dragging
document.addEventListener("dragstart", () => setTimeout(() => { document.body.classList.add("dragging"); document.querySelectorAll(".zone.tall").forEach(z => z.classList.remove("tall")); document.querySelectorAll(".zone.empty").forEach(z => { z.classList.remove("empty"); z.dataset.wasEmpty = "1"; }); }, 0));
document.addEventListener("dragend", () => { document.body.classList.remove("dragging"); document.querySelectorAll(".zone[data-wasEmpty]").forEach(z => { delete z.dataset.wasEmpty; }); applyLayout(); });
document.addEventListener("click", e => {
  const c = e.target.closest(".ztab .ctl span"); const tab = e.target.closest(".ztab");
  if (c){ e.stopPropagation(); const id = tab.dataset.p, act = c.dataset.act;
    if (act === "hide") movePanel(id, null);
    else if (act === "float"){ LAY.home = LAY.home || {}; const z = zoneOf(id); if (z) LAY.home[id] = z; movePanel(id, "float"); }
    else if (act === "dock") dockPicker(id, c);
    else if (act === "max"){ LAY.max = LAY.max === id ? null : id; applyLayout(); }
    return; }
  const zs = e.target.closest(".zsplit"); if (zs){ LAY.split = LAY.split || {}; LAY.split[zs.dataset.zsplit] = !LAY.split[zs.dataset.zsplit]; applyLayout(); return; }
  if (tab){ const z = tab.closest(".zone"); if (z){ const zn = z.dataset.zone, id = tab.dataset.p;
    if (LAY.split && LAY.split[zn] && LAY.zones[zn].length > 1){
      if (id === (LAY.second || {})[zn]){ LAY.second[zn] = LAY.active[zn]; LAY.active[zn] = id; }
      else if (id !== LAY.active[zn]){ LAY.second = LAY.second || {}; LAY.second[zn] = id; }
    } else LAY.active[zn] = id;
    applyLayout(); } }
});
// floating window: move by its tab strip; size via the corner (resize:both) is picked up on mouseup
document.addEventListener("mousedown", e => {
  const strip = e.target.closest(".float > .ztabs"); if (!strip || e.target.closest(".ctl")) return;
  const el = strip.parentElement, id = el.querySelector(".ztab").dataset.p, sx = e.clientX, sy = e.clientY, ol = el.offsetLeft, ot = el.offsetTop;
  e.preventDefault();
  const move = ev => { el.style.left = Math.max(0, ol + ev.clientX - sx) + "px"; el.style.top = Math.max(0, ot + ev.clientY - sy) + "px"; };
  const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); LAY.floats[id] = {l: el.offsetLeft, t: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight}; saveLayoutLocal(); };
  window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
});
document.addEventListener("mouseup", e => { const el = e.target.closest(".float"); if (el){ const id = el.querySelector(".ztab").dataset.p; if (LAY.floats[id]){ LAY.floats[id] = {l: el.offsetLeft, t: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight}; saveLayoutLocal(); Object.values(charts).forEach(drawChart); } } });
// gutters: grab any divider and pull or push. While you hold it the divider lights up as a line and only that
// one column / window moves, once per screen frame (nothing else on the desk is rebuilt), so it follows the mouse
// smoothly; the charts redraw at the new size as you go. Let go and the size is saved.
document.querySelectorAll(".gut").forEach(g => g.addEventListener("mousedown", e => {
  if (e.button !== 0) return;
  e.preventDefault();
  const k = g.dataset.gut, horiz = k === "h";
  let frame = 0, lastEv = null;
  g.classList.add("grab"); document.body.classList.add("resizing", horiz ? "resizing-h" : "resizing-v");
  let apply;
  if (horiz){                                       // this column's own top / bottom split: drag up = bigger bottom window
    const c = g.dataset.col, col = g.parentElement, start = e.clientY, base = LAY.sizes.r2[c] || 300;
    const zb = g.nextElementSibling && g.nextElementSibling.classList.contains("zone") ? g.nextElementSibling : col.querySelector(".zone:last-of-type");
    apply = ev => { const v = Math.round(Math.max(60, Math.min(col.clientHeight - 60, base - (ev.clientY - start)))); LAY.sizes.r2[c] = v; if (zb) zb.style.height = v + "px"; };
  } else {                                          // a width gutter: sizes the column on its outer side; the middle column takes the rest
    const sign = k === "c1" ? 1 : -1, start = e.clientX, base = LAY.sizes[k] || 300;
    const colOf = {c1: "L", c3: "R", c4: "X"}[k], col = document.querySelector(`#work .col[data-col="${colOf}"]`);
    apply = ev => { const v = Math.round(Math.max(120, Math.min(window.innerWidth * 0.6, base + sign * (ev.clientX - start)))); LAY.sizes[k] = v; if (col) col.style.width = v + "px"; };
  }
  const tick = () => { frame = 0; if (lastEv){ apply(lastEv); Object.values(charts).forEach(drawChart); } };
  const move = ev => { lastEv = ev; if (!frame) frame = requestAnimationFrame(tick); };
  const up = () => {
    window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up);
    if (frame) cancelAnimationFrame(frame); if (lastEv) apply(lastEv);
    g.classList.remove("grab"); document.body.classList.remove("resizing", "resizing-h", "resizing-v");
    applyLayout(); saveLayoutLocal(); Object.values(charts).forEach(drawChart);
  };
  window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
}));
function renderPanelsMenu(){
  document.getElementById("panelsPop").innerHTML = `<h5>PANELS</h5>` + Object.keys(PANELS).map(id => `<label><input type="checkbox" data-show="${id}" ${LAY.hidden.includes(id) ? "" : "checked"}> ${PANELS[id]}</label>`).join("");
}
document.getElementById("panelsPop").addEventListener("change", e => { const id = e.target.dataset.show; if (!id) return; if (e.target.checked) showPanel(id); else movePanel(id, null); });

/* ---------- layouts: presets + named, server-side */
function layoutFromPreset(name){ const p = PRESETS[name]; const l = emptyLayout(); l.zones = JSON.parse(JSON.stringify(p.zones)); l.active = Object.assign({}, p.active); l.sizes = Object.assign(l.sizes, JSON.parse(JSON.stringify(p.sizes)));
  if (p.split) l.split = Object.assign({}, p.split); if (p.second) l.second = Object.assign({}, p.second);
  l.ver = p.ver || 1;
  if (p.exact) l.seen = Object.keys(P);          // exactly these panels: the rest wait in PANELS ▾, nothing docks itself
  for (const [id, tf] of Object.entries(p.tf || {})) store.set("tf." + id, tf);
  return normalize(l); }
function renderLayoutSel(){
  const sel = document.getElementById("layoutSel");
  const names = [...Object.keys(PRESETS).map(n => "★ " + n), ...Object.keys(LAYOUTS)];
  sel.innerHTML = `<optgroup label="PRESETS">` + names.filter(n => n.startsWith("★ ")).map(n => `<option value="${esc(n)}" ${n === layoutName ? "selected" : ""}>${esc(n.slice(2))}</option>`).join("") + `</optgroup>` + (Object.keys(LAYOUTS).length ? `<optgroup label="SAVED">` + Object.keys(LAYOUTS).map(n => `<option value="${esc(n)}" ${n === layoutName ? "selected" : ""}>${esc(n)}</option>`).join("") + `</optgroup>` : "");
  if (!names.includes(layoutName)) sel.value = "";
}
async function useLayout(name){
  if (name.startsWith("★ ")){ LAY = layoutFromPreset(name.slice(2)); }
  else if (LAYOUTS[name]) LAY = normalize(LAYOUTS[name]);
  else return;
  layoutName = name; applyLayout(); renderLayoutSel();
  post("/api/layouts", {action: "use", name});
}
document.getElementById("layoutSel").addEventListener("change", e => useLayout(e.target.value));
document.getElementById("layoutMenu").querySelector("button").addEventListener("click", e => { e.stopPropagation();
  const m = document.getElementById("layoutMenu"), open = !m.classList.contains("open"); document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); m.classList.toggle("open", open);
  document.getElementById("layoutPop").innerHTML = `<h5>LAYOUTS</h5>
    <div class="row"><input id="layName" placeholder="name" value="${esc(layoutName && !layoutName.startsWith("★") ? layoutName : "")}"><button data-lay="save">Save</button></div>
    <div class="row"><button data-lay="dup">Duplicate</button><button data-lay="rename">Rename</button><button data-lay="delete">Delete</button><button data-lay="reset">Reset to preset</button></div>
    <div class="dim" style="font-size:10.5px;margin-top:4px">Presets are fixed. Save a copy under your own name to change one. The last layout used loads at the next start.</div>`;
});
document.getElementById("layoutPop").addEventListener("click", async e => {
  const b = e.target.closest("button[data-lay]"); if (!b) return;
  const act = b.dataset.lay, inp = document.getElementById("layName"), name = (inp.value || "").trim();
  if (act === "save" || act === "dup"){ const nm = name || prompt("Layout name:"); if (!nm) return; const out = await post("/api/layouts", {action: "save", name: nm, layout: LAY}); if (out.ok){ LAYOUTS = out.layouts; layoutName = nm; renderLayoutSel(); toast("Layout saved: " + nm, true); } }
  else if (act === "rename"){ if (!layoutName || layoutName.startsWith("★")) return toast("Pick a saved layout first", false); const to = prompt("New name:", layoutName); if (!to) return; const out = await post("/api/layouts", {action: "rename", name: layoutName, to}); if (out.ok){ LAYOUTS = out.layouts; layoutName = to; renderLayoutSel(); } }
  else if (act === "delete"){ if (!layoutName || layoutName.startsWith("★")) return toast("Presets can't be deleted", false); if (!confirm("Delete layout " + layoutName + "?")) return; const out = await post("/api/layouts", {action: "delete", name: layoutName}); if (out.ok){ LAYOUTS = out.layouts; useLayout("★ PS60 Execution"); } }
  else if (act === "reset"){ useLayout("★ Stock + Options"); }
  document.getElementById("layoutMenu").classList.remove("open");
});
async function loadLayouts(){
  try { const j = await (await fetch("/api/layouts", {cache: "no-store"})).json(); LAYOUTS = j.layouts || {}; PREFS = j.prefs || {};
    const last = j.last; const local = store.get("lay", null), localName = store.get("layName", null);
    const stale = local && localName && localName.startsWith("★ ") && PRESETS[localName.slice(2)] && (PRESETS[localName.slice(2)].ver || 1) !== (local.ver || 1);
    if (local && localName === last && !stale){ LAY = normalize(local); layoutName = localName; }
    else if (stale && localName === last){ LAY = layoutFromPreset(localName.slice(2)); layoutName = localName; }   // a preset that changed in this build
    else if (last && last.startsWith("★ ") && PRESETS[last.slice(2)]){ LAY = layoutFromPreset(last.slice(2)); layoutName = last; }
    else if (last && LAYOUTS[last]){ LAY = normalize(LAYOUTS[last]); layoutName = last; }
  } catch (e) {}
  if (!LAY){ LAY = layoutFromPreset("Stock + Options"); layoutName = "★ Stock + Options"; }
  renderLayoutSel(); applyLayout();
  // this build brings Twiney's own layout: it opens once on its own (LAYOUT ▾ still lists every other one)
  if (!store.get("lay.stockopt1", false)){ store.set("lay.stockopt1", true); if (layoutName !== "★ Stock + Options") useLayout("★ Stock + Options"); }
}

/* ---------- symbol tabs */
function renderTabs(){
  document.getElementById("symTabs").innerHTML = TABS.list.map(s => `<span class="stab ${s === TABS.active ? "on" : ""}" data-sym="${esc(s)}">${esc(s)}${s === TABS.active && store.get("voice", true) ? `<span class="v" title="voice reads this tab">VOICE</span>` : ""}<span class="x" data-close="${esc(s)}" title="close tab">✕</span></span>`).join("");
  document.querySelectorAll(".ztab .sym").forEach(el => el.textContent = curSym || "");
}
async function openTab(sym, add){
  sym = String(sym || "").trim().toUpperCase(); if (!sym) return;
  const known = state && state.symbols && state.symbols.includes(sym);
  const out = await post("/api/play", {symbol: sym, action: known || !add ? "focus" : "add"});
  if (!out.ok){ toast(known ? "Could not open " + sym : sym + " is not a valid ticker", false); return; }
  if (!TABS.list.includes(sym)) TABS.list.push(sym);
  TABS.active = sym; curSym = sym;
  const rec = (PREFS.recent || []).filter(x => x !== sym); rec.unshift(sym); PREFS.recent = rec.slice(0, 12);
  savePrefs({tabs: TABS.list, active: sym, recent: PREFS.recent});
  if (!known) toast(sym + " added as a watch-only play — mark its pivot on the chart", true);
  // the chart keeps ONE view object (its mouse handlers hold it); render() swaps the per-symbol view state into it
  renderTabs(); renderRecent(); poll(true);
}
function closeTab(sym){ TABS.list = TABS.list.filter(s => s !== sym); if (TABS.active === sym){ TABS.active = TABS.list[TABS.list.length - 1] || null; curSym = TABS.active; if (curSym) post("/api/play", {symbol: curSym, action: "focus"}); } savePrefs({tabs: TABS.list, active: TABS.active}); renderTabs(); poll(true); }
document.getElementById("symTabs").addEventListener("click", e => { const x = e.target.closest("[data-close]"); if (x){ closeTab(x.dataset.close); return; } const t = e.target.closest(".stab"); if (t) openTab(t.dataset.sym, false); });
document.getElementById("addTab").addEventListener("click", () => document.getElementById("symIn").focus());
document.getElementById("symIn").addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter"){ openTab(e.target.value, true); e.target.value = ""; e.target.blur(); } if (e.key === "Escape") e.target.blur(); });
document.getElementById("symHist").addEventListener("change", e => { if (e.target.value) openTab(e.target.value, false); e.target.value = ""; });
function renderRecent(){ document.getElementById("symHist").innerHTML = `<option value="">RECENT</option>` + (PREFS.recent || []).map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join(""); }
let prefsTimer = null;
function savePrefs(p){ Object.assign(PREFS, p); clearTimeout(prefsTimer); prefsTimer = setTimeout(() => post("/api/layouts", {action: "prefs", prefs: p}), 300); }
function viewFor(sym, id){ VIEWS[sym] = VIEWS[sym] || {}; if (!VIEWS[sym][id]) VIEWS[sym][id] = {cw: id === "foot" ? 64 : 11, offset: restOffset(), yLo: null, yHi: null, follow: true, cross: null}; return VIEWS[sym][id]; }

/* ---------- charts (reuse the drawing engine) */
const charts = {};
function mkChart(id, isFoot){
  const p = P[id]; const el = p.el;
  const c = {id, type: isFoot ? "foot" : "chart", el, isFoot, data: null, canvas: el.querySelector("canvas"), tools: el.querySelector(".chart-tools"), view: viewFor("_", id)};
  el._pane = c;
  wireChart(c, c.canvas, c.view, () => {}, isFoot);
  // wireChart captured the first view object: keep the same object and copy state on symbol change
  c.setView = v => { Object.assign(c.view, v); };
  new ResizeObserver(() => drawChart(c)).observe(el);
  if (!isFoot){
    c.tools.addEventListener("change", e => { if (e.target.dataset.mark){ c.view.levelTool = e.target.value || null; renderTools(c); } if (e.target.dataset.screen){ store.set("screen", e.target.value); if (store.get("wick", null) == null) store.set("wick", e.target.value === "desk" ? 1 : 3); drawChart(c); renderTools(c); } });
    c.tools.addEventListener("input", e => {
      const k = e.target.dataset.indk, top = e.target.dataset.top, cs = e.target.dataset.cs;
      if (e.target.dataset.study){ const on = e.target.checked, nm = e.target.dataset.study;
        post("/api/settings", {changes: {["studies." + nm]: on}}).then(out => { toast(out.ok ? `${nm.toUpperCase()} ${on ? "ON" : "OFF"}` : "Not saved: " + (out.reason || ""), out.ok); poll(true); });
        return; }
      if (e.target.dataset.vol){ store.set("volstyle", e.target.dataset.vol); Object.values(charts).forEach(drawChart); }
      if (k){ const IND = store.get("ind", {}); IND[k] = e.target.checked; store.set("ind", IND); drawChart(c); }
      if (top){ store.set(top, e.target.checked); Object.values(charts).forEach(drawChart); const b = c.tools.querySelector(`button[data-${top}]`); if (b) b.classList.toggle("on", e.target.checked); }
      if (cs === "screenColor"){ store.set("screenColor", e.target.value); store.set("screen", "custom"); Object.values(charts).forEach(drawChart); const s = c.tools.querySelector("select[data-screen]"); if (s) s.value = "custom"; return; }
      if (cs){ store.set(cs, +e.target.value); const v = c.tools.querySelector(`[data-csv="${cs}"]`); if (v) v.textContent = e.target.value + (cs === "wick" ? "px" : cs === "rspace" ? " bars" : "%");
        if (cs === "rspace") for (const ch of Object.values(charts)) if (ch.view && ch.view.follow){ ch.view.offset = restOffset(); ch.view.rightT = null; }   // live charts move to it now
        Object.values(charts).forEach(drawChart); }
    });
    c.tools.addEventListener("mousedown", e => e.stopPropagation());
    c.tools.addEventListener("click", e => {
      const tf = e.target.dataset.tf;
      if (tf){ store.set("tf." + id, tf === "D" ? "D" : +tf); c.view.offset = restOffset(); c.view.follow = true; c.view.yLo = c.view.yHi = null; c.view.autoY = null; if (tf === "D" && c.view.cw < 6) c.view.cw = 8; drawChart(c); renderTools(c); }
      for (const k of ["mas", "bb"]) if (e.target.dataset[k]){ store.set(k, !store.get(k, k === "mas" || k === "bb")); drawChart(c); renderTools(c); }
      if (e.target.dataset.ind){ e.stopPropagation(); const m = e.target.closest(".menu"), open = !m.classList.contains("open"); document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); m.classList.toggle("open", open); if (open){ m.querySelector(".pop").innerHTML = indPopHTML(); placePop(m); } }
      if (e.target.closest(".menu.ind .pop")) e.stopPropagation();
      if (e.target.dataset.vwap){ store.set("vwap", !store.get("vwap", true)); drawChart(c); renderTools(c); }
      if (e.target.dataset.foot){ const on = !store.get("foot." + id, false); store.set("foot." + id, on); if (on && c.view.cw < 40){ c.view.cw = 44; c.view.offset = restOffset(); c.view.follow = true; } drawChart(c); renderTools(c); }
      if (e.target.dataset.clean){ store.set("clean", !store.get("clean", true)); el.classList.toggle("clean", store.get("clean", true)); drawChart(c); renderTools(c); }
      if (e.target.dataset.fit){ const n = aggBars(c.data ? c.data.bars : [], store.get("tf." + id, 1)).length || 1; c.view.cw = Math.max(2, Math.min(40, (c.canvas.clientWidth - 86) / n)); c.view.offset = restOffset(); c.view.follow = true; c.view.yLo = c.view.yHi = null; drawChart(c); }
    });
    renderTools(c);
  }
  charts[id] = c; return c;
}
function indPopHTML(){
  const IND = store.get("ind", {}), on = k => IND[k] !== false;
  const box = (k, label, col) => `<label><input type="checkbox" data-indk="${k}" ${on(k) ? "checked" : ""}> <i style="display:inline-block;width:14px;height:3px;background:${col};vertical-align:middle"></i> ${label}</label>`;
  const SO = (typeof state !== "undefined" && state && state.studies_on) || {};
  const sbox = (k, label) => `<label><input type="checkbox" data-study="${k}" ${SO[k] ? "checked" : ""}> ${label}</label>`;
  return `<h5>STUDIES · STOCK CHART</h5>${sbox("gas", "GAS + ATR (tank, ATR levels, PDH / PDL, PMH / PML, box, 2nd entry)")}${sbox("airspace", "AIRSPACE (Bounce / Reject, MP, MT supply / demand)")}${sbox("unvisited", "UNVISITED HIGHS / LOWS")}
    <div style="margin-left:14px">${sbox("gas_readout", "GAS readout panel (bottom right)")}${sbox("air_board", "AIRSPACE board panel (top left)")}${sbox("whole_numbers", "whole-number lines (WHOLE 147.00 ...)")}</div>
    <div class="dim" style="font-size:10.5px;margin-bottom:4px">Every piece of each is in SETTINGS &gt; Chart studies.</div>
    <h5>SCREEN</h5>
    <div class="row"><span class="dim" style="width:64px">CUSTOM</span><input type="color" data-cs="screenColor" value="${store.get("screenColor", "#dfe9f3")}" title="your own screen colour (pick CUSTOM on the toolbar)"><span class="dim" style="font-size:10px">pick CUSTOM on the toolbar to use it</span></div>
    <label><input type="checkbox" data-top="matags" ${store.get("matags", true) ? "checked" : ""}> value tags on the price scale, one per line</label>
    <h5>VOLUME</h5>
    <label><input type="radio" name="volstyle" data-vol="auto" ${store.get("volstyle", "auto") === "auto" ? "checked" : ""}> match the screen (Dan's on light screens, desk on dark)</label>
    <label><input type="radio" name="volstyle" data-vol="dan" ${store.get("volstyle", "auto") === "dan" ? "checked" : ""}> Dan's: green up close, red down close</label>
    <label><input type="radio" name="volstyle" data-vol="desk" ${store.get("volstyle", "auto") === "desk" ? "checked" : ""}> desk: split buyers paid up / sellers hit bid</label>
    <h5>CANDLES</h5>
    <div class="row"><span class="dim" style="width:64px">WICK</span><input type="range" data-cs="wick" min="1" max="8" step="0.5" value="${store.get("wick", store.get("screen", "blue") !== "desk" ? 3 : 1)}" style="flex:1"><span class="mono" data-csv="wick">${store.get("wick", store.get("screen", "blue") !== "desk" ? 3 : 1)}px</span></div>
    <div class="row" title="empty bars kept right of the last candle, so price action isn't jammed against the edge. Double-click the chart to go back to it"><span class="dim" style="width:64px">SPACE →</span><input type="range" data-cs="rspace" min="0" max="40" step="1" value="${store.get("rspace", 0)}" style="flex:1"><span class="mono" data-csv="rspace">${store.get("rspace", 0)} bars</span></div>
    <div class="row"><span class="dim" style="width:64px">BODY</span><input type="range" data-cs="body" min="20" max="95" step="5" value="${store.get("body", store.get("screen", "blue") !== "desk" ? 76 : 70)}" style="flex:1"><span class="mono" data-csv="body">${store.get("body", store.get("screen", "blue") !== "desk" ? 76 : 70)}%</span></div>
    <h5>SMA</h5>${DAN_SMA.map(([n, col]) => box("s" + n, n + " SMA", col)).join("")}
    <h5>EMA</h5>${DAN_EMA.map(([n, col]) => box("e" + n, n + " EMA", col)).join("")}
    <h5>EMA · DAILY CHART ONLY</h5>${DAN_EMA_DAILY.map(([n, col]) => box("d" + n, n + " EMA", col)).join("")}
    <h5>BANDS</h5><label><input type="checkbox" data-top="bb" ${store.get("bb", true) ? "checked" : ""}> <i style="display:inline-block;width:14px;height:3px;background:${DAN_BB};vertical-align:middle"></i> Bollinger 20 / 2.0</label>
    <label><input type="checkbox" data-top="datawin" ${store.get("datawin", true) ? "checked" : ""}> data window (the floating OK box: bar values and every line at the cursor)</label>
    <div class="dim" style="font-size:10.5px;margin-top:6px">MAS on the toolbar switches every average at once; these boxes pick the lines.</div>`;
}
/* the floating data window: eSignal's "OK" box. Bar values and every line's value at the cursor, draggable. */
function renderDataWin(p){
  const wrap = p.el.querySelector(".chart-wrap"); if (!wrap) return;
  let w = wrap.querySelector(".datawin");
  // each chart has its own box: where you put it and whether it is shrunk. The main chart keeps the old settings;
  // the other charts (CHART 2 / 3, OPTION CHART) start shrunk to Symbol..Close so the candles stay clear
  const main = !p.id || p.id === "chart", posKey = main ? "datawin.pos2" : "datawin.pos2." + p.id, minKey = main ? "datawin.min3" : "datawin.min2." + p.id, minDefault = !main;   // the stock chart shows the whole box; the shorter charts start with the one-line box
  const on = store.get("datawin", true) && p.data && p.dataBar;
  if (!on){ if (w) w.style.display = "none"; return; }
  if (!w){
    w = document.createElement("div"); w.className = "datawin"; wrap.appendChild(w);
    const pos = store.get(posKey, null); if (pos){ w.style.left = pos[0] + "px"; w.style.top = pos[1] + "px"; w.style.bottom = "auto"; }
    w.addEventListener("click", e => { if (e.target.classList.contains("mn")){ store.set(minKey, !store.get(minKey, minDefault)); w.dataset.h = ""; renderDataWin(p); } });
    w.addEventListener("mousedown", e => { if (e.target.classList.contains("mn")) return; e.stopPropagation(); e.preventDefault(); const r = w.getBoundingClientRect(), wr = wrap.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      const mv = ev => { w.style.left = Math.max(0, Math.min(wr.width - r.width, ev.clientX - wr.left - dx)) + "px"; w.style.top = Math.max(0, Math.min(wr.height - r.height, ev.clientY - wr.top - dy)) + "px"; w.style.bottom = "auto"; };
      const up = () => { window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up); store.set(posKey, [parseInt(w.style.left), parseInt(w.style.top)]); };
      window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up); });
  }
  w.style.display = "";
  const b = p.dataBar, d = p.data, tf = p.dataTf, dt = new Date(b[0] * 1000);
  const ny = o => dt.toLocaleString("en-US", Object.assign({timeZone: "America/New_York"}, o));
  const lum = c => { const n = parseInt(c.slice(1), 16); return (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)); };
  const f = v => v == null ? "—" : (+v).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  const rows = (p.dataRows || []).map(([name, col, val]) => `<div class="r" style="background:${col};color:${lum(col) > 140 ? "#000" : "#fff"}"><span>${name}</span><span>${f(val)}</span></div>`).join("");
  const min = store.get(minKey, minDefault);
  w.classList.toggle("min", min);
  // shrunk = the black box only (Symbol through Close); the coloured indicator rows and Vol fold away under it
  const html = `<div class="ok"><span>OK</span><b class="mn" title="${min ? "show every line's value too" : "fold the indicator rows away: keep the black box"}">${min ? "▾" : "▴"}</b></div>
    <div class="kv"><span>Symbol:</span><span>${esc(d.symbol)},${tf === "D" ? "D" : tf}</span></div>
    <div class="kv"><span>Date:</span><span>${ny({month: "2-digit", day: "2-digit", year: "2-digit"})}</span></div>
    <div class="kv"><span>Time:</span><span>${tf === "D" ? "00:00" : ny({hour: "2-digit", minute: "2-digit", hourCycle: "h23"})}</span></div>
    <div class="kv"><span>Price:</span><span>${f(p.dataPrice != null ? p.dataPrice : b[4])}</span></div>
    <div class="kv"><span>Open:</span><span>${f(b[1])}</span></div><div class="kv"><span>High:</span><span>${f(b[2])}</span></div>
    <div class="kv"><span>Low:</span><span>${f(b[3])}</span></div><div class="kv"><span>Close:</span><span>${f(b[4])}</span></div>
    ${min ? "" : rows + `<div class="r vol"><span>Vol</span><span>${(b[5] || 0).toLocaleString("en-US")}</span></div>`}`;
  if (w.dataset.h !== html){ w.dataset.h = html; w.innerHTML = html; }
}
function renderTools(v){
  if (!v.tools || v.type !== "chart") return;
  const tf = store.get("tf." + v.id, 1);
  v.tools.innerHTML = [1, 5, 15, 60, "D"].map(m => `<button data-tf="${m}" class="${String(tf)===String(m)?"on":""}">${m === "D" ? "D" : m + "m"}</button>`).join("")
    + `<button data-fit="1">fit</button><button data-vwap="1" class="${store.get("vwap", true) ? "on" : ""}">VWAP</button>`
    + `<button data-mas="1" class="${store.get("mas", true) ? "on" : ""}" title="Dan's moving averages: SMA 5/10/20/50/100/150/200, EMA 5/10/20/50/100/150/200, plus 34/65/89 EMA on Daily only">MAS</button>`
    + `<button data-bb="1" class="${store.get("bb", true) ? "on" : ""}" title="Bollinger Bands 20 / 2.0">BB</button>`
    + `<select data-screen="1" class="${store.get("screen", "blue") !== "desk" ? "on" : ""}" title="the screen: dark desk, or an eSignal-style light screen with Dan's candles">${[["desk", "DESK"], ["white", "WHITE"], ["blue", "BLUE"], ["pink", "PINK"], ["custom", "CUSTOM"]].map(([v, l]) => `<option value="${v}" ${store.get("screen", "blue") === v ? "selected" : ""}>${l}</option>`).join("")}</select>`
    + `<span class="menu ind"><button data-ind="1" title="pick the lines you want, set wick and body width">IND</button><div class="pop">${indPopHTML()}</div></span>`
    + `<button data-foot="1" class="${store.get("foot." + v.id, false) ? "on" : ""}" title="footprint on this timeframe">FOOT</button>`
    + `<button data-clean="1" class="${store.get("clean", true) ? "on" : ""}" title="clean chart: candles, volume, VWAP, your levels, your orders">clean</button>`
    + `<select data-mark="1" class="lvl ${v.view.levelTool ? "on" : ""}" title="mark a level: pick it, click the chart at the price (saved to plays.json)"><option value="">MARK</option><option value="second_entry" ${v.view.levelTool==="second_entry"?"selected":""}>2nd entry</option><option value="trigger" ${v.view.levelTool==="trigger"?"selected":""}>pivot</option><option value="target" ${v.view.levelTool==="target"?"selected":""}>target</option><option value="stop" ${v.view.levelTool==="stop"?"selected":""}>stop</option><option value="extra" ${v.view.levelTool==="extra"?"selected":""}>extra level</option></select>`;
  v.canvas.classList.toggle("lvltool", !!v.view.levelTool);
}
function drawChart(v){ if (!v || !v.data || !v.canvas || v.el.offsetParent === null) return; drawOne(v, v.canvas, v.view, v.isFoot); }
function chartViewFor(){ return charts.chart; }
function curData(){ return charts.chart ? charts.chart.data : null; }
function dataFor(s, sym){ if (!sym || !s) return null; return (s.panes || []).find(d => d && d.symbol === sym) || (s.extra && s.extra[sym]) || null; }
/* menus live inside bars that clip overflow: place the popup with fixed coordinates when it opens */
function placePop(m){ const b = m.querySelector(":scope > button"), pop = m.querySelector(":scope > .pop"); if (!b || !pop) return; const r = b.getBoundingClientRect(); pop.style.position = "fixed"; pop.style.top = (r.bottom + 3) + "px"; pop.style.left = "auto"; pop.style.right = Math.max(4, window.innerWidth - r.right) + "px"; pop.style.maxHeight = (window.innerHeight - r.bottom - 12) + "px"; pop.style.overflow = "auto"; }
document.addEventListener("click", e => { const m = e.target.closest(".menu"); if (!m) return; setTimeout(() => { if (m.classList.contains("open")) placePop(m); }, 0); }, true);

/* DOCK ▾ on a floating window: pick the spot. Back where it came from is first; the layout is saved, so it stays */
const ZONE_NAMES = {TL: "left, top", BL: "left, bottom", TC: "middle, top", BC: "middle, bottom", TR: "right, top", BR: "right, bottom", TX: "far right, top", BX: "far right, bottom"};
function dockPicker(id, anchor){
  const old = document.getElementById("dockPick"); if (old) old.remove();
  const home = (LAY.home || {})[id];
  const m = document.createElement("div"); m.id = "dockPick"; m.className = "pop cmenu";
  m.innerHTML = `<div class="dim" style="font-size:11px;margin-bottom:4px">DOCK ${esc(PANELS[id])} TO</div>` +
    (home ? `<button data-dz="${home}"><b>back where it was</b> · ${ZONE_NAMES[home]}</button>` : "") +
    ["TL", "TC", "TR", "TX", "BL", "BC", "BR", "BX"].map(z => `<button data-dz="${z}">${ZONE_NAMES[z]}${LAY.zones[z].length ? ` <span class="dim">(with ${esc(LAY.zones[z].map(x => PANELS[x]).join(", ").slice(0, 40))})</span>` : ` <span class="dim">(empty)</span>`}</button>`).join("");
  const r = anchor.getBoundingClientRect();
  m.style.left = Math.min(r.left, window.innerWidth - 280) + "px"; m.style.top = (r.bottom + 4) + "px";
  document.body.appendChild(m);
  m.addEventListener("click", e => { const b = e.target.closest("button[data-dz]"); if (!b) return; m.remove(); movePanel(id, b.dataset.dz); const c = charts[id]; if (c) setTimeout(() => drawChart(c), 50); });
  const away = ev => { if (!m.isConnected){ document.removeEventListener("mousedown", away, true); return; } if (!m.contains(ev.target)) m.remove(); };
  setTimeout(() => document.addEventListener("mousedown", away, true), 0);
}

/* ---------- the chart studies: GAS + ATR, AIRSPACE, UNVISITED HIGHS / LOWS (your TradingView scripts, computed by TED
   from IBKR bars). STOCK charts only — never the option chart. Each one switches off in SETTINGS > Chart studies or the
   IND menu. Lines stop a few bars right of the last candle; their labels sit right after, levels too close to read
   share one row ("PDH 141.54 | PMH 141.40"), each name in its own colour. */
function stX(ctx, t0){
  // a time on this chart: the first candle at or after it (older than the screen = the left edge)
  const {bars, x0, cw} = ctx;
  if (t0 == null || !bars.length || t0 <= bars[0][0]) return 0;
  let lo = 0, hi = bars.length - 1;
  if (t0 > bars[hi][0]) return x0 + hi * cw + cw / 2;
  while (lo < hi){ const m = (lo + hi) >> 1; if (bars[m][0] < t0) lo = m + 1; else hi = m; }
  return x0 + lo * cw;
}
function studyLineList(S){ return [].concat(S.gas ? S.gas.lines || [] : [], S.air ? S.air.lines || [] : [], S.uv ? S.uv.lines || [] : []); }
function stDash(d){ return d === "dash" ? [6, 4] : d === "dot" ? [2, 3] : []; }
function studiesBack(ctx){
  const {g, S, bars, x0, cw, plotW, y, H} = ctx;
  if (!S || !bars.length) return;
  const xLast = x0 + (bars.length - 1) * cw + cw / 2, xs = Math.max(0, xLast - 8 * cw), xe = Math.min(plotW - 2, xLast + 4 * cw);
  const gs = S.gas;
  if (gs && gs.box){ const xb = stX(ctx, gs.box.t0), y1 = y(gs.box.hi), y2 = y(gs.box.lo);
    g.fillStyle = gs.box.c + "1f"; g.fillRect(xb, y1, plotW - xb, y2 - y1); g.strokeStyle = gs.box.c; g.lineWidth = 2; g.strokeRect(xb, y1, plotW - xb, y2 - y1); g.lineWidth = 1; }
  if (gs) for (const z of gs.zones || []){ const ya = y(z.a), yb = y(z.b); g.fillStyle = z.c; g.fillRect(xs, Math.min(ya, yb), Math.max(1, xe - xs), Math.abs(yb - ya)); }
}
function studiesFront(ctx){
  const {g, S, bars, x0, cw, plotW, y, lo, hi, lightScreen} = ctx;
  if (!S || !bars.length) return;
  const xLast = x0 + (bars.length - 1) * cw + cw / 2, xs = Math.max(0, xLast - 8 * cw), xe = Math.min(plotW - 2, xLast + 4 * cw);
  const lines = studyLineList(S);
  const rows = [], tags = [];
  for (const L of lines){
    if (L.p == null || L.p < lo || L.p > hi) continue;
    const yy = Math.round(y(L.p)) + .5;
    const from = L.stub ? Math.max(0, xLast) : (L.t0 != null ? stX(ctx, L.t0) : xs);
    g.strokeStyle = L.c; g.lineWidth = L.w || 1; g.setLineDash(stDash(L.d)); g.globalAlpha = L.fade ? 0.45 : 1;
    g.beginPath(); g.moveTo(from, yy); g.lineTo(xe, yy); g.stroke();
    g.globalAlpha = 1;
    if (L.l) rows.push({p: L.p, t: L.l, c: L.lc || L.c});
    // the price-scale tag, like the scripts' price-scale plots (not for whole numbers, box edges, today's high / low)
    if (L.g !== "uv" && L.c !== "rgba(158,158,158,.45)" && !/^(BOX EDGE|TIGHT|HIGH OF DAY|LOW OF DAY|2ND|1st|pivot)/.test(L.l || "")) tags.push([L.p, L.c]);
  }
  g.setLineDash([]); g.lineWidth = 1;
  // labels: highest first, levels closer than merge % of price share one row
  rows.sort((a, b) => b.p - a.p);
  const tol = (S.merge_pct || 0.15) / 100 * (ctx.last || (lo + hi) / 2);
  g.font = "bold 10px ui-monospace, Menlo, Consolas, monospace";
  const lx = xe + Math.max(2, cw);
  for (let i = 0; i < rows.length;){
    let j = i + 1, sum = rows[i].p;
    while (j < rows.length && rows[i].p - rows[j].p <= tol){ sum += rows[j].p; j++; }
    const grp = rows.slice(i, j), yy = y(sum / grp.length) + 3.5;
    const parts = grp.map((r, k) => ({t: (k ? "  |  " : "") + r.t, c: r.c}));
    const w = parts.reduce((s, q) => s + g.measureText(q.t).width, 0);
    if (lx + w > plotW - 3 && grp.length > 1){
      // too long for one row: each name on its own line, stacked from the shared price down
      grp.forEach((r, k) => { const tw = g.measureText(r.t).width, x = Math.max(2, Math.min(lx, plotW - tw - 3)), yk = yy + k * 12;
        g.fillStyle = r.c; g.fillText(r.t, x, yk); });
    } else {
      let x = Math.max(2, Math.min(lx, plotW - w - 3));
      for (const q of parts){ g.fillStyle = q.c; g.fillText(q.t, x, yy); x += g.measureText(q.t).width; }
    }
    i = j;
  }
  // price-scale tags in each line's colour (drawn by the caller after the clip is lifted)
  ctx.tags = tags;
  g.font = "11px ui-monospace, Menlo, Consolas, monospace";
}
function studiesTags(ctx){
  const {g, plotW, labelW, y, lo, hi} = ctx;
  if (!ctx.tags || !ctx.tags.length) return;
  g.font = "bold 10px ui-monospace, Menlo, Consolas, monospace";
  for (const [v, col] of ctx.tags.sort((a, b) => b[0] - a[0])){
    if (v < lo || v > hi) continue;
    const yy = y(v); g.fillStyle = col; g.fillRect(plotW + 1, yy - 6, labelW - 2, 12); g.fillStyle = "#ffffff"; g.fillText(v.toFixed(2), plotW + 4, yy + 4);
  }
  g.font = "11px ui-monospace, Menlo, Consolas, monospace";
}
// the chart's own MA values at the last candle (what you see drawn): the CONFLUENCE row reads these
function chartPack(cls){
  const out = [];
  for (const n of [5, 10, 20, 34, 50, 65, 89, 100, 150, 200]){ const s = emaSeries(cls, n); out.push([n + "E", s[s.length - 1]]); }
  for (const n of [5, 10, 20, 50, 100, 150, 200]){ const s = smaSeries(cls, n); out.push([n + "S", s[s.length - 1]]); }
  const bb = bbSeries(cls, 20, 2.0); out.push(["BbU", bb.up[bb.up.length - 1]]); out.push(["BbL", bb.dn[bb.dn.length - 1]]);
  return out;
}
function confluenceRow(p, S){
  const A = S.air, d = p.data; if (!A || !d) return null;
  const tf = store.get("tf." + (p.id || "chart"), 1), daily = typeof tf === "string";
  const pack = daily ? (A.pack60 || []) : (p.studyPack || []);
  const last = d.last;
  const match = yv => { let best = "", bd = A.tol + 1; for (const [nm, v] of pack){ if (v == null) continue; const dd = Math.abs(yv - v); if (dd <= A.tol && dd < bd){ bd = dd; best = nm; } } return best; };
  const line = (lv, side) => { const m = match(lv[0]); if (!m) return null;
    const dir = lv[0] > last ? "above" : lv[0] < last ? "below" : "at", atrN = A.atr ? Math.abs(last - lv[0]) / A.atr : null;
    return `confluence ${dir}, ${atrN == null ? "—" : (Math.round(atrN * 100) / 100)} ATR, Daily ${side} ${lv[2]} + ${daily ? "60m" : (tf === 60 ? "60" : tf)} ${m}`; };
  const b = A.bounce ? line(A.bounce, "Bounce") : null, r = A.reject ? line(A.reject, "Reject") : null;
  if (b && r) return {t: Math.abs(last - A.bounce[0]) <= Math.abs(last - A.reject[0]) ? b : r, bg: "rgba(69,39,160,.85)", fg: "#fff"};
  if (b) return {t: b, bg: "rgba(27,94,32,.8)", fg: "#fff"};
  if (r) return {t: r, bg: "rgba(74,20,140,.8)", fg: "#fff"};
  return {t: "confluence · none", bg: "rgba(38,50,56,.8)", fg: "#90A4AE"};
}
function nextStopRows(p, S){
  const N = S.gas && S.gas.next_stop, d = p.data; if (!N || !N.y_atr || !d || d.last == null) return [];
  const c = d.last, a = N.y_atr, lv = N.levels.slice();
  if (p.studyE65 != null) lv.push([p.studyE65, "EMA65 chart"]);
  lv.push([Math.ceil(c / N.step) * N.step, "whole"]); lv.push([Math.floor(c / N.step) * N.step, "whole"]);
  let up = null, dn = null;
  for (const [v, nm] of lv){ if (v > c + 0.10 * a && (up == null || v < up)) up = v; if (v < c - 0.10 * a && (dn == null || v > dn)) dn = v; }
  const names = best => { const hit = lv.filter(([v]) => best != null && Math.abs(v - best) <= 0.15 * a); return {n: hit.length, s: hit.slice(0, 3).map(x => x[1]).join(" + ") + (hit.length > 3 ? ` +${hit.length - 3} more` : "")}; };
  const bias = N.sma50 != null ? (c > N.sma50 ? " · ↑bias" : " · ↓bias") : "";
  const sand = (best, upSide) => { let k = 0; const band = 0.15 * a; for (const [h, l, cl] of N.last10){ if (upSide ? (Math.abs(h - best) <= band && cl < best) : (Math.abs(l - best) <= band && cl > best)) k++; }
    if (upSide && N.dH != null && Math.abs(N.dH - best) <= band && c < best) k++; if (!upSide && N.dL != null && Math.abs(N.dL - best) <= band && c > best) k++;
    return k >= 2 ? ` · LINE IN THE SAND (${k} touches held)` : ""; };
  const f = v => (Math.round(v * 100) / 100).toString(), out = [];
  if (up != null){ const nm = names(up), need = up - c, tank = N.left == null ? "" : N.left >= need ? ` · $${f(N.left)} in the tank` : ` · only $${f(N.left)} in the tank`;
    out.push({t: `SUPPLY (selling) ${f(up)} · ${nm.s} (${nm.n} ${nm.n > 1 ? "levels" : "level"}) · $${f(need)} gas needed${tank}${need < 0.25 * a ? " · THIN" : ""}${sand(up, true)}${bias}`, bg: "rgba(51,11,11,.9)", fg: "#ef5350"}); }
  if (dn != null){ const nm = names(dn), need = c - dn, tank = N.left == null ? "" : N.left >= need ? ` · $${f(N.left)} in the tank` : ` · only $${f(N.left)} in the tank`;
    out.push({t: `DEMAND (buying) ${f(dn)} · ${nm.s} (${nm.n} ${nm.n > 1 ? "levels" : "level"}) · $${f(need)} gas needed${tank}${need < 0.25 * a ? " · THIN" : ""}${sand(dn, false)}${bias}`, bg: "rgba(0,51,46,.9)", fg: "#26a69a"}); }
  return out;
}
function renderStudyBoards(p){
  const wrap = p.el && p.el.querySelector(".chart-wrap"); if (!wrap) return;
  const S = (!p.opt && p.data && p.data.studies) || null;
  const box = (cls, html, key) => { let b = wrap.querySelector(".stbd." + cls);
    if (!html){ if (b) b.remove(); return; }
    if (!b){ b = document.createElement("div"); b.className = "stbd " + cls; wrap.appendChild(b);
      b.addEventListener("click", e => {
        if (e.target.closest(".stmin")){ const k = b.dataset.key; store.set(k, !store.get(k, true)); b.dataset.h = ""; renderStudyBoards(p); }
        const hide = e.target.closest(".sthide");
        if (hide) post("/api/settings", {changes: {["studies." + hide.dataset.hide]: false}}).then(out => { toast(out.ok ? "Hidden · bring it back in the IND menu or SETTINGS > Chart studies" : "Not saved: " + (out.reason || ""), out.ok); poll(true); });
      });
      b.addEventListener("mousedown", e => e.stopPropagation()); }
    b.dataset.key = key;                     // every board starts small: unset = minimized
    if (b.dataset.h !== html){ b.dataset.h = html; b.innerHTML = html; } };
  const row = r => `<div class="r" style="background:${r.bg};color:${r.fg}">${esc(r.t)}</div>`;
  // AIRSPACE board (top right)
  if (S && S.air && S.air.board && S.air.board.length){
    const key = "stmin.air." + (p.id || "chart"), min = store.get(key, true);     // starts as the one-line strip
    const trs = S.air.board.map(r => {
      if (r === "CONFLUENCE"){ const c = confluenceRow(p, S); return c ? `<tr><td colspan="3" style="background:${c.bg};color:${c.fg}">${esc(c.t)}</td></tr>` : ""; }
      if (Array.isArray(r)) return `<tr>${r.map(([t, c, bg]) => `<td style="color:${c}${bg ? ";background:" + bg : ""}">${esc(t)}</td>`).join("")}</tr>`;
      return `<tr><td colspan="3" class="${r.big ? "big" : ""}" style="background:${r.bg};color:${r.fg}">${esc(r.t)}</td></tr>`; });
    const head = `<div class="sth">AIRSPACE${min && S.air.mini ? `<span class="mini">${esc(S.air.mini)}</span>` : ""}<b class="stmin" title="${min ? "open the whole board" : "minimize to one line + OVERALL"}">${min ? "▾" : "▴"}</b><b class="sthide" data-hide="air_board" title="hide the AIRSPACE board (the lines stay)">✕</b></div>`;
    box("air", head + `<div class="stbody"><table>${min ? trs[trs.length - 1] : trs.join("")}</table></div>`, key);
    // never over the data box (its LESS / MORE must stay clickable): sit just right of it when it is up top
    const ab = wrap.querySelector(".stbd.air"), dw = wrap.querySelector(".datawin");
    if (ab){ const dwOn = dw && dw.style.display !== "none" && dw.offsetTop < 60;
      const left = dwOn ? dw.offsetLeft + dw.offsetWidth + 6 : 6;
      if (ab.style.left !== left + "px") ab.style.left = left + "px"; }
  } else box("air", "");
  // GAS readout (bottom right) + NEXT STOP
  if (S && S.gas && ((S.gas.rows || []).length || S.gas.next_stop || S.gas.se)){
    const key = "stmin.gas." + (p.id || "chart"), min = store.get(key, true);     // starts with the tank lines only
    const rws = (S.gas.rows || []).concat(nextStopRows(p, S));
    const se = S.gas.se ? row(S.gas.se) : "";               // the second-entry status rides on top of the tank
    box("gas", `<div class="sth">GAS<b class="stmin" title="${min ? "day-after, continuation odds, next stop" : "just the tank"}">${min ? "▾" : "▴"}</b>${(S.gas.rows || []).length ? `<b class="sthide" data-hide="gas_readout" title="hide the GAS readout (the lines stay)">✕</b>` : ""}</div><div class="stbody">` + se + (min ? rws.slice(0, 2) : rws).map(row).join("") + `</div>`, key);
  } else box("gas", "");
}
