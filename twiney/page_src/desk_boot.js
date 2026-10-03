
/* ---------- command bar wiring */
document.getElementById("armBtn").addEventListener("click", async () => { const out = await post("/api/trade/arm", {on: !T().armed}); if (!out.ok) toast("ARM REFUSED · " + out.reason, false); else toast(out.armed ? "ARMED — orders will transmit" : "Disarmed", true); poll(true); });
document.getElementById("oneclick").addEventListener("change", e => post("/api/trade/oneclick", {on: e.target.checked}));
document.getElementById("bracket").addEventListener("change", e => post("/api/trade/bracket", {on: e.target.checked}));
document.getElementById("scale").addEventListener("change", e => post("/api/trade/scale", {on: e.target.checked}));
document.getElementById("soundBtn").addEventListener("click", () => { store.set("sound", !store.get("sound", true)); beep("buyer"); poll(true); });
document.getElementById("rotate").addEventListener("click", () => post("/api/autorotate", {on: !(state && state.auto_rotate)}));
document.getElementById("feedBody").addEventListener("click", async e => {
  const b = e.target.closest(".grade button"); if (!b) return;
  const key = b.parentElement.dataset.key, verdict = b.classList.contains("on") ? null : b.dataset.v;
  const out = await post("/api/grade", {key, verdict}); if (out.ok) toast(verdict ? "Graded " + verdict : "Grade cleared", true); poll(true);
});
document.addEventListener("click", e => { if (!e.target.closest(".menu")) document.querySelectorAll(".menu.open").forEach(m => m.classList.remove("open")); });
document.getElementById("panelsMenu").querySelector("button").addEventListener("click", e => { e.stopPropagation(); const m = document.getElementById("panelsMenu"), open = !m.classList.contains("open"); document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); m.classList.toggle("open", open); renderPanelsMenu(); });
document.getElementById("recBtn").addEventListener("click", deskRec);
document.getElementById("trainBtn").addEventListener("click", () => { const on = !store.get("training", false); store.set("training", on); const b = document.getElementById("trainBtn"); b.textContent = on ? "TRAIN ON" : "TRAIN OFF"; b.classList.toggle("on", on); P.book.last = null; P.reload.last = null; toast(on ? "Training: reload calls are hidden. REVEAL is in the RELOADS window." : "Training off: the desk calls reloads again", true); poll(true); });
{ const b = document.getElementById("trainBtn"); if (store.get("training", false)){ b.textContent = "TRAIN ON"; b.classList.add("on"); } }
document.addEventListener("click", e => { if (e.target.dataset.reveal){ window._revealUntil = (state ? state.now : 0) + 20; P.book.last = null; P.reload.last = null; toast("Revealed for 20 seconds", true); poll(true); } });
document.getElementById("markBtn").addEventListener("click", () => deskMark());
document.getElementById("shotBtn").addEventListener("click", deskShot);
// keyboard: configurable hotkeys first; then the few fixed ones (Esc closes things, / focuses the symbol box, J journal, 2 / L chart marks)
document.addEventListener("keydown", e => {
  if (e.key === "Escape"){ document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); if (e.target.matches("input, select, textarea")) e.target.blur(); }
  if (!document.getElementById("settings").hidden) return;     // typing in SETTINGS never fires hotkeys
  if (document.getElementById("modal") || document.querySelector("td.k.cap")) return;
  if (!e.target.matches("input, select, textarea") && chartTypeKey(e)) return;
  if (e.target.matches("input, select, textarea")) return;
  if (runHotkey(e)) return;
  // chart navigation keys: the chart under the mouse; with none hovered, the main chart (not while a replay is on, where
  // the arrows are the replay speed)
  const hot = Object.values(charts).find(x => x._hot && x.chartKey) || (!(state && state.replay) && charts.chart && charts.chart.chartKey && charts.chart.el.offsetParent !== null ? charts.chart : null);
  if (hot && hot.chartKey(e, hot === charts.chart)){ e.preventDefault(); return; }
  const c = charts.chart;
  if (e.key === "/"){ e.preventDefault(); document.getElementById("symIn").focus(); }
  else if (e.key === "j" || e.key === "J"){ e.preventDefault(); showPanel("journal"); const j = document.getElementById("jText"); if (j) j.focus(); }
  else if (e.key === "2" && c){ c.view.levelTool = "second_entry"; renderTools(c); toast("Click the chart where the 2nd entry is", true); }
  else if ((e.key === "l" || e.key === "L") && c){ c.view.levelTool = c.view.levelTool ? null : "extra"; renderTools(c); }
  else if (state && state.replay && (e.key === "ArrowLeft" || e.key === "ArrowRight")){ e.preventDefault(); const sp = state.replay.speed || 1; post("/api/replay", {speed: e.key === "ArrowRight" ? Math.min(50, sp * 2) : Math.max(1, sp / 2)}); }
  else if (e.key === "Escape"){ const m = document.getElementById("cmenu"); if (m) m.remove(); document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); }
});
window.addEventListener("resize", () => Object.values(charts).forEach(drawChart));
setInterval(() => { document.getElementById("stClock").textContent = nyT(Date.now() / 1000) + " ET"; }, 1000);
/* ---------- boot: panels, charts, layout, tabs, first poll */
mkChart("chart", false); mkChart("foot", true);
(async () => {
  await loadLayouts();
  renderRecent();
  if (PREFS.flowScope) post("/api/flow", {scope: PREFS.flowScope});
  if (PREFS.flowAlerts) post("/api/flow", {alerts: PREFS.flowAlerts});   // your WHOLE MARKET setting survives a restart
  post("/api/trade/risk", {dollars: riskDollars()});                    // the auto 2nd entry is sized from your risk $
  if (PREFS.tabs && PREFS.tabs.length){ TABS.list = PREFS.tabs.slice(); TABS.active = PREFS.active && TABS.list.includes(PREFS.active) ? PREFS.active : TABS.list[0]; curSym = TABS.active; renderTabs(); if (curSym) post("/api/play", {symbol: curSym, action: "focus"}); }
  poll();
})();
