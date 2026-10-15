
/* ---------- command bar wiring */
document.getElementById("armBtn").addEventListener("click", async () => {
  if (T().locked && !(T().mode === "LIVE" && T().allow_live)){ const u = await post("/api/trade/unlock", {});
    toast(!u.ok ? "Not unlocked: " + (u.reason || "") : u.can_trade ? "Loss lock lifted — now click ARM" : "Loss lock lifted, but TED can't trade yet: " + (u.why_not || ""), u.ok && u.can_trade); poll(true); return; }
  const out = await post("/api/trade/arm", {on: !T().armed}); if (!out.ok) toast("ARM REFUSED · " + out.reason, false); else toast(out.armed ? "ARMED — orders will transmit" : "Disarmed", true); poll(true); });
document.getElementById("practiceBtn").addEventListener("click", async () => {
  const b = document.getElementById("practiceBtn"); b.disabled = true; b.textContent = "STARTING…";
  toast("Starting the practice desk (its own tab, the practice market)…", true);
  const out = await post("/api/practice", {action: "start"});
  b.disabled = false; b.textContent = "PRACTICE";
  if (!out.ok){ toast("Practice desk: " + (out.reason || "did not start"), false); return; }
  // the page is reached through whatever host serves it (the SSH tunnel on the VPS): same host, the next port
  const url = location.protocol + "//" + location.hostname + ":" + out.port + "/";
  const w = window.open(url, "ted-practice"); if (!w) toast("Open " + url + " in a new tab (the browser blocked the pop-up)", false);
  else if (!out.ready) toast("The practice desk is still coming up: give the new tab a few seconds", true); });
/* the SIM / PAPER menu: where orders go AND where the data comes from. PAPER and SIM on LIVE data switch on the spot;
   the PRACTICE market and a RECORDED day restart TED on that feed (saved, so the next start opens there too) */
async function modeMenu(){
  let m = document.getElementById("modeMenu"); if (m){ m.remove(); return; }
  const ds = await fetch("/api/datasource", {cache: "no-store"}).then(r => r.json()).catch(() => ({}));
  const t = T(), cur = ds.source === "practice" || ds.source === "recorded" ? ds.source : (t.mode === "SIM" ? "live" : "paper");
  const recs = (ds.recordings || []).map(r => `<option value="${esc(r.name)}" ${r.name === ds.sim_recording ? "selected" : ""}>${esc(r.name)} · ${r.size_mb} MB</option>`).join("");
  m = document.createElement("div"); m.id = "modeMenu"; m.className = "pop modemenu";
  const opt = (k, title, sub) => `<button data-src="${k}" class="${cur === k ? "on" : ""}"><b>${title}</b><span>${sub}</span></button>`;
  m.innerHTML = `<div class="mmhd">ORDERS + DATA</div>`
    + opt("paper", "PAPER", "IBKR's data · orders to the IBKR paper account")
    + opt("live", "SIM · LIVE DATA", "IBKR's data · orders fill on this desk, nothing to IBKR")
    + opt("practice", "SIM · PRACTICE MARKET", "the built-in market, moving any hour · no IBKR · TED restarts on it")
    + opt("recorded", "SIM · RECORDED DAY", "a day you recorded, replayed in real time · TED restarts on it")
    + `<select id="mmRec" ${recs ? "" : "disabled"}>${recs || `<option>no recordings yet</option>`}</select>`
    + (ds.can_switch === false && (cur === "practice" || cur === "recorded") ? `<div class="mmnote">this desk was started on a fixed feed: close it and start TED normally to switch</div>` : "")
    + `<div class="mmnote">Flat first. PRACTICE and RECORDED stay on until you pick PAPER or SIM · LIVE DATA here.</div>`;
  document.body.appendChild(m);
  const b = document.getElementById("modeBtn").getBoundingClientRect(); m.style.left = Math.max(8, b.left) + "px"; m.style.top = (b.bottom + 4) + "px";
  m.addEventListener("click", async e => {
    const x = e.target.closest("button[data-src]"); if (!x) return;
    const src = x.dataset.src, held = ((state && state.account && state.account.positions) || []).length;
    if (src === cur && src !== "recorded"){ m.remove(); return; }
    if (held && !confirm("You hold a position. Switching leaves it where it is (PAPER positions stay at IBKR, SIM positions are dropped). Switch anyway?")) return;
    const needsRestart = src === "practice" || src === "recorded" || cur === "practice" || cur === "recorded";
    if (needsRestart){
      const rec = src === "recorded" ? document.getElementById("mmRec").value : null;
      const out = await post("/api/datasource", {source: src, recording: rec});
      m.remove();
      if (!out.ok){ toast("Not switched: " + (out.reason || ""), false); return; }
      toast(`Switching to ${x.querySelector("b").textContent}: TED restarts, the page comes back by itself`, true);
      setTimeout(() => location.reload(), 6000); return; }
    const out = await post("/api/trade/mode", {mode: src === "live" ? "SIM" : "PAPER", remember: true});
    m.remove();
    toast(out.ok ? (out.mode === "SIM" ? "SIM on LIVE DATA: orders stay on this desk. ARM to trade" : `${out.mode}: orders go to IBKR. ARM to trade`) : "Not switched: " + (out.reason || ""), out.ok); poll(true); });
}
document.getElementById("modeBtn").addEventListener("click", e => { e.stopPropagation(); modeMenu(); });
document.addEventListener("click", e => { const m = document.getElementById("modeMenu"); if (m && !e.target.closest("#modeMenu") && !e.target.closest("#modeBtn")) m.remove(); });
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
if (store.get("tf.chart2", null) == null) store.set("tf.chart2", 5);
if (store.get("tf.chart3", null) == null) store.set("tf.chart3", 15);
mkChart("chart2", false); mkChart("chart3", false);
(async () => {
  await loadLayouts();
  renderRecent();
  if (PREFS.flowScope) post("/api/flow", {scope: PREFS.flowScope});
  if (PREFS.flowAlerts) post("/api/flow", {alerts: PREFS.flowAlerts});   // your WHOLE MARKET setting survives a restart
  post("/api/trade/risk", {dollars: riskDollars()});                    // the auto 2nd entry is sized from your risk $
  if (PREFS.tabs && PREFS.tabs.length){ TABS.list = PREFS.tabs.slice(); TABS.active = PREFS.active && TABS.list.includes(PREFS.active) ? PREFS.active : TABS.list[0]; curSym = TABS.active; renderTabs(); if (curSym) post("/api/play", {symbol: curSym, action: "focus"}); }
  poll();
})();
