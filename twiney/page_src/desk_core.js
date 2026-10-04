
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
  const NEW_PANELS = {myalerts: "TL", eqflow: "BC", urgency: "BC", bigmoney: "BC", conviction: "BC", bigtape: "BX", options: "BC"};
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
    for (const id of ids){ const p = P[id]; if (p.el.parentElement !== body) body.appendChild(p.el); p.el.classList.toggle("on", LAY.active[z] === id); p.el.classList.remove("float"); p.el.style.cssText = ""; }
  }
  // floating
  for (const [id, f] of Object.entries(LAY.floats || {})){
    const p = P[id]; if (!p) continue;
    if (!p.el.querySelector(":scope > .ztabs")){ const t = document.createElement("div"); t.className = "ztabs"; p.el.prepend(t); }
    p.el.querySelector(":scope > .ztabs").innerHTML = `<span class="ztab on" draggable="true" data-p="${id}">${PANELS[id]}${SYMBOL_LINKED.has(id) ? ` <span class="sym">${esc(curSym || "")}</span>` : ""}<span class="ctl"><span data-act="dock" title="dock back">⧈</span><span data-act="hide" title="hide">✕</span></span></span>`;
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
function saveLayoutLocal(){ store.set("lay", LAY); store.set("layName", layoutName); }
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
    else if (act === "float") movePanel(id, "float");
    else if (act === "dock") movePanel(id, "TC");
    else if (act === "max"){ LAY.max = LAY.max === id ? null : id; applyLayout(); }
    return; }
  if (tab){ const z = tab.closest(".zone"); if (z){ LAY.active[z.dataset.zone] = tab.dataset.p; applyLayout(); } }
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
function layoutFromPreset(name){ const p = PRESETS[name]; const l = emptyLayout(); l.zones = JSON.parse(JSON.stringify(p.zones)); l.active = Object.assign({}, p.active); l.sizes = Object.assign(l.sizes, p.sizes); return normalize(l); }
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
  else if (act === "reset"){ useLayout("★ PS60 Execution"); }
  document.getElementById("layoutMenu").classList.remove("open");
});
async function loadLayouts(){
  try { const j = await (await fetch("/api/layouts", {cache: "no-store"})).json(); LAYOUTS = j.layouts || {}; PREFS = j.prefs || {};
    const last = j.last; const local = store.get("lay", null), localName = store.get("layName", null);
    if (local && localName === last){ LAY = normalize(local); layoutName = localName; }
    else if (last && last.startsWith("★ ") && PRESETS[last.slice(2)]){ LAY = layoutFromPreset(last.slice(2)); layoutName = last; }
    else if (last && LAYOUTS[last]){ LAY = normalize(LAYOUTS[last]); layoutName = last; }
  } catch (e) {}
  if (!LAY){ LAY = layoutFromPreset("PS60 Execution"); layoutName = "★ PS60 Execution"; }
  renderLayoutSel(); applyLayout();
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
  return `<h5>SCREEN</h5>
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
  const on = store.get("datawin", true) && p.data && p.dataBar;
  if (!on){ if (w) w.style.display = "none"; return; }
  if (!w){
    w = document.createElement("div"); w.className = "datawin"; wrap.appendChild(w);
    const pos = store.get("datawin.pos", null); if (pos){ w.style.left = pos[0] + "px"; w.style.top = pos[1] + "px"; w.style.bottom = "auto"; }
    w.addEventListener("click", e => { if (e.target.classList.contains("mn")){ store.set("datawin.min", !store.get("datawin.min", false)); w.dataset.h = ""; renderDataWin(p); } });
    w.addEventListener("mousedown", e => { if (e.target.classList.contains("mn")) return; e.stopPropagation(); e.preventDefault(); const r = w.getBoundingClientRect(), wr = wrap.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      const mv = ev => { w.style.left = Math.max(0, Math.min(wr.width - r.width, ev.clientX - wr.left - dx)) + "px"; w.style.top = Math.max(0, Math.min(wr.height - r.height, ev.clientY - wr.top - dy)) + "px"; w.style.bottom = "auto"; };
      const up = () => { window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up); store.set("datawin.pos", [parseInt(w.style.left), parseInt(w.style.top)]); };
      window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up); });
  }
  w.style.display = "";
  const b = p.dataBar, d = p.data, tf = p.dataTf, dt = new Date(b[0] * 1000);
  const ny = o => dt.toLocaleString("en-US", Object.assign({timeZone: "America/New_York"}, o));
  const lum = c => { const n = parseInt(c.slice(1), 16); return (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)); };
  const f = v => v == null ? "—" : (+v).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  const rows = (p.dataRows || []).map(([name, col, val]) => `<div class="r" style="background:${col};color:${lum(col) > 140 ? "#000" : "#fff"}"><span>${name}</span><span>${f(val)}</span></div>`).join("");
  const min = store.get("datawin.min", false);
  w.classList.toggle("min", min);
  const html = `<div class="ok"><span>OK</span><b class="mn" title="${min ? "show the indicator values too" : "keep Symbol through Close, hide the indicator values"}">${min ? "+" : "–"}</b></div>
    <div class="kv"><span>Symbol:</span><span>${esc(d.symbol)},${tf === "D" ? "D" : tf}</span></div>
    <div class="kv"><span>Date:</span><span>${ny({month: "2-digit", day: "2-digit", year: "2-digit"})}</span></div>
    <div class="kv"><span>Time:</span><span>${tf === "D" ? "00:00" : ny({hour: "2-digit", minute: "2-digit", hourCycle: "h23"})}</span></div>
    <div class="kv"><span>Price:</span><span>${f(p.dataPrice != null ? p.dataPrice : b[4])}</span></div>
    <div class="kv"><span>Open:</span><span>${f(b[1])}</span></div><div class="kv"><span>High:</span><span>${f(b[2])}</span></div>
    <div class="kv"><span>Low:</span><span>${f(b[3])}</span></div><div class="kv"><span>Close:</span><span>${f(b[4])}</span></div>
    ${rows}
    <div class="r vol"><span>Vol</span><span>${(b[5] || 0).toLocaleString("en-US")}</span></div>`;
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
