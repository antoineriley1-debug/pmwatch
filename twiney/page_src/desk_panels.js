
/* ===================== panel renderers ===================== */
const NA = "—";
const pctFmt = (v) => v == null ? NA : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";

function renderQuote(d){
  const el = P.chart.el.querySelector(".qs");
  if (!d){ el.innerHTML = `<span class="sym">${esc(curSym || "")}</span><span class="dim">${curSym ? "NO DATA" : "NO SYMBOL · Ctrl+L"}</span>`; return; }
  const day = d.day || {}, pl = d.play, g = d.ps60;
  const chg = d.last && day.prev_close ? d.last - day.prev_close : null;
  const tfNow = store.get("tf.chart", 1);
  const TFP = [["1", 1], ["5", 5], ["1H", 60], ["4H", 240], ["1D", "D"], ["1W", "W"], ["1M", "M"], ["1Y", "12M"]];
  const html = `<span class="sym">${esc(d.symbol)}</span><span class="tfp" title="timeframe · or click the chart and type: 5, 1H, 1D, 1W, 5M, or a ticker">${TFP.map(([l, v]) => `<button data-tfp="${v}" class="${String(tfNow) === String(v) ? "on" : ""}">${l}</button>`).join("")}</span><span class="tfn">${tfLabel(tfNow)}</span>
    <span>LAST <b style="color:var(--gold)">${px(d.last)}</b>${chg != null ? ` <span class="${chg >= 0 ? "buy" : "sell"}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)} ${(chg / day.prev_close * 100).toFixed(2)}%</span>` : ""}</span>
    <span><span class="buy">${px(d.bid)}</span><span class="dim">${day.bid_size ? "×" + kfmt(day.bid_size) : ""}</span> / <span class="sell">${px(d.ask)}</span><span class="dim">${day.ask_size ? "×" + kfmt(day.ask_size) : ""}</span></span>
    <span class="dim">O ${px(day.open)} H ${px(day.high)} L ${px(day.low)} V ${day.volume ? kfmt(day.volume) : NA}</span>
    <span class="dim">PIVOT <b style="color:#dbe3ee">${px(pl.trigger)}</b> 2ND <b style="color:var(--cyan)">${px(pl.second_entry)}</b> TGT <b style="color:var(--buy)">${px(pl.target)}</b> STOP <b style="color:var(--sell)">${px(pl.stop)}</b></span>
    ${g ? `<span class="p-ps60" style="margin:0;height:auto;overflow:visible"><span class="g ${g.grade}" title="${esc(g.why)}">${g.grade}</span></span>` : ""}
    <span class="dim">${esc(d.health.status)}${d.pinned ? " · PINNED" : ""}${(d.book && (d.book.bids.length || d.book.asks.length)) ? "" : " · no depth"}</span>`;
  const scr = store.get("screen", "white");
  const html2 = html + `<span class="spacer"></span><select class="qscreen" data-qscreen="1" title="chart screen">${[["blue", "BLUE"], ["white", "WHITE"], ["pink", "PINK"], ["custom", "CUSTOM"], ["desk", "DESK"]].map(([v, l]) => `<option value="${v}" ${scr === v ? "selected" : ""}>${l}</option>`).join("")}</select><button class="qtools ${store.get("tools", false) ? "on" : ""}" data-tools="1" title="show / hide the chart toolbar">TOOLS</button>`;
  const html3 = html2 + `<button class="qgear" data-gear="1" title="chart settings">⚙</button>`;
  if (el.dataset.h !== html3){ el.dataset.h = html3; el.innerHTML = html3; }
}
/* ⚙ chart settings, TradingView style: colours, lines and what the chart draws. Saved per browser, applied at once */
const CS_DEF = [
  ["SYMBOL", [
    ["color", "upCol", "Up candle", ""], ["color", "dnCol", "Down candle", ""], ["color", "wickCol", "Wick (light screens)", ""],
    ["check", "wicks", "Wicks", true], ["check", "borders", "Body borders", true],
    ["range", "body", "Body width %", 76, 20, 95, true], ["range", "wick", "Wick width px", 3, 1, 8, true]]],
  ["STATUS LINE", [["check", "datawin", "Data window (OHLC + indicators)", true, true]]],
  ["SCALES & LINES", [
    ["check", "lastLine", "Last price line", true], ["select", "lastStyle", "Last price line style", "dotted", ["dotted", "dashed", "solid"]],
    ["check", "lastLabel", "Last price label", true], ["check", "countdown", "Bar close countdown", true]]],
  ["CANVAS", [
    ["color", "bgCol", "Background (light screens)", ""], ["check", "gridH", "Horizontal grid lines", true],
    ["select", "cross", "Crosshair", "auto", ["auto", "solid", "dashed", "dotted", "off"]], ["color", "crossCol", "Crosshair colour", ""],
    ["check", "crossSync", "Crosshair synced on every chart (same time)", true]]],
  ["TRADING", [["check", "levels", "Your levels (pivot, 2nd entry, stop, target)", true], ["check", "orders", "Working order lines", true],
    ["check", "chip", "2nd entry order chip", true], ["check", "bigmoney", "Big option money (30 days) at its strikes", false],
    ["check", "trapped", "Trapped crowd's exit (their average price)", false], ["check", "trapband", "Trapped buyers / sellers band (last 10 min)", false],
    ["check", "stopRisk", "Stop $ label: what you lose if the stop is hit (shares or contracts)", true], ["range", "stopRiskPx", "Stop $ label size (px)", 10, 8, 16, true],
    ["range", "flyMax", "Prints that fly to T&S at once (big + reload fills)", 4, 1, 12, true]]],
  ["INDICATORS", [["check", "vwap", "VWAP", true, true], ["check", "mas", "Moving averages", true, true], ["check", "matags", "MA price tags", true, true],
    ["check", "bb", "Bollinger bands", true, true]]],
  ["LEVEL II CANDLE", [["check", "candleFly", "The ladder's candle flies to the chart when it closes (CANDLE mode, 1m / 5m)", true, true]]],
];
function csKey(f){ return f[0] === "range" ? f[1] : f[4] === true || (f[0] === "check" && f.length > 4 && f[4]) ? f[1] : "cs." + f[1]; }
function csHTML(){
  return `<div class="cs-hd"><b>CHART SETTINGS</b><span><button data-cs-reset="1" title="every chart setting back to its default">RESET</button><button data-cs-close="1">✕</button></span></div>` +
    CS_DEF.map(([sec, rows]) => `<h5>${sec}</h5>` + rows.map(f => {
      const key = csKey(f), v = store.get(key, f[3]);
      const inp = f[0] === "check" ? `<input type="checkbox" data-csk="${key}" ${v ? "checked" : ""}>`
        : f[0] === "color" ? `<input type="color" data-csk="${key}" value="${v || "#888888"}"> <button data-cs-clear="${key}" title="back to the screen's colour" ${v ? "" : "disabled"}>auto</button>`
        : f[0] === "range" ? `<input type="range" data-csk="${key}" min="${f[4]}" max="${f[5]}" value="${v}"> <span class="dim">${v}</span>`
        : `<select data-csk="${key}">${f[4].map(o => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
      return `<label class="cs-row"><span>${f[2]}</span><span>${inp}</span></label>`; }).join("")).join("");
}
function csRedraw(){ Object.values(charts).forEach(c => { try { drawChart(c); } catch (e) {} }); }
function csOpen(btn){
  let pop = document.getElementById("csPop");
  if (pop){ pop.remove(); return; }
  pop = document.createElement("div"); pop.id = "csPop"; pop.className = "pop cs-pop"; pop.innerHTML = csHTML();
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.top = Math.min(r.bottom + 4, window.innerHeight - 40) + "px";
  pop.style.left = Math.max(8, Math.min(r.right - pop.offsetWidth, window.innerWidth - pop.offsetWidth - 8)) + "px";
  const set = el => { const k = el.dataset.csk, v = el.type === "checkbox" ? el.checked : el.type === "range" ? +el.value : el.value;
    store.set(k, v); if (el.type === "range") el.nextElementSibling.textContent = v;
    if (el.type === "color"){ const b = el.parentElement.querySelector("[data-cs-clear]"); if (b) b.disabled = false; }
    csRedraw(); };
  pop.addEventListener("input", e => { if (e.target.dataset.csk) set(e.target); });
  pop.addEventListener("change", e => { if (e.target.dataset.csk) set(e.target); });
  pop.addEventListener("click", e => {
    if (e.target.dataset.csClose){ pop.remove(); return; }
    if (e.target.dataset.csClear){ store.set(e.target.dataset.csClear, ""); pop.innerHTML = csHTML(); csRedraw(); return; }
    if (e.target.dataset.csReset){ CS_DEF.forEach(([, rows]) => rows.forEach(f => store.set(csKey(f), f[3]))); pop.innerHTML = csHTML(); csRedraw(); }
  });
  const away = ev => { if (!pop.isConnected){ document.removeEventListener("mousedown", away, true); return; } if (!pop.contains(ev.target) && !ev.target.dataset.gear) pop.remove(); };
  setTimeout(() => document.addEventListener("mousedown", away, true), 0);
}
P.chart.el.querySelector(".qs").addEventListener("click", e => { if (e.target.dataset.gear) csOpen(e.target); });
let bookUserScroll = 0, bookDragging = false, bookHold = null;   // bookHold: the row you pressed {side, px, sym}
P.chart.el.querySelector(".qs").addEventListener("change", e => { if (!e.target.dataset.qscreen) return; store.set("screen", e.target.value); P.chart.last = null; drawChart(charts.chart); renderTools(charts.chart); });
function setChartTf(tf){ store.set("tf.chart", tf); const c = charts.chart; c.view.offset = restOffset(); c.view.follow = true; c.view.autoY = null; c.view.yLo = c.view.yHi = null; if (typeof tf === "string" && c.view.cw < 6) c.view.cw = 8; drawChart(c); renderTools(c); P.chart.last = null; renderQuote(curData()); }
P.chart.el.querySelector(".qs").addEventListener("click", e => {
  if (e.target.dataset.tfp){ const v = e.target.dataset.tfp; setChartTf(/^\d+$/.test(v) ? +v : v); return; }
  if (!e.target.dataset.tools) return; const on = !store.get("tools", false); store.set("tools", on); P.chart.el.classList.toggle("tools-on", on); e.target.classList.toggle("on", on); });
P.chart.el.classList.toggle("tools-on", store.get("tools", false));
/* the chart crosshair lights up the same price on the ladder */
let hoverPx = null;
function ladderHighlight(pr){
  hoverPx = pr;
  const tbl = P.book.pc.querySelector("table.lad"); if (!tbl) return;
  let best = null, bestD = Infinity;
  for (const tr of tbl.rows){ const p = +tr.dataset.price; if (!(p > 0)) continue; const dd = Math.abs(p - (pr == null ? -1e9 : pr)); if (dd < bestD){ bestD = dd; best = tr; } }
  const tick = best ? (+best.dataset.price >= 1 ? 0.01 : 0.0001) : 0;
  tbl.querySelectorAll("tr.xh").forEach(tr => { if (tr !== best || pr == null) tr.classList.remove("xh"); });
  if (best && pr != null && bestD <= tick * 0.51 && !best.classList.contains("xh")) best.classList.add("xh");
}
/* type on the chart, TradingView style: 5 → 5 min · 1H · 1D · 1W · 5M (months) · TSLA / NVIDIA → that chart */
const NAMES = {NVIDIA: "NVDA", TESLA: "TSLA", APPLE: "AAPL", AMAZON: "AMZN", MICROSOFT: "MSFT", GOOGLE: "GOOGL", ALPHABET: "GOOGL", META: "META", FACEBOOK: "META",
  NETFLIX: "NFLX", PALANTIR: "PLTR", COINBASE: "COIN", SOFI: "SOFI", AMD: "AMD", INTEL: "INTC", BOEING: "BA", DISNEY: "DIS", NIKE: "NKE", UBER: "UBER",
  SHOPIFY: "SHOP", SNOWFLAKE: "SNOW", MICRON: "MU", BROADCOM: "AVGO", ORACLE: "ORCL", SALESFORCE: "CRM", PAYPAL: "PYPL", VISA: "V", WALMART: "WMT",
  COSTCO: "COST", EXXON: "XOM", CHEVRON: "CVX", JPMORGAN: "JPM", GOLDMAN: "GS", BERKSHIRE: "BRK B", QQQ: "QQQ", SPY: "SPY", NASDAQ: "QQQ", SPX: "SPY"};
function parseTyped(text){
  const t = text.trim().toUpperCase().replace(/\s+/g, "");
  let m = /^(\d+)(MIN|M|H|HR|D|W|MO)?$/.exec(t);
  if (m){
    const n = +m[1], u = m[2] || "MIN";
    if (!n) return null;
    if (u === "MIN") return {tf: n};
    if (u === "H" || u === "HR") return {tf: n * 60};
    if (u === "D") return {tf: n === 1 ? "D" : n + "D"};
    if (u === "W") return {tf: n === 1 ? "W" : n + "W"};
    return {tf: n === 1 ? "M" : n + "M"};                 // M = months, like TradingView
  }
  if (/^[A-Z][A-Z .]{0,9}$/.test(t)) return {symbol: NAMES[t] || t};
  return null;
}
P.chart.el.addEventListener("mousedown", () => { P.chart.el.classList.add("typing"); }, true);
document.addEventListener("mousedown", e => { if (!P.chart.el.contains(e.target)) P.chart.el.classList.remove("typing"); }, true);
function openTyper(first){
  const wrap = P.chart.el.querySelector(".chart-wrap"); if (!wrap) return;
  let box = wrap.querySelector(".typer");
  if (!box){ box = document.createElement("div"); box.className = "typer"; box.innerHTML = `<input spellcheck="false" autocomplete="off"><span class="hint">Enter · 5 = 5 min · 1H · 1D · 1W · 5M = 5 months · or a ticker</span>`; wrap.appendChild(box);
    const inp = box.querySelector("input");
    inp.addEventListener("keydown", e => {
      e.stopPropagation();
      if (e.key === "Escape"){ box.remove(); return; }
      if (e.key !== "Enter") return;
      const r = parseTyped(inp.value); box.remove();
      if (!r){ toast("Type a timeframe (5, 1H, 1D, 5M) or a ticker", false); return; }
      if (r.tf != null){ setChartTf(r.tf); toast("Chart: " + tfLabel(r.tf), true); }
      else openTab(r.symbol, true);
    });
    inp.addEventListener("blur", () => setTimeout(() => box.remove(), 150));
  }
  const inp = box.querySelector("input"); inp.value = first; inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length);
}
function chartTypeKey(e){
  // the mouse is over the chart and a plain letter or digit was pressed: that is typing, not a hotkey
  if (e.ctrlKey || e.metaKey || e.altKey || e.key.length !== 1 || !/[a-zA-Z0-9]/.test(e.key)) return false;
  const c = charts.chart; if (!c || c.el.offsetParent === null) return false;
  // 2 is the 2nd-entry mark: it is never eaten as the first key of a typed timeframe (type 2 again inside the box)
  if (e.key === "2" && !c.el.classList.contains("typing")) return false;
  if (!(c.el.matches(":hover") || c.view.cross || c.el.classList.contains("typing"))) return false;
  e.preventDefault(); openTyper(e.key); return true;
}
/* BREAK TRAPS: a small floating box (drag it by its title; − folds it, ✕ hides it until the next trap). When price
   takes out a key level and comes back, how many got caught, on which side, their average (where they get out), how
   far underwater, and what was resting at the level when it broke. The ticker you are on. */
const BTX = {hidden: false, lastKey: ""};
function btBox(){
  let w = document.getElementById("btrap"); if (w) return w;
  w = document.createElement("div"); w.id = "btrap"; w.className = "btrap"; w.hidden = true;
  w.innerHTML = `<div class="bth" title="drag to move"><b>TRAPS</b><span class="bts"></span><button class="btmin" title="fold">−</button><button class="btx" title="hide until the next trap">✕</button></div><div class="btb"></div>`;
  document.body.appendChild(w);
  const pos = store.get("btrap.pos", null); if (pos){ w.style.left = pos[0] + "px"; w.style.top = pos[1] + "px"; }
  if (store.get("btrap.min", false)) w.classList.add("min");
  const hd = w.querySelector(".bth");
  hd.addEventListener("mousedown", e => { if (e.target.closest("button")) return; e.preventDefault();
    const r = w.getBoundingClientRect(), x0 = e.clientX, y0 = e.clientY;
    const mv = ev => { const l = Math.max(0, Math.min(innerWidth - r.width, r.left + ev.clientX - x0)), tp = Math.max(0, Math.min(innerHeight - 24, r.top + ev.clientY - y0));
      w.style.left = l + "px"; w.style.top = tp + "px"; w.style.right = "auto"; w.style.bottom = "auto"; };
    const up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); store.set("btrap.pos", [parseInt(w.style.left) || 0, parseInt(w.style.top) || 0]); };
    addEventListener("mousemove", mv); addEventListener("mouseup", up); });
  w.querySelector(".btmin").addEventListener("click", () => { w.classList.toggle("min"); store.set("btrap.min", w.classList.contains("min")); });
  w.querySelector(".btx").addEventListener("click", () => { BTX.hidden = true; w.hidden = true; });
  return w;
}
function renderBreakTraps(d){
  const list = (d && d.breaktraps) || [], w = btBox();
  // a NEW trap (or a new break) on this ticker brings the box back even after ✕
  const key = d ? d.symbol + "|" + list.filter(b => b.state === "TRAPPED").map(b => b.name + b.level).join(",") : "";
  if (key !== BTX.lastKey){ if (list.some(b => b.state === "TRAPPED")) BTX.hidden = false; BTX.lastKey = key; }
  if (!list.length || BTX.hidden){ if (!w.hidden) w.hidden = true; return; }
  const last = d.last != null ? +d.last : null;
  const st = {BROKE: ["BROKE", "brk"], TRAPPED: ["TRAPPED", "trp"], "AT EXIT": ["AT THEIR EXIT", "ext"], RECLAIMED: ["BREAK HELD", "hld"]};
  const ago = s => s == null ? "" : s < 60 ? s + "s" : Math.round(s / 60) + "m";
  const h = list.map(b => {
    const [word, cls] = st[b.state] || [b.state, ""], who = b.up ? "LONGS" : "SHORTS", act = b.up ? "buy" : "sell";
    const head = `<div class="btl ${cls} ${b.up ? "up" : "dn"}"><b class="btn" title="${esc(b.name)}">${esc(String(b.name).replace(/PREMARKET /g, "PM ").replace(/PRIOR DAY /g, "PD ").replace(/AFTER-HOURS /g, "AH ").replace(/ OF DAY/g, " OF DAY"))}</b><span class="btp">${px(b.level)} ${b.up ? "▲" : "▼"}</span><span class="btw">${b.state === "TRAPPED" || b.state === "AT EXIT" ? word + " " + who : word}</span><i title="${b.trap_age != null ? "trapped " + ago(b.trap_age) + " ago, broke " + ago(b.age) + " ago" : "broke " + ago(b.age) + " ago"}">${b.trap_age != null ? ago(b.trap_age) : ago(b.age)}</i></div>`;
    const caught = b.shares ? `<div class="btr"><span><b>${(b.prints || 0).toLocaleString()}</b> ${act} orders</span><span><b>${kfmt(b.shares)}</b> sh</span><span>${usdK(b.usd)}</span><span>avg <b>${b.avg != null ? px(b.avg) : "—"}</b></span></div>` : `<div class="btr dim">no ${act} orders at it yet</div>`;
    const rest = b.resting ? `<div class="btr dim" title="shares showing on the ${b.up ? "offer" : "bid"} at ${px(b.level)} when price broke through it">${kfmt(b.resting)} sh resting on the ${b.up ? "offer" : "bid"} at the break</div>` : "";
    const now = (b.state === "TRAPPED" || b.state === "AT EXIT") && b.under != null
      ? `<div class="btr ${b.under > 0 ? "uw" : ""}"><span>now ${last != null ? px(last) : ""}</span>${b.under > 0 ? `<span><b>${(b.under * 100).toFixed(0)}¢ under</b></span><span>${usdK(b.at_risk)} at risk</span>` : "<span>back at even</span>"}</div><div class="btr out">they get out at <b>${px(b.avg)}</b></div>`
      : b.state === "RECLAIMED" ? `<div class="btr dim">new ${b.up ? "high" : "low"} past ${px(b.extreme)}: nobody trapped</div>`
      : `<div class="btr dim">trapped if price comes back ${b.up ? "under" : "over"} ${px(b.trap_at)} without a new ${b.up ? "high" : "low"} (now ${b.up ? "high" : "low"} ${px(b.extreme)})</div>`;
    return `<div class="bti">${head}${caught}${rest}${now}</div>`; }).join("");
  const sym = `${esc(d.symbol)}`;
  if (w.dataset.h !== sym + h){ w.dataset.h = sym + h; w.querySelector(".bts").textContent = d.symbol; w.querySelector(".btb").innerHTML = h; }
  if (w.hidden) w.hidden = false;
}
/* the candle being built right now (and the one before it), from the 1-minute bars, on the chart's timeframe when
   it is 1 or 5 minutes (else 5): for the CANDLE ladder */
function ladderCandleTf(){ const c = typeof charts !== "undefined" && charts.chart, tf = c ? store.get("tf." + c.id, 1) : 0; return +tf === 1 || +tf === 5 ? +tf : 5; }
function ladderCandle(d){
  const bars = d.bars || [], last = d.last != null ? +d.last : null, tfm = ladderCandleTf(), span = tfm * 60;
  if (!bars.length || last == null || typeof bucketFn !== "function") return null;
  const now = (state && state.now) || Date.now() / 1000, bk = bucketFn(tfm), cur = bk(now), prev = cur - span;
  const inb = bars.filter(b => b[0] >= cur && b[0] < cur + span), pb = bars.filter(b => b[0] >= prev && b[0] < cur);
  const agg = rows => rows.length ? {open: +rows[0][1], high: Math.max(...rows.map(b => +b[2])), low: Math.min(...rows.map(b => +b[3])), close: +rows[rows.length - 1][4]} : null;
  const c = agg(inb) || {open: last, high: last, low: last, close: last};
  c.high = Math.max(c.high, last); c.low = Math.min(c.low, last); c.last = last; c.prev = agg(pb); c.tf = tfm; c.t0 = cur;
  return c;
}
/* THE HAND-OFF: when the ladder's candle closes, the same candle (body, wick, open, close) lifts off the ladder, flies
   across the screen with a glow and lands exactly on its slot on the chart, where the chart's own candle takes over.
   The ladder flashes the close row and starts the next candle. Only when the chart shows that symbol on that
   timeframe (1m or 5m); never in the way of a click. SETTINGS / ⚙ on the ladder: candle_fly */
const CFLY = {last: {}};
function candleHandoff(wrap, d, c){
  if (!c || !d) return;
  const key = d.symbol, prev = CFLY.last[key];
  CFLY.last[key] = {t0: c.t0, open: c.open, high: c.high, low: c.low, close: c.last, tf: c.tf};
  if (!prev || prev.t0 === c.t0 || prev.tf !== c.tf || !store.get("candleFly", true)) return;
  const closed = prev;                                           // the candle that just finished
  // the row where it closed flashes
  const rowOf = p => wrap.querySelector(`tr[data-price="${(+p).toFixed(2)}"]`) || [...wrap.querySelectorAll("tr[data-price]")].find(r => Math.abs(+r.dataset.price - p) < 0.0051);
  const rc = rowOf(closed.close); if (rc){ rc.classList.add("cclose"); setTimeout(() => rc.classList.remove("cclose"), 1400); }
  const ch = typeof charts !== "undefined" && charts.chart, g = ch && ch.view && ch.view.geom;
  if (!g || g.sym !== key || +g.tf !== closed.tf || !ch.canvas.offsetParent) return;
  const rh = rowOf(closed.high), rl = rowOf(closed.low), ro = rowOf(closed.open);
  const col = wrap.querySelector("td.cdl"); if (!col || !(rh || rl)) return;
  const a = (rh || rl).getBoundingClientRect(), b = (rl || rh).getBoundingClientRect(), cb = col.getBoundingClientRect();
  const top = Math.min(a.top, b.top), bot = Math.max(a.bottom, b.bottom);
  const up = closed.close >= closed.open, colr = up ? "#1fb86a" : "#e8404f";
  // where it lands: the chart's slot for that bucket (or the newest candle)
  const cr = ch.canvas.getBoundingClientRect();
  const kIdx = Math.max(0, g.keys.indexOf(closed.t0) >= 0 ? g.keys.indexOf(closed.t0) : g.n - 1);
  const yC = v => cr.top + 8 + (g.hi - v) / (g.hi - g.lo) * (g.plotH - 8);
  const xC = cr.left + g.x0 + kIdx * g.cw + g.cw / 2;
  const dTop = yC(closed.high), dBot = yC(closed.low), dH = Math.max(3, dBot - dTop), dW = Math.max(3, g.cw * 0.76);
  const bodyTop = (closed.high - Math.max(closed.open, closed.close)) / Math.max(1e-9, closed.high - closed.low), bodyBot = (Math.min(closed.open, closed.close) - closed.low) / Math.max(1e-9, closed.high - closed.low);
  const el = document.createElement("div");
  el.className = "cfly " + (up ? "u" : "d");
  el.style.cssText = `left:${cb.left + 2}px;top:${top}px;width:${Math.max(10, cb.width - 4)}px;height:${Math.max(6, bot - top)}px;--cc:${colr}`;
  el.innerHTML = `<i class="wk"></i><i class="bd" style="top:${(bodyTop * 100).toFixed(1)}%;bottom:${(bodyBot * 100).toFixed(1)}%"></i><b class="o">O ${px(closed.open)}</b><b class="c">C ${px(closed.close)}</b>`;
  document.body.appendChild(el);
  const ring = document.createElement("div"); ring.className = "cland"; ring.style.cssText = `left:${xC - 14}px;top:${dTop + dH / 2 - 14}px;--cc:${colr}`;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    el.classList.add("go");
    el.style.left = (xC - dW / 2) + "px"; el.style.top = dTop + "px"; el.style.width = dW + "px"; el.style.height = dH + "px";
  }));
  setTimeout(() => { document.body.appendChild(ring); el.classList.add("land"); }, 640);
  setTimeout(() => { el.remove(); ring.remove(); }, 1500);
}
function renderBook(d){
  try { renderBreakTraps(d); } catch (e) {}
  const wrap = P.book.pc.querySelector(".ladder-wrap");
  renderLadStat(d, state); renderLadQty(state);
  autoPair(); renderContractL2(); renderSwitchStrips(); if (contractMode("book")) return;
  if (!d){ if (P.book.last !== "-"){ P.book.last = "-"; wrap.innerHTML = `<div class="dim" style="padding:8px">${NA}</div>`; } return; }
  if (bookDragging || bookHold) return;       // never redraw rows under a pressed mouse button
  const bi = document.getElementById("bigIn"), L = d.ladder || {};
  if (bi && document.activeElement !== bi && L.big_shares != null && bi.dataset.sym + ":" + L.big_shares !== d.symbol + ":" + L.big_shares){ bi.value = Math.round(L.big_shares); bi.dataset.sym = d.symbol; }
  const hint = document.getElementById("bigHint"); if (hint){ const txt = L.big_shares != null ? (L.big_default ? "" : d.symbol + " · ") + "huge ≥" + kfmt(L.huge_shares) : ""; if (hint.textContent !== txt) hint.textContent = txt; }
  if (d.ladder){ d.ladder.pace = d.tape && d.tape.pace; d.ladder.story = d.story; d.ladder.refs = d.refs;
    d.ladder.seq = d.seq; d.ladder.pps = d.tape && d.tape.speed ? d.tape.speed.pps : null; }   // the BASKET ladder's sequence and fast mode    // PACE OF TAPE and the PS60 STORY line ride on top of the ladder
  window._fundLv = {}; for (const x of ((d.inst && d.inst.levels) || [])) window._fundLv[(+x.price).toFixed(2) + (x.side === "bid" ? "b" : "s")] = x;   // FUND score by level
  window._darkLv = {}; for (const x of ((d.dark && d.dark.levels) || [])) if (x.usd >= 200000) window._darkLv[(+x.price).toFixed(2)] = x;   // dark $ by price for the ladder
  if (d.ladder && store.get("ladMode", "clean") === "candle") d.ladder.candle = ladderCandle(d);   // the 5-minute candle on the rows
  const html = ladderHTML(training() ? Object.assign({}, d.ladder, {rows: d.ladder.rows.map(r => Object.assign({}, r, {bid_state: null, ask_state: null, bid_refills: 0, ask_refills: 0, bid_verdict: null, ask_verdict: null}))}) : d.ladder);
  if (P.book.last === html){ try { basketFx(wrap, d); } catch (e) {} if (d.ladder && d.ladder.candle) try { candleHandoff(wrap, d, d.ladder.candle); } catch (e) {} return; }   // nothing redrawn: the basket clock still ticks
  P.book.last = html;
  const keep = wrap.scrollTop;
  wrap.innerHTML = html; applyLadCols(wrap.querySelector("table")); makeColsResizable(wrap.querySelector("table")); if (hoverPx != null) ladderHighlight(hoverPx);
  eatMarks(wrap, d); avgRow(wrap, d); fitLadderRows(wrap);
  if (d.ladder && d.ladder.candle) try { candleHandoff(wrap, d, d.ladder.candle); } catch (e) {}
  try { basketFx(wrap, d); } catch (e) {}                 // the BASKET drop: cosmetic, never stops the ladder
  const cur = wrap.querySelector("tr.lastpx") || wrap.querySelector("tr.best-ask");
  // a STILL ladder: the view holds where it is while price trades inside its middle; it re-centres only when price
  // gets into the top or bottom fifth (or a new symbol opens). Re-centring on every print made every row jump
  const autoCenter = store.get("ladcols", {}).center !== false;
  wrap.scrollTop = keep;
  if (cur && autoCenter && Date.now() - bookUserScroll > 8000){
    const h = wrap.clientHeight, y = cur.offsetTop - wrap.scrollTop, fresh = wrap.dataset.csym !== d.symbol;
    if (fresh || y < h * 0.2 || y > h * 0.8) wrap.scrollTop = cur.offsetTop - h / 2;
    wrap.dataset.csym = d.symbol;
  }
  // a fresh RELOAD call flashes its row so the eye lands on it
  const fresh = (state.alerts || []).filter(a => a.symbol === d.symbol && /^RELOAD/.test(a.label) && state.now - a.t < 6);
  for (const a of fresh){ const row = wrap.querySelector(`tr[data-price="${a.price}"]`); if (row && !row.classList.contains("flash")) row.classList.add("flash"); }
  rlBanner(wrap, d); renderRlBasket(d);
}
/* OPTION CHAIN: expiries and strikes from IBKR (the practice desk makes its own), quotes and Greeks for the strikes
   around the spot, BUY / SELL to open from the row. Polled on its own (not in the big state payload) while the
   panel is on screen. */
const OC = {right: "C", expiry: null, data: null, timer: null, busy: false};
/* RISK SIZE for a contract: your RISK $ over what one contract loses if the stock runs to the stop
   (delta × 100 × distance) — the stop is this contract's own (on the stock) or the chart's STOP line on its side */
function optRiskSize(d){
  const os = (T().opt_stops || {})[d.key], stop = os && os.on === "stock" ? +os.price : d.chart_stop;
  if (!stop || !d.spot || d.delta == null) return null;
  const per = Math.abs(d.delta) * 100 * Math.abs(d.spot - stop);
  if (!(per > 0)) return null;
  const n = Math.floor(riskDollars() / per);
  if (n < 1) return null;
  return {n, why: `RISK $${riskDollars()} ÷ (delta ${Math.abs(d.delta).toFixed(2)} × 100 × ${Math.abs(d.spot - stop).toFixed(2)} to the stop ${stop.toFixed(2)}) = ${n} contracts — click to use it`};
}
/* ORDER ENTRY: STOCK | OPTIONS. On OPTIONS with no contract yet, pick it right here: expiry, CALLS / PUTS, a strike
   near the money (with its bid / ask) — the same as clicking a strike in the OPTION CHAIN */
let TMODE = "stock";
const PICK = {sym: null, right: "C", expiry: null, data: null, busy: false};
async function pollPick(){
  if (PICK.busy || TMODE !== "opt" || (OC.link && OC.link.sym === curSym) || !curSym || !P.ticket.el.offsetParent) return;
  PICK.busy = true;
  try { const r = await fetch(`/api/options/chain?symbol=${encodeURIComponent(curSym)}&right=${PICK.right}${PICK.expiry ? "&expiry=" + PICK.expiry : ""}&width=8`);
    PICK.data = await r.json(); PICK.sym = curSym; if (PICK.data && PICK.data.expiry) PICK.expiry = PICK.data.expiry; P.ticket.last = null; renderTicket(state, curData()); }
  catch (e) {} finally { PICK.busy = false; }
}
setInterval(pollPick, 1500);
function optPickHTML(d){
  const c = PICK.sym === curSym ? PICK.data : null, f = v => v == null ? "—" : (+v).toFixed(2);
  if (!c || !c.available) return `<div class="simple pick"><div class="dim" style="padding:6px">${c && c.note ? esc(c.note) : "Loading the " + esc(curSym || "") + " option chain…"}</div></div>`;
  const exps = c.expiries.slice(0, 8).map(x => `<option value="${x}" ${x === c.expiry ? "selected" : ""}>${x.slice(4, 6)}/${x.slice(6, 8)}</option>`).join("");
  const atm = c.rows.reduce((b, r, i) => Math.abs(r.strike - c.spot) < Math.abs(c.rows[b].strike - c.spot) ? i : b, 0);
  const rows = c.rows.slice(Math.max(0, atm - 4), atm + 5).map(r => { const itm = c.right === "C" ? r.strike < c.spot : r.strike > c.spot;
    return `<button class="pk ${itm ? "itm" : ""} ${Math.abs(r.strike - c.spot) < 1e-9 || r === c.rows[atm] ? "atm" : ""}" data-pick="${esc(r.key)}" data-strike="${r.strike}" title="trade this contract">${r.strike % 1 ? r.strike.toFixed(2) : r.strike}${c.right}<i>${f(r.bid)} / ${f(r.ask)}</i></button>`; }).join("");
  return `<div class="simple pick"><div class="prow"><span class="lbl">PICK THE CONTRACT</span><select id="pickExp" title="expiry">${exps}</select>
    <span class="cp"><button data-pickr="C" class="${c.right === "C" ? "on b" : ""}">CALLS</button><button data-pickr="P" class="${c.right === "P" ? "on s" : ""}">PUTS</button></span><span class="dim">${esc(curSym)} ${f(c.spot)}</span></div>
    <div class="pgrid">${rows}</div><div class="dim" style="font-size:10.5px">in the money shaded · the middle one is at the money · then BUY / SELL with contracts</div></div>`;
}
document.addEventListener("change", e => { if (e.target.id === "pickExp"){ PICK.expiry = e.target.value; pollPick(); } });
document.addEventListener("click", e => { const b = e.target.closest("button[data-sqty]"); if (b && P.ticket.el.contains(b)) setLadQty(b.dataset.sqty); });
document.addEventListener("change", e => { if (e.target.id === "sbQty") setLadQty(e.target.value); });
document.addEventListener("click", e => {
  const m = e.target.closest("button[data-tmode]");
  if (m){ if (m.dataset.tmode === "stock"){ TMODE = "stock"; OC.link = null; unpair(); if (typeof CPIN !== "undefined"){ CPIN.book = CPIN.tape = "auto"; store.set("cpin", CPIN); } }
    else { TMODE = "opt"; PICK.data = PICK.sym === curSym ? PICK.data : null; pollPick(); }
    P.ticket.last = null; renderTicket(state, curData(), true); poll(true); return; }
  const mo = e.target.closest("button[data-tkmore]"); if (mo){ store.set("tkmore", !store.get("tkmore", false)); P.ticket.last = null; renderTicket(state, curData(), true); return; }
  const r = e.target.closest("button[data-pickr]"); if (r){ PICK.right = r.dataset.pickr; pollPick(); return; }
  const pk = e.target.closest("button[data-pick]"); if (pk && PICK.data){ const row = PICK.data.rows.find(x => x.key === pk.dataset.pick) || {};
    OC.link = {sym: curSym, expiry: PICK.data.expiry, strike: +pk.dataset.strike, right: PICK.data.right, key: pk.dataset.pick, bid: row.bid, ask: row.ask, n: (OC.link && OC.link.n) || 1};
    if (typeof chartOption === "function") chartOption(pk.dataset.pick, false);
    P.ticket.last = null; renderTicket(state, curData(), true); poll(true); toast("ORDER ENTRY trades " + contractName(OC.link), true); }
});
/* SELL TO OPEN: selling contracts you don't own leaves you SHORT. Always a red confirm (ONE-CLICK or not), saying so */
function shortOpening(key, action, n){
  if (action !== "SELL") return 0;
  const p = ((state && state.account && state.account.opt_positions) || []).find(x => x.key === key);
  return Math.max(0, n - Math.max(0, p ? p.qty : 0));
}
function shortOpenConfirm(what, so, send){
  const allowed = !!T().allow_sell_to_open;
  confirmBox(`SELL TO OPEN · ${what}`, `you'll be SHORT ${so} contract${so === 1 ? "" : "s"}: you take the premium and owe the move. ` +
    (allowed ? "A short call has no ceiling on the loss; a short put can be assigned the shares. Your IBKR account needs the option level for it."
             : "Selling to open is OFF (SETTINGS, Trading, Allow selling to open): this goes through only as a covered call (100 shares each)."), "s", send);
  const m = document.getElementById("modal"); if (m) m.classList.add("shortopen");
}
// "NVDA 10/09 225 CALL" / "NVDA 10/09 225C" -> "NVDA 10/09 225 calls"
function optWords(n){ return String(n || "").replace(/\s?(CALL|C)$/, " calls").replace(/\s?(PUT|P)$/, " puts"); }
function contractName(l){ return `${l.sym} ${l.expiry.slice(4, 6)}/${l.expiry.slice(6, 8)} ${l.strike % 1 ? l.strike.toFixed(2) : l.strike} ${l.right === "C" ? "CALL" : "PUT"}`; }
async function pollLink(){
  const l = OC.link; if (!l || l.sym !== curSym || OC.busy) return;
  const p = P.options; if (p && p.el.classList.contains("on") && p.el.offsetParent !== null && OC.data && OC.data.expiry === l.expiry && OC.data.right === l.right) return;   // the chain poll covers it
  try { const r = await fetch(`/api/options/chain?symbol=${encodeURIComponent(l.sym)}&right=${l.right}&expiry=${l.expiry}`); const d = await r.json();
    const row = (d.rows || []).find(x => x.key === l.key || x.strike === l.strike); if (row){ l.bid = row.bid; l.ask = row.ask; } } catch (e) {}
}
setInterval(pollLink, 1000);
async function pollChain(){
  if (OC.busy) return; const sym = curSym, p = P.options; if (!sym || !p || !p.el.classList.contains("on") || p.el.offsetParent === null) return;
  OC.busy = true;
  try { const r = await fetch(`/api/options/chain?symbol=${encodeURIComponent(sym)}&right=${OC.right}${OC.expiry ? "&expiry=" + OC.expiry : ""}`); OC.data = await r.json(); renderChain(); }
  catch (e) {} finally { OC.busy = false; }
}
setInterval(pollChain, 1000);
function renderChain(){
  const box = P.options && P.options.pc.querySelector(".oc"); if (!box) return;
  const d = OC.data, body = box.querySelector(".oc-body");
  document.getElementById("ocSym").textContent = curSym || "";
  if (!d || !d.available){ body.innerHTML = `<div class="dim" style="padding:6px">${d && d.note ? esc(d.note) : "no chain yet"}${d && d.source === null && state && state.connection && state.connection.state === "CONNECTED" ? " — asked IBKR; needs the contract resolved and option data permissions" : ""}</div>`; return; }
  const sel = document.getElementById("ocExp");
  const opts = d.expiries.map(x => `<option value="${x}" ${x === d.expiry ? "selected" : ""}>${x.slice(4, 6)}/${x.slice(6, 8)}${x.slice(0, 4) !== String(new Date().getFullYear()) ? "/" + x.slice(2, 4) : ""}</option>`).join("");
  if (sel.dataset.h !== opts){ sel.dataset.h = opts; sel.innerHTML = opts; }
  if (OC.expiry !== d.expiry) OC.expiry = d.expiry;
  box.querySelectorAll(".cp button").forEach(b => b.classList.toggle("on", b.dataset.right === d.right));
  document.getElementById("ocSpot").textContent = d.spot ? `spot ${px(d.spot)} · ${d.rows.length ? Math.round(d.rows[0].dte) + "d" : ""}` : "";
  { const src = document.getElementById("ocSrc");
    src.textContent = d.sim ? "SIM · market closed" : d.source === "PRACTICE" ? "PRACTICE prices (model)" : "IBKR";
    src.className = d.sim ? "simtag" : "dim"; src.title = d.sim ? (d.sim_why || "") : "";
    const pn = box.closest(".pnl"); if (pn) pn.classList.toggle("simmode", !!d.sim); }
  const on = canTrade(), red = canReduce();
  if (OC.link && OC.link.sym === curSym && d.expiry === OC.link.expiry && d.right === OC.link.right){ const lr = d.rows.find(x => x.key === OC.link.key); if (lr){ OC.link.bid = lr.bid; OC.link.ask = lr.ask; } }
  const rows = d.rows.map(r => { const itm = d.right === "C" ? r.strike < d.spot : r.strike > d.spot; const held = r.qty;
    return `<tr class="${itm ? "itm" : "otm"} ${Math.abs(r.strike - d.spot) < (d.rows[1] ? Math.abs(d.rows[1].strike - d.rows[0].strike) / 2 : 0.5) ? "atm" : ""} ${held ? "held" : ""} ${OC.sel === r.strike ? "sel" : ""} ${OC.link && OC.link.key === r.key ? "linked" : ""}" data-key="${esc(r.key)}" data-strike="${r.strike}" title="click to trade this contract from ORDER ENTRY (its mid goes into PX too)">
      <td class="k">${r.strike % 1 ? r.strike.toFixed(2) : r.strike}${held ? ` <span class="hold ${held > 0 ? "b" : "s"}">${held > 0 ? "+" : ""}${held}</span>` : ""}</td>
      <td class="b">${r.bid == null ? "—" : r.bid.toFixed(2)}</td><td class="s">${r.ask == null ? "—" : r.ask.toFixed(2)}</td><td class="dim">${r.last == null ? "—" : r.last.toFixed(2)}</td>
      <td class="dl" title="delta: how much the contract moves per $1 in the stock">${r.delta == null ? "—" : r.delta.toFixed(2)}</td><td class="dim" title="implied volatility">${r.iv == null ? "—" : Math.round(r.iv * 100) + "%"}</td>
      <td class="act">${OC.link && OC.link.key === r.key
        ? `<span class="ldbtn on" title="loaded on the OPTION CHART — click the ✓ to take it off the chart (no order is touched)">✓</span>`
        : `<span class="ldbtn" title="load ${esc(curSym)} ${r.strike % 1 ? r.strike.toFixed(2) : r.strike}${d.right} onto the OPTION CHART and ORDER ENTRY (no order is sent)">📈</span>`}</td></tr>`; }).join("");
  const working = (d.orders || []).map(o => `<div class="wk"><span class="${o.action === "BUY" ? "b" : "s"}">${esc(o.action)} ${o.remaining ?? o.qty} ${esc(o.symbol)} @ ${o.lmt}</span> <span class="dim">${esc(o.status || "")}</span> <button data-cxl="${o.order_id}" class="danger">✕</button></div>`).join("");
  const noQ = d.rows.length && d.rows.every(r => r.bid == null && r.ask == null);
  const banner = noQ ? `<div class="ocwarn q">NO QUOTES on this chain (market closed, or no option data on this login) — click a strike and type your limit in PX</div>` : "";
  const html = banner + `<table class="t oct"><tr><th>STRIKE</th><th>BID</th><th>ASK</th><th>LAST</th><th>Δ</th><th>IV</th><th></th></tr>${rows}</table>${working ? `<div class="wks">${working}</div>` : ""}`;
  if (body.dataset.h === html) return; body.dataset.h = html;
  const keep = body.scrollTop; body.innerHTML = html; body.scrollTop = keep;
}
document.addEventListener("click", e => { const b = e.target.closest("button[data-openchain]"); if (!b) return; showPanel("options"); const el = P.options && P.options.el; if (el) el.scrollIntoView({block: "nearest"}); toast("OPTION CHAIN: pick the expiry, click BUY or SELL on a strike, set contracts and price, SEND", true); });
(function(){ const p = P.options; if (!p) return;
  p.el.addEventListener("change", e => { if (e.target.id === "ocExp"){ OC.expiry = e.target.value; pollChain(); } });
  p.el.addEventListener("keydown", e => { if (e.target.matches("input")) e.stopPropagation(); });
  p.el.addEventListener("click", async e => {
    const rb = e.target.closest(".cp button[data-right]"); if (rb){ OC.right = rb.dataset.right; pollChain(); return; }
    const cx = e.target.closest("button[data-cxl]"); if (cx){ cancelMine(+cx.dataset.cxl); return; }
    const oc = e.target.closest("button[data-oc]"); if (oc){ if (!confirm("CLOSE every contract of " + oc.dataset.oc + "?")) return; const out = await post("/api/trade/opt_adjust", {key: oc.dataset.oc, contracts: 0, mode: "close"}); toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); return; }
    if (e.target.closest("button[data-ocarm]")){ document.getElementById("armBtn").click(); setTimeout(() => { const bd = P.options.pc.querySelector(".oc-body"); if (bd) bd.dataset.h = ""; renderChain(); }, 600); return; }
    const b = e.target.closest("button[data-oo]");
    // the ✓ on the loaded contract takes it OFF the option chart again (same button that put it there)
    { const ld = e.target.closest(".ldbtn"), rowEl = e.target.closest("tr[data-strike]");
      if (ld && rowEl && OC.link && OC.link.key === rowEl.dataset.key){ unloadContract(); return; } }
    if (!b){ const rowEl = e.target.closest("tr[data-strike]"); if (rowEl && OC.data){ const k = +rowEl.dataset.strike, r = OC.data.rows.find(x => x.strike === k) || {};
        OC.sel = k; const mid = r.bid != null && r.ask != null ? (r.bid + r.ask) / 2 : (r.last != null ? r.last : null);
        OC.link = {sym: curSym, expiry: OC.data.expiry, strike: k, right: OC.data.right, key: r.key, bid: r.bid, ask: r.ask, n: (OC.link && OC.link.n) || 1};
        toast(`${contractName(OC.link)} loaded — on the OPTION CHART and in ORDER ENTRY (nothing was bought)`, true); P.ticket.last = null; poll(true); if (typeof chartOption === "function") chartOption(r.key, false); renderContractL2(); renderContractTape();
        const bd = P.options.pc.querySelector(".oc-body"); if (bd) bd.dataset.h = ""; renderChain(); }
      return; }
    return;      // the chain never sends an order: it only loads the contract (orders go from ORDER ENTRY, the order bar, the option chart)
    if (!OC.data) return;
    if (!canTrade()){ const w = T().why_not || "trading is DISARMED"; toast(/click ARM/i.test(w) ? w : w + " — click ARM (top left) first", false); const a = document.getElementById("armBtn"); if (a){ a.dataset.pulse = "1"; setTimeout(() => { delete a.dataset.pulse; }, 2400); } return; }
    const tr = b.closest("tr"), strike = +tr.dataset.strike, n = Math.max(1, +document.getElementById("ocQty").value || 1), pxv = document.getElementById("ocPx").value;
    { const r0 = OC.data.rows.find(x => x.strike === strike) || {}; const touch = b.dataset.oo === "BUY" ? r0.ask : r0.bid;
      if (pxv === "" && touch == null){ toast("No quote on that contract — type your limit price in PX, then press " + b.dataset.oo + " again", false); OC.sel = strike; document.getElementById("ocPx").focus(); return; } }
    const d = OC.data, what = `${b.dataset.oo} ${n} ${curSym} ${d.expiry.slice(4, 6)}/${d.expiry.slice(6, 8)} ${strike}${d.right}`;
    const send = async () => { const out = await post("/api/trade/opt_open", {symbol: curSym, expiry: d.expiry, strike, right: d.right, action: b.dataset.oo, contracts: n, price: pxv === "" ? null : +pxv}); toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); poll(true); pollChain(); };
    { const row0 = d.rows.find(r => r.strike === strike) || {}; const so = shortOpening(row0.key, b.dataset.oo, n); if (so) return shortOpenConfirm(what, so, send); }
    if (T().one_click) return send();
    const row = d.rows.find(r => r.strike === strike) || {}; const ref = pxv !== "" ? +pxv : (b.dataset.oo === "BUY" ? row.ask : row.bid);
    confirmBox(what, `limit ${ref != null ? "$" + ref.toFixed(2) : "?"} a contract · about $${sz(Math.round((ref || 0) * 100 * n))} · ${d.source === "PRACTICE" ? "practice" : "IBKR paper"}`, b.dataset.oo === "BUY" ? "b" : "s", send);
  });
})();
/* right-click a ladder row: every order action at that price, in one menu */
function ladderMenu(d, price, x, y, chip){
  const old = document.getElementById("cmenu"); if (old) old.remove();
  const t = T(), on = canTrade(), red = canReduce(), q = t.default_shares, tk = tickOfPx(price), ticks = (t.stop_limit_ticks || 10) * tk;
  const m = document.createElement("div"); m.id = "cmenu"; m.className = "pop cmenu lmenu";
  const mine = (d.orders || []).filter(o => o.id != null), bids = mine.filter(o => o.action === "BUY").length, asks = mine.filter(o => o.action === "SELL").length;
  m.innerHTML = `<div class="dim" style="font-size:11px;margin-bottom:4px">${esc(d.symbol)} @ <b style="color:var(--gold)">${px(price)}</b> · ${sz(q)} sh<span class="x" title="close (Esc)">✕</span></div>
    ${chip ? `<button data-do="moveto" data-id="${chip.dataset.id}">Move order #${esc(chip.dataset.id)} here</button><button class="bsell" data-do="cxlone" data-id="${chip.dataset.id}">Cancel order #${esc(chip.dataset.id)}</button>` : ""}
    <button class="bbuy" data-do="buy" ${on ? "" : "disabled"}>BUY limit @ ${px(price)}</button>
    <button class="bsell" data-do="sell" ${on ? "" : "disabled"}>SELL limit @ ${px(price)}</button>
    <button data-do="buystp" ${on ? "" : "disabled"} title="buy stop-limit: triggers at ${px(price)}, limit ${px(price + ticks)}">BUY stop-limit, trigger ${px(price)}</button>
    <button data-do="sellstp" ${on ? "" : "disabled"} title="sell stop-limit: triggers at ${px(price)}, limit ${px(price - ticks)}">SELL stop-limit, trigger ${px(price)}</button>
    ${t.allow_market ? `<button data-do="buymkt" ${on ? "" : "disabled"}>BUY market</button><button data-do="sellmkt" ${on ? "" : "disabled"}>SELL market</button>` : ""}
    <button data-do="joinbid" ${on ? "" : "disabled"}>Join the bid (BUY @ ${px(d.bid)})</button>
    <button data-do="joinask" ${on ? "" : "disabled"}>Join the ask (SELL @ ${px(d.ask)})</button>
    <div class="sep"></div>
    ${bids ? `<button data-do="cxlbids">Cancel bid orders (${bids})</button>` : ""}${asks ? `<button data-do="cxlasks">Cancel ask orders (${asks})</button>` : ""}
    ${mine.length ? `<button data-do="cxl">Cancel all on ${esc(d.symbol)} (${mine.length})</button>` : ""}
    ${d.position && d.position.qty ? `<button class="bflat" data-do="flat" ${red ? "" : "disabled"}>FLATTEN ${esc(d.symbol)}</button><button class="bflat" data-do="rev" ${on ? "" : "disabled"} title="close the position and open the same size the other way">REVERSE to ${d.position.qty > 0 ? "SHORT" : "LONG"} ${sz(Math.abs(d.position.qty))}</button>` : ""}
    <div class="sep"></div>
    <button data-do="lvl" data-role="stop" class="blvl">STOP here</button><button data-do="lvl" data-role="target" class="blvl">TARGET here</button><button data-do="lvl" data-role="second_entry" class="blvl se">2ND ENTRY here</button>`;
  document.body.appendChild(m);
  const W = m.offsetWidth || 260, H = m.offsetHeight || 300;
  m.style.left = Math.min(x, window.innerWidth - W - 8) + "px"; m.style.top = Math.min(y, window.innerHeight - H - 8) + "px";
  m.querySelector(".x").addEventListener("click", () => m.remove());
  m.addEventListener("click", async e => {
    const b = e.target.closest("button[data-do]"); if (!b || b.disabled) return; m.remove();
    const act = b.dataset.do, sym = d.symbol;
    const order = body => post("/api/trade/order", Object.assign({symbol: sym, qty: q, tif: "DAY", nonce: tkNonce()}, body)).then(out => { toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); poll(true); });
    if (act === "buy") sendOrder(sym, "BUY", price);
    else if (act === "sell") sendOrder(sym, "SELL", price);
    else if (act === "buystp") order({action: "BUY", type: "STP LMT", aux: price, price: snapPx(price + ticks)});
    else if (act === "sellstp") order({action: "SELL", type: "STP LMT", aux: price, price: snapPx(price - ticks)});
    else if (act === "buymkt") order({action: "BUY", type: "MKT", price: null});
    else if (act === "sellmkt") order({action: "SELL", type: "MKT", price: null});
    else if (act === "joinbid") sendOrder(sym, "BUY", d.bid);
    else if (act === "joinask") sendOrder(sym, "SELL", d.ask);
    else if (act === "cxlbids" || act === "cxlasks"){ const out = await post("/api/trade/cancel_side", {symbol: sym, side: act === "cxlbids" ? "bid" : "ask"}); toast(`Cancelled ${out.cancelled || 0}`, true); poll(true); }
    else if (act === "cxl") cancelAll(sym);
    else if (act === "cxlone") cancelMine(+b.dataset.id);
    else if (act === "moveto"){ const out = await post("/api/trade/modify", {id: +b.dataset.id, price}); toast(out.ok ? "Moved to " + px(price) : "Not moved: " + (out.reason || ""), out.ok); poll(true); }
    else if (act === "flat") flatten(sym);
    else if (act === "rev"){ confirmBox(`REVERSE ${sym}`, `closes ${sz(Math.abs(d.position.qty))} and opens the same size the other way, both at the market`, "s", async () => { const out = await post("/api/trade/reverse", {symbol: sym}); toast(out.ok ? "Reverse sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); poll(true); }); }
    else if (act === "lvl"){ const role = b.dataset.role; const out = await post("/api/level", {symbol: sym, role, price}); toast(out.ok ? `${sym} ${role.replace("_", " ")} ${px(price)}` : "Could not set it", out.ok); if (out.ok) poll(true); }
  });
  const away = ev => { if (!m.isConnected){ document.removeEventListener("mousedown", away, true); return; } if (!m.contains(ev.target)) m.remove(); };
  setTimeout(() => document.addEventListener("mousedown", away, true), 0);
  setTimeout(() => { if (m.isConnected) m.remove(); }, 20000);
}
/* your average entry, marked on the ladder (the row nearest your cost carries an AVG tag) */
function avgRow(wrap, d){
  const pos = d && d.position; if (!pos || !pos.qty || !pos.avg_cost) return;
  let best = null, bd = Infinity;
  for (const tr of wrap.querySelectorAll("tr[data-price]")){ const dd = Math.abs(+tr.dataset.price - pos.avg_cost); if (dd < bd){ bd = dd; best = tr; } }
  if (!best) return;
  best.classList.add("avgrow", pos.qty > 0 ? "long" : "short");
  const cell = best.querySelector("td.px"); if (cell && !cell.querySelector(".avgtag")) cell.insertAdjacentHTML("afterbegin", `<span class="avgtag" title="your average entry ${px(pos.avg_cost)} · ${pos.qty > 0 ? "LONG" : "SHORT"} ${sz(Math.abs(pos.qty))}">AVG</span>`);
}
/* the status strip over the ladder: symbol · last · change · bid / ask · spread · position · avg · P&L % · data · connection · mode */
function renderLadStat(d, s){
  const el = document.getElementById("ladStat"); if (!el) return;
  // you asked for it gone: no symbol / price / change / bid-ask line over the Level II (POSITIONS has your trade)
  if (el.style.display !== "none") el.style.display = "none";
  return;
  if (!d){ el.innerHTML = ""; return; }
  const t = (s && s.trading) || {}, c = (s && s.connection) || {}, f = (s && s.feeds) || {};
  const chg = d.last && d.prev_close ? (d.last - d.prev_close) / d.prev_close * 100 : null;
  const spread = d.bid && d.ask ? d.ask - d.bid : null;
  const pos = d.position, pct = pos && pos.qty && d.last ? ((d.last - pos.avg_cost) / pos.avg_cost * 100) * (pos.qty > 0 ? 1 : -1) : null;
  const mode = t.mode === "LIVE" ? "LIVE TRADING" : t.mode === "PAPER" ? "PAPER" : t.mode === "SIM" ? "PRACTICE" : "NO ORDERS";
  const conn = c.state || "—", cstate = conn === "CONNECTED" ? "ok" : /CONNECTING|RECONNECTING|DEMO|REPLAY/.test(conn) ? "warn" : "bad";
  const mkt = f.mkt || {};
  const html = `<b class="sym">${esc(d.symbol)}</b>${d.halted ? `<span class="haltbadge">${esc(d.halted)}</span>` : ""}<span class="mono">${px(d.last)}</span><span class="mono ${chg == null ? "dim" : chg >= 0 ? "up" : "dn"}">${chg == null ? "—" : (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%"}</span>
    <span class="mono"><i class="b">${px(d.bid)}</i> / <i class="s">${px(d.ask)}</i></span><span class="mono dim">${spread == null ? "" : "sp " + spread.toFixed(spread < 1 ? 2 : 2)}</span>
    <span class="spacer"></span>
    ${pos && pos.qty ? `<span class="pos ${pos.qty > 0 ? "b" : "s"}">${pos.qty > 0 ? "+" : ""}${sz(pos.qty)}</span><span class="mono dim">avg ${px(pos.avg_cost)}</span><span class="mono ${pct >= 0 ? "up" : "dn"}"><b>${pct == null ? "—" : (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%"}</b></span>` : `<span class="dim">FLAT</span>`}
    <span class="led ${mkt.color === "green" ? "ok" : mkt.color === "amber" ? "warn" : "bad"}" title="${esc(mkt.title || "")}"></span><span class="dim">${esc(mkt.label || "")}</span>
    <span class="led ${cstate}" title="${esc(c.detail || "")}"></span><span class="dim">${esc(conn)}</span>
    <span class="mode ${t.mode === "LIVE" ? "live" : ""}">${mode}</span>`;
  if (el.dataset.h !== html){ el.dataset.h = html; el.innerHTML = html; }
}
/* SEE THE ORDERS BEING TAKEN. Every size cell remembers the most it showed at that price in the last 90 s (its
   peak) and draws itself as a bar: full when the size is all there, shrinking as prints eat it. 10.2K showing,
   price trades up into it, 5.5K gets bought: the bar is half gone and the number reads 4.7K. A drop flashes the
   cell and floats the shares taken (−1.4K); size coming back after a drop floats +2.0K ↻ (the reload). The strip
   under the ladder spells out the touch on both sides: "ASK 242.75 · 4.7K of 10.2K left · 5.5K bought (54%)". */
const EAT = new Map();
document.addEventListener("mouseover", e => {
  const c = e.target.closest && e.target.closest(".ladder-wrap td.bsz, .ladder-wrap td.asz"); const tr = c && c.closest("tr[data-price]");
  if (tr){ LADHOVER.sym = curSym; LADHOVER.price = tr.dataset.price; LADHOVER.side = c.classList.contains("bsz") ? "bid" : "ask"; }
  else if (LADHOVER.sym && !(e.target.closest && e.target.closest(".ladder-wrap"))) LADHOVER.sym = null;
});
function eatMarks(wrap, d, host){
  // the CLEAN ladder shows a pull as a faded, crossed-out size: no floating badges over its rows
  if (!host && ["clean", "basket"].includes(store.get("ladMode", "clean"))){ wrap.querySelectorAll(".eatbar").forEach(x => x.remove()); return; }
  const rows = (d.ladder && d.ladder.rows) || [], now = Date.now(), sym = d.symbol;
  const touch = {bid: null, ask: null};
  for (const r of rows){
    for (const side of ["bid", "ask"]){
      const size = +r[side] || 0, key = `${sym}|${side}|${r.price}`;
      let m = EAT.get(key);
      if (!m || now - m.t > 90000 || size > m.peak){ m = {peak: size, t: now, last: m ? m.last : size, pt: now}; EAT.set(key, m); }
      const cell = wrap.querySelector(`tr[data-price="${r.price}"] td.${side === "bid" ? "bsz" : "asz"}`);
      if (cell && size > 0 && m.peak > 0){
        const left = Math.max(0, Math.min(1, size / m.peak));
        cell.style.setProperty("--fill", (left * 100).toFixed(0) + "%");
        if (left < 0.98) cell.classList.add("eat");
      }
      if (cell && m.last != null && size !== m.last && now - m.pt < 4000){
        const dlt = size - m.last;
        const trd = Math.max(0, (+r[side === "bid" ? "sold" : "bought"] || 0) - (m.trd != null ? m.trd : (+r[side === "bid" ? "sold" : "bought"] || 0)));
        if (dlt < 0 && size > 0){
          const gone = -dlt, traded = Math.min(gone, trd), pulled = gone - traded;
          const lbl = traded >= gone * 0.5 ? `−${kfmt(traded)} ${side === "bid" ? "sold" : "bot"}${pulled >= 100 ? ` −${kfmt(pulled)} pull` : ""}` : `−${kfmt(gone)} pull`;
          cell.classList.add(traded >= gone * 0.5 ? "hit" : "pull");
          cell.insertAdjacentHTML("beforeend", `<i class="ghost ${traded >= gone * 0.5 ? "dn" : "pl"}" title="${kfmt(gone)} came off ${px(r.price)}: ${kfmt(traded)} traded (prints at this price), ${kfmt(pulled)} just left without trading">${lbl}</i>`); }
        else if (dlt > 0 && m.last > 0 && m.last < m.peak * 0.7){ cell.classList.add("refill"); cell.insertAdjacentHTML("beforeend", `<i class="ghost up" title="${kfmt(dlt)} shares just came back at this price: a refill">+${kfmt(dlt)} ↻</i>`); }
      }
      m.last = size; m.pt = now; m.trd = +r[side === "bid" ? "sold" : "bought"] || 0;
      if ((side === "bid" && r.best_bid) || (side === "ask" && r.best_ask)) touch[side] = {price: r.price, size, peak: m.peak};
    }
  }
  if (EAT.size > 4000) for (const k of [...EAT.keys()].slice(0, 2000)) EAT.delete(k);
  host = host || P.book.pc;
  let bar = host.querySelector(":scope > .eatbar, :scope .eatbar"); if (!bar){ bar = document.createElement("div"); bar.className = "eatbar"; host.appendChild(bar); }
  const line = (side, t) => { if (!t) return `<span class="${side === "bid" ? "b" : "s"} dim">${side.toUpperCase()} —</span>`;
    const gone = Math.max(0, t.peak - t.size), pct = t.peak ? Math.round(100 * gone / t.peak) : 0;
    return `<span class="${side === "bid" ? "b" : "s"}" title="${side === "bid" ? "the bid" : "the offer"} at ${px(t.price)}: it showed ${sz(t.peak)} at most in the last 90 s; ${sz(t.size)} is left. ${sz(gone)} ${side === "bid" ? "sold into it" : "bought from it"} since (${pct}%)${pct >= 60 ? " — nearly eaten: if it refills, that is a reload" : ""}"><b>${side.toUpperCase()} ${px(t.price)}</b> ${kfmt(t.size)} of ${kfmt(t.peak)}${gone ? ` · ${kfmt(gone)} ${side === "bid" ? "sold into it" : "bought"} (${pct}%)` : " · untouched"}</span>`; };
  // THE LEVEL'S STORY: the row under the mouse, else the biggest size near price. What is sitting, what came in,
  // what traded out of it, what got pulled, the most it showed
  let pick = LADHOVER.sym === sym ? rows.find(r => r.price === LADHOVER.price) : null, pside = LADHOVER.side;
  if (!pick){
    const li = rows.findIndex(r => r.last || r.best_bid || r.best_ask); let best = 0;
    rows.forEach((r, i) => { if (li >= 0 && Math.abs(i - li) > 8) return; for (const sd of ["bid", "ask"]) if ((+r[sd] || 0) > best){ best = +r[sd]; pick = r; pside = sd; } });
  }
  const st = pick ? levelStory(pick, pside) : "";
  const h = `<div class="lstory">${st || `<span class="dim">hover a size to see its story: what sits there, what came in, what traded, what got pulled</span>`}</div><div class="ltouch">${line("bid", touch.bid) + line("ask", touch.ask)}</div>`;
  if (bar.dataset.h !== h){ bar.dataset.h = h; bar.innerHTML = h; }
}
const LADHOVER = {sym: null, price: null, side: null};
function levelStory(r, side){
  const s = r[side + "_story"] || {}, now = +r[side] || 0, took = side === "bid" ? "sold into it" : "bought from it";
  const parts = [`<b class="${side === "bid" ? "b" : "s"}">${side === "bid" ? "BID" : "ASK"} ${px(r.price)}</b>`,
    `<b>${sz(now)}</b> sitting`,
    s.in ? `<span class="up">+${sz(s.in)} came in</span>` : "",
    s.traded ? `<span class="${side === "bid" ? "s" : "b"}">${sz(s.traded)} ${took}</span>` : `<span class="dim">nothing traded into it</span>`,
    s.pulled ? `<span class="pl">${sz(s.pulled)} pulled</span>` : "",
    s.peak > now ? `<span class="dim">most it showed ${sz(s.peak)}</span>` : "",
    (r[side === "bid" ? "sold" : "bought"] || 0) ? `<span class="dim">${sz(r[side === "bid" ? "sold" : "bought"])} printed at this price in all</span>` : ""];
  return parts.filter(Boolean).join(" · ");
}
/* the banner over the ladder: every proven reload buyer / seller on this symbol, where he is, and a click to jump there */
/* THE RELOAD BASKET: minimized, the dollars the reload buyers bought and the reload sellers sold today; open, their
   own small Level II: each price, what was bought (buyers' side) or sold (sellers' side) there, in shares and dollars,
   whether he is still there (glowing, with what he shows) or gone (dim). */
function renderRlBasket(d){
  const box = document.getElementById("rlBasket"); if (!box) return;
  const bk = (d && d.reload_basket) || {rows: [], buy_usd: 0, sell_usd: 0}, pill = box.querySelector(".rbk-pill"), pop = box.querySelector(".rbk-pop");
  const ph = bk.rows.length ? `R$ <b class="b">▲ ${usdK(bk.buy_usd)}</b> <b class="s">▼ ${usdK(bk.sell_usd)}</b>` : "R$ —";
  if (pill.dataset.h !== ph){ pill.dataset.h = ph; pill.innerHTML = ph; }
  if (!box.classList.contains("open")) return;
  const bs = bk.rows.filter(r => r.side === "bid").reduce((a, r) => a + r.shares, 0), ss = bk.rows.filter(r => r.side === "ask").reduce((a, r) => a + r.shares, 0);
  const prices = [...new Set(bk.rows.map(r => r.price))].sort((a, b) => b - a);
  const cell = (r, side) => r ? `<td class="${side} ${r.here ? "here" : "gone"}" title="${side === "b" ? "reload BUYER" : "reload SELLER"} ${px(r.price)} · refilled ${r.refills}× · ${r.here ? `showing ${sz(r.showing)} now` : "not there now"}">${sz(r.shares)}${r.here ? `<i>+${kfmt(r.showing)} now</i>` : ""}</td>` : `<td class="${side}"></td>`;
  const usd = (r, side) => `<td class="${side} usd ${r ? (r.here ? "here" : "gone") : ""}">${r ? usdK(r.usd) : ""}</td>`;
  const h = `<div class="rbk-h">RELOAD BASKET · ${esc(d.symbol)}<span class="dim">today</span></div>` + (prices.length ? `<table class="rbk-t"><tr><th>BUYER $</th><th>BOUGHT</th><th>PRICE</th><th>SOLD</th><th>SELLER $</th></tr>` +
    prices.map(p0 => { const b = bk.rows.find(r => r.price === p0 && r.side === "bid"), a = bk.rows.find(r => r.price === p0 && r.side === "ask");
      const last = d.last != null && Math.abs(+d.last - p0) < 0.0051;
      return `<tr class="${last ? "atpx" : ""}">${usd(b, "b")}${cell(b, "b")}<td class="px">${px(p0)}</td>${cell(a, "s")}${usd(a, "s")}</tr>`; }).join("") +
    `<tr class="tot"><td class="b usd">${usdK(bk.buy_usd)}</td><td class="b">${sz(bs)}</td><td class="px">TOTAL</td><td class="s">${sz(ss)}</td><td class="s usd">${usdK(bk.sell_usd)}</td></tr></table>`
    : `<div class="dim" style="padding:6px">No reload buyers or sellers yet today.</div>`);
  if (pop.dataset.h !== h){ pop.dataset.h = h; pop.innerHTML = h; }
}
document.addEventListener("click", e => {
  const b = e.target.closest("#rlBasket .rbk-pill"); if (!b) return;
  e.stopPropagation(); const m = b.closest(".menu"), open = !m.classList.contains("open");
  document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); m.classList.toggle("open", open);
  if (open){ m.querySelector(".rbk-pop").dataset.h = ""; renderRlBasket(curData()); if (typeof placePop === "function") placePop(m); }
}, true);
function rlBanner(wrap, d){
  const ban = document.getElementById("rlBan"); if (!ban) return;
  const rows = (d.ladder && d.ladder.rows) || [];
  const items = [];
  for (const r of rows){
    for (const side of ["bid", "ask"]){
      if (!(r[side + "_state"] === "RELOAD" || r[side + "_proven"])) continue;
      const el = wrap.querySelector(`tr[data-price="${r.price}"]`);
      const y = el ? el.offsetTop : null, top = wrap.scrollTop, bot = top + wrap.clientHeight;
      const where = y == null ? "" : y < top ? "up" : y > bot - 20 ? "down" : "on";
      const rowsAway = el ? Math.round(Math.abs((y < top ? top - y : y - bot) / (el.offsetHeight || 18))) : 0;
      const rw = reloadMoney(r, side);
      items.push({side, price: r.price, n: r[side + "_refills"] || 0, stage: r[side + "_stage"] || "RELOADING", where, rowsAway, knows: r[side + "_knows"] && r[side + "_knows"].knows, rw});
    }
  }
  // working orders that sit outside the ladder's rows (the still ladder keeps its rows while price moves):
  // never invisible — a tag says where they are, with the chip's cancel on it
  const prices = new Set(rows.map(r => +r.price)), lo = rows.length ? Math.min(...prices) : null, hi = rows.length ? Math.max(...prices) : null;
  const off = (d.orders || []).filter(o => o.price && !prices.has(+o.price) && lo != null).map(o => `<span class="rlb ord ${o.action === "BUY" ? "b" : "s"} ${o.price > hi ? "up" : "down"}" data-oid="${o.id}" title="${esc(o.type || "")} ${esc(o.role || "")} order, ${o.price > hi ? "above" : "below"} the rows on screen · click to cancel it">${o.price > hi ? "▲" : "▼"} YOUR ${esc(o.action)} ${sz(o.qty)} @ ${px(o.price)}${o.type && o.type !== "LMT" ? " " + esc(o.type) : ""} · ${o.price > hi ? "above" : "below"} the ladder ✕</span>`).join("");
  const noBook = rows.length && !rows.some(r => r.bid || r.ask);
  const nb = noBook ? `<span class="rlb nobook" title="Level II needs one of the ${(state && state.slots) || 3} book slots (LADDERS at the bottom). The ticker on screen takes one; give it a second.">NO BOOK YET FOR ${esc(d.symbol)} · bid and ask sizes come in a moment · the HIT / PAID numbers are what already traded</span>` : "";
  const html = nb + off + items.map(i => `<span class="rlb ${i.side === "bid" ? "b" : "s"} ${i.where}" data-jump="${i.price}" title="${esc(i.rw.text)} · ${i.stage} · click to jump to it">${i.where === "up" ? "▲" : i.where === "down" ? "▼" : "●"} RELOAD ${i.side === "bid" ? "BUYER" : "SELLER"}${i.rw.back ? ` BACK ×${i.rw.back.n} (gone ${Math.max(1, Math.round((i.rw.back.away || 0) / 60))}m)` : ""} ${px(i.price)} · ${i.side === "bid" ? "bought" : "sold"} ${kfmt(i.rw.n)} sh · ${usdK(i.rw.usd)}${i.rw.back && i.rw.all > i.rw.n ? ` · ${kfmt(i.rw.all)} all visits` : ""}${i.rw.peak && i.rw.n > i.rw.peak ? ` · never showed more than ${kfmt(i.rw.peak)} at once (large size, refilled ${i.n}×)` : ""}${i.where !== "on" ? ` · ${i.rowsAway} rows ${i.where}` : ""}${i.knows ? " ⚡" : ""}</span>`).join("");
  if (ban.dataset.h !== html){ ban.dataset.h = html; ban.innerHTML = html; ban.classList.toggle("on", !!(items.length || off || nb)); }
}
P.book.el.addEventListener("click", e => {
  const oc = e.target.closest(".rlb[data-oid]"); if (oc){ if (confirm("Cancel this order?")) cancelMine(+oc.dataset.oid); return; }
  const j = e.target.closest(".rlb[data-jump]"); if (!j) return;
  const wrap = P.book.pc.querySelector(".ladder-wrap"), row = wrap && wrap.querySelector(`tr[data-price="${j.dataset.jump}"]`);
  if (row){ bookUserScroll = Date.now(); wrap.scrollTop = row.offsetTop - wrap.clientHeight / 2; row.classList.add("flash"); rlBanner(wrap, curData()); }
});
P.book.el.addEventListener("scroll", () => { const wrap = P.book.pc.querySelector(".ladder-wrap"); const d = curData(); if (wrap && d) rlBanner(wrap, d); }, true);
function renderTape(d){
  const el = P.tape.pc.querySelector(".p-tape");
  renderContractTape(); renderSwitchStrips(); if (contractMode("tape")){ renderBigTape(d); return; }
  if (!d){ el.innerHTML = `<div class="dim" style="padding:8px">${NA}</div>`; P.tape.last = null; renderBigTape(null); return; }
  const html = refsHTML(null, d.story && d.story.edge) + tapeGaugeHTML(d.tape) + darkStripHTML(d.dark) + instStripHTML(d.inst) + tapeSpeedHTML(d.tape.speed) + paceHTML(d.tape.pace) + tapeHTML(d.tape, d.ladder); if (P.tape.last !== html){ P.tape.last = html;
    const keep = el.scrollTop; el.innerHTML = html; el.scrollTop = keep; makeColsResizable(el.querySelector("table")); }
  renderBigTape(d); flyBigPrints(d);
}
/* LARGE ORDERS on the T&S (off-exchange): today's dollars and their share of the volume, the last large order.
   Click: every large order (size, $, against the quote and VWAP) and the prices they keep printing at */
function darkStripHTML(dk){
  if (!dk || !dk.usd) return `<div class="dkstrip dim" data-dk="1">LARGE ORDERS · none yet today</div>`;
  const open = store.get("darkOpen", false), b = (dk.big || [])[0];
  const vv = v => v == null ? "" : Math.abs(v) < 0.005 ? "at VWAP" : `${(Math.abs(v) * 100).toFixed(0)}¢ ${v > 0 ? "over" : "under"} VWAP`;
  let h = `<div class="dkstrip" data-dk="1" title="large off-exchange orders: click for the list"><b>LARGE ORDERS</b> ${usdK(dk.usd)}${dk.pct != null ? ` · ${dk.pct}% of volume` : ""}${b ? ` · last big <b>${kfmt(b.size)} @ ${px(b.price)}</b> ${usdK(b.usd)}${b.vs_vwap != null ? " · " + vv(b.vs_vwap) : ""} · ${ago(b.age)} ago` : ""}<span class="dkcar">${open ? "▴" : "▾"}</span></div>`;
  if (open){
    h += `<div class="dkbox"><table class="dkt"><tr><th>AGO</th><th>SIZE</th><th>PRICE</th><th>$</th><th>QUOTE</th><th>VWAP</th></tr>` +
      ((dk.big || []).slice(0, 10).map(r => `<tr><td>${ago(r.age)}</td><td><b>${sz(r.size)}</b></td><td>${px(r.price)}</td><td><b>${usdK(r.usd)}</b></td><td class="dim">${esc(r.at || "")}</td><td class="${r.vs_vwap > 0.004 ? "s" : r.vs_vwap < -0.004 ? "b" : "dim"}">${r.vs_vwap == null ? "" : (r.vs_vwap >= 0 ? "+" : "−") + (Math.abs(r.vs_vwap) * 100).toFixed(0) + "¢"}</td></tr>`).join("") || `<tr><td colspan="6" class="dim">no large orders yet</td></tr>`) + `</table>` +
      `<div class="dkh">WHERE LARGE ORDERS KEEP PRINTING</div><table class="dkt">` + (dk.levels || []).slice(0, 6).map(x => `<tr><td>${px(x.price)}</td><td><b>${usdK(x.usd)}</b></td><td>${sz(x.shares)} sh</td><td class="dim">${x.prints} prints${x.big ? ` · ${x.big} large` : ""}</td></tr>`).join("") + `</table></div>`;
  }
  return h;
}
/* INST: the institutional footprint read on the T&S. The program (side, how many 5-min slots it won, its share of the
   volume, since when, the dollars, where it fills against VWAP), the pace for the time of day; click for the
   fund-style reloaders (same refill size) and a side walking the price */
function instStripHTML(ic){
  if (!ic) return "";
  const pg = ic.program, tod = ic.tod, open = store.get("instOpen", false);
  const vv = v => v == null ? "" : Math.abs(v) < 0.005 ? " · at VWAP" : ` · ${(Math.abs(v) * 100).toFixed(0)}¢ ${v < 0 ? "under" : "over"} VWAP`;
  const todTxt = tod ? `<span class="${tod.x >= 1.5 ? "hot" : tod.x <= 0.6 ? "cold" : ""}">pace ×${tod.x} for ${tod.at}</span>` : "";
  const kd = ic.kids;
  const kids = kd ? `<b class="${kd.side === "BUY" ? "b" : "s"} kids" title="CHILD ORDERS: the same size again and again on one side at a steady clock. One print looks like nothing; ${kd.n} of them is an algo working a ${kd.side === "BUY" ? "buyer" : "seller"}'s order. Those prints are marked ⚙ on the tape">⚙ ${kd.side === "BUY" ? "BUY" : "SELL"} PROGRAM ${kd.n}× ${sz(kd.size)} ${kd.side === "BUY" ? "at the ask" : "at the bid"} · every ${kd.every}s · ${sz(kd.shares)} sh since ${esc(kd.since || "")}</b> · ` : "";
  const main = kids + (pg ? `<b class="${pg.side === "BUY" ? "b" : "s"}" title="steady one-sided flow against the market, slot after slot, at a steady share of the volume: the way a VWAP / % of volume algo works a fund's order (or several buyers / sellers pressing)">STEADY ${pg.side === "BUY" ? "BUYING" : "SELLING"}</b> <span class="sc">${pg.score}</span> · ${pg.won}/${pg.slots} slots · ~${pg.part}% of vol · since ${pg.since} · net ${pg.side === "BUY" ? "bought" : "sold"} ≈${usdK(pg.usd)}${vv(pg.vs_vwap)}`
    : kd ? "" : `<span class="dim">no steady one-sided flow</span>`);
  const lv0 = (ic.levels || [])[0];
  const extra = (lv0 ? ` · <b class="${lv0.side === "bid" ? "b" : "s"}">FUND ${lv0.side === "bid" ? "BUYER" : "SELLER"} ${px(lv0.price)} ${lv0.score}</b>` : "") + (ic.walk ? ` · <b class="${ic.walk.side === "BUYER" ? "b" : "s"}">${ic.walk.side.toLowerCase()} walking ${ic.walk.dir}</b>` : "");
  const warn = ic.against ? `<div class="instwarn" data-inst="1" title="a program is running on the other side of your trade">⚠ ${esc(ic.against)}</div>` : "";
  const guide = (ic.guides || [])[0] ? `<div class="instguide" data-inst="1">${esc(ic.guides[0])}</div>` : "";
  let h = warn + `<div class="instrip" data-inst="1" title="institutional footprints: a fund's order sliced by an execution algo. Click for the details"><b class="ih">INST</b> ${main}${extra}${todTxt ? " · " + todTxt : ""}<span class="dkcar">${open ? "▴" : "▾"}</span></div>` + guide;
  if (open){
    const f = ic.levels || [];
    h += `<div class="dkbox inbox">` + (f.length ? `<div class="dkh">FUND SCORE BY LEVEL · same size · large size · walking · large orders · steady flow</div><table class="dkt">` + f.map(x => `<tr><td class="${x.side === "bid" ? "b" : "s"}"><b>${x.score}</b> ${x.side === "bid" ? "BUYER" : "SELLER"}</td><td>${px(x.price)}</td><td><b>${usdK(x.usd)}</b></td><td class="dim">${esc(x.why.join(" · "))}${x.here ? " · there now" : ""}</td></tr>`).join("") + `</table>` : `<div class="dim">no fund levels yet</div>`) +
      (ic.walk ? `<div class="dkh">WALKING ${ic.walk.dir === "down" ? "IT DOWN · distribution" : "IT UP · accumulation"}</div><div>${ic.walk.side === "SELLER" ? "Selling" : "Buying"} at ${ic.walk.steps.map(px).join(" → ")} · ${usdK(ic.walk.usd)}</div>` : "") +
      ((ic.guides || []).length > 1 ? `<div class="dkh">WHAT IT MEANS</div>` + ic.guides.map(g => `<div>${esc(g)}</div>`).join("") : "") +
      (pg ? `<div class="dkh">STEADY ${pg.side === "BUY" ? "BUYING" : "SELLING"} · program-like</div><div>${pg.side === "BUY" ? "Buyers" : "Sellers"} won ${pg.won} of the last ${pg.slots} five-minute slots (${pg.agree}%), net ~${pg.part}% of all volume, ${sz(pg.shares)} shares since ${pg.since}${vv(pg.vs_vwap)}. Steady, scaled to the volume: the way a VWAP / % of volume algo works a fund's order.</div>` : "") + `</div>`;
  }
  return h;
}
document.addEventListener("click", e => { if (!e.target.closest(".instrip[data-inst]")) return; store.set("instOpen", !store.get("instOpen", false)); if (P.tape) P.tape.last = null; const d0 = curData(); if (d0) renderTape(d0); });
document.addEventListener("click", e => { if (!e.target.closest(".dkstrip[data-dk]")) return; store.set("darkOpen", !store.get("darkOpen", false)); if (P.tape) P.tape.last = null; const d0 = curData(); if (d0) renderTape(d0); });
/* THE MONEY GAUGE: the last minute's dollars paid at the ask (buyers in a rush) against dollars hit at the bid */
function tapeGaugeHTML(t){
  const u = t.usd_60 || {buy: 0, sell: 0}, tot = u.buy + u.sell;
  if (!tot) return `<div class="tgauge dim">LAST MINUTE · no money through yet</div>`;
  const bp = Math.round(u.buy / tot * 100);
  return `<div class="tgauge" title="the last 60 seconds: dollars traded at the ask (paid up) vs at the bid (hit)"><span class="b">${usdK(u.buy)} BOUGHT</span><span class="bar"><i class="b" style="width:${bp}%"></i><i class="s" style="width:${100 - bp}%"></i></span><span class="s">${usdK(u.sell)} SOLD</span></div>`;
}
/* A BIG PRINT FLIES: when size comes off the ladder in a big print, a chip lifts off its row on LEVEL II and lands
   on top of TIME & SALES, so the eye follows the money from the book to the tape */
const FLOWN = new Map();
function flyBigPrints(d){
  if (!d || !d.tape || !P.book.el.offsetParent || !P.tape.el.offsetParent) return;
  const big = (d.ladder && d.ladder.big_shares) || 5000, now = Date.now();
  for (const [k, at] of FLOWN) if (now - at > 30000) FLOWN.delete(k);
  // a print INTO a reloader (a sell into a reload buyer's bid, a buy from a reload seller's ask) flies too, whatever
  // its size: his fills leave his row on the ladder and land, glowing, on the tape
  const rlAt = {};
  for (const x of ((d.ladder && d.ladder.rows) || [])){ if (x.bid_state === "RELOAD" || x.bid_proven) rlAt[x.price + "|sell"] = "b"; if (x.ask_state === "RELOAD" || x.ask_proven) rlAt[x.price + "|buy"] = "s"; }
  let n = 0;
  for (const r of (d.tape.recent || [])){
    const rlk = rlAt[(+r.price) + "|" + r.side];
    if (r.age > 2 || n >= Math.max(1, +store.get("flyMax", 4) || 4) || (r.size < big && !rlk)) continue;
    const key = `${d.symbol}|${r.price}|${r.size}|${r.exchange}|${Math.round((state.now - r.age) * 2)}`;
    if (FLOWN.has(key)) continue; FLOWN.set(key, now); n++;
    const row = P.book.el.querySelector(`.ladder-wrap tr[data-price="${r.price}"]`), dst = P.tape.el.querySelector(".tape2");
    if (!row || !dst) continue;
    const a = row.getBoundingClientRect(), b = dst.getBoundingClientRect();
    if (!a.width || !b.width) continue;
    const chip = document.createElement("div");
    chip.className = "flychip " + (r.side === "buy" ? "b" : r.side === "sell" ? "s" : "") + (rlk ? " rl" : "");
    chip.textContent = `${rlk ? `R ${rlk === "b" ? "BUYER" : "SELLER"} ` : ""}${r.side === "buy" ? "▲" : r.side === "sell" ? "▼" : "•"} ${kfmt(r.size)} @ ${px(r.price)}`;
    chip.style.left = (a.left + a.width / 2 - 50) + "px"; chip.style.top = (a.top) + "px";
    document.body.appendChild(chip);
    requestAnimationFrame(() => requestAnimationFrame(() => { chip.style.left = (b.left + 8) + "px"; chip.style.top = (b.top + 20) + "px"; chip.style.opacity = "0.15"; }));
    setTimeout(() => chip.remove(), 900);
  }
}
/* BIG TAPE: the second time & sales, under the first, filtered the way a trader filters for large orders and for
   anyone building a position. Top: BUILDERS — the same side hitting the same price over and over (3+ prints inside
   90 s adding up to big size): PAID UP at one price again and again is a buyer working an order there, HIT a
   seller unloading. Then the BLOCKS: every single print of big size (shares) or big money (dollars). */
function btCols(){ return Object.assign({who: false, times: true, shares: true, usd: false, age: true, blocks: true}, store.get("btcols", {})); }
function renderBigTape(d){
  const box = P.bigtape && P.bigtape.pc.querySelector(".p-bigtape"); if (!box) return;
  const body = box.querySelector(".bt-body");
  let bt = d && d.bigtape;
  if (!bt){ body.innerHTML = `<div class="dim" style="padding:4px 6px">${NA}</div>`; return; }
  const c = btCols(), who = s => s === "buy" ? "PAID UP" : "HIT";
  const minSh = btNum(store.get("btMinSh", "")), minUsd = btNum(store.get("btMinUsd", ""));
  const bigEnough = (shares, usd) => shares >= minSh && usd >= minUsd;
  bt = Object.assign({}, bt, {builders: bt.builders.filter(g => bigEnough(g.shares, g.dollars)), prints: bt.prints.filter(p => bigEnough(p.size, p.dollars))});
  // price · how many times · shares · (dollars) · LIVE / seconds — the colour says who: green paid up, red hit
  const cells = (side, price, times, shares, usd, age) => `<td class="px ${side}">${price}</td>${c.who ? `<td class="${side}">${who(side)}</td>` : ""}${c.times ? `<td class="${side}">${times}</td>` : ""}${c.shares ? `<td class="${side}"><b>${shares}</b></td>` : ""}${c.usd ? `<td class="${side}">${usd}</td>` : ""}${c.age ? `<td class="dim">${age}</td>` : ""}`;
  const n = 1 + (c.who ? 1 : 0) + (c.times ? 1 : 0) + (c.shares ? 1 : 0) + (c.usd ? 1 : 0) + (c.age ? 1 : 0);
  const bl = bt.builders.map(g => `<tr class="${g.side} bld ${g.still ? "live" : ""}" title="${g.side === "buy" ? "paid the ask" : "hit the bid"} at ${g.price} ${g.prints} times in ${g.first_age - g.last_age}s — ${sz(g.shares)} shares, ${usdK(g.dollars)}, biggest print ${sz(g.biggest)}. ${g.still ? "Still going (last print " + g.last_age + "s ago)." : "Went quiet " + g.last_age + "s ago."}">
      ${cells(g.side, g.price, "×" + g.prints, kfmt(g.shares), usdK(g.dollars), g.still ? "LIVE" : ago(g.last_age))}</tr>`).join("");
  const pr = c.blocks ? bt.prints.map(p => `<tr class="${p.side}" title="${who(p.side).toLowerCase()} ${sz(p.size)} shares at ${p.price} = ${usdK(p.dollars)}${p.exchange ? " · " + esc(p.exchange) : ""} · ${ago(p.age)} ago">
      ${cells(p.side, p.price, "", sz(p.size), usdK(p.dollars), ago(p.age))}</tr>`).join("") : "";
  const html = `<table class="t bt"><tr><th class="sec" colspan="${n}">BUILDERS</th></tr>${bl || `<tr><td colspan="${n}" class="dim">—</td></tr>`}
    ${c.blocks ? `<tr><th class="sec" colspan="${n}">BLOCKS</th></tr>${pr || `<tr><td colspan="${n}" class="dim">—</td></tr>`}` : ""}</table>`;
  if (body.dataset.h === html) return; body.dataset.h = html;
  const keep = body.scrollTop; body.innerHTML = html; body.scrollTop = keep;
}
// "5k", "2.5m", "250000" all read as numbers; blank = no extra filter
function btNum(v){ const m = /^\s*([\d.]+)\s*([kKmM]?)\s*$/.exec(String(v || "")); if (!m) return 0; return parseFloat(m[1]) * (m[2].toLowerCase() === "k" ? 1e3 : m[2].toLowerCase() === "m" ? 1e6 : 1); }
(function(){ for (const [id, key] of [["btMinSh", "btMinSh"], ["btMinUsd", "btMinUsd"]]){ const el = document.getElementById(id); if (!el) continue; el.value = store.get(key, "");
  el.addEventListener("change", () => { store.set(key, el.value.trim()); const b = P.bigtape && P.bigtape.pc.querySelector(".bt-body"); if (b) b.dataset.h = ""; renderBigTape(curData()); }); } })();
(function(){ const m = document.getElementById("btMenu"); if (!m) return; const btn = m.querySelector("button"), pop = document.getElementById("btPop");
  btn.addEventListener("click", e => { e.stopPropagation(); const open = !m.classList.contains("open"); document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); m.classList.toggle("open", open); const c = btCols(); pop.querySelectorAll("input[data-btc]").forEach(i => { i.checked = !!c[i.dataset.btc]; }); });
  pop.addEventListener("change", e => { const k = e.target.dataset.btc; if (!k) return; const c = store.get("btcols", {}); c[k] = e.target.checked; store.set("btcols", c); const b = P.bigtape.pc.querySelector(".bt-body"); if (b) b.dataset.h = ""; renderBigTape(curData()); }); })();
/* tape speed: how fast prints are coming right now against this stock's own last minute, plus the last 90 s as
   stacked bars (green = paid up, red = hit, grey = in between). Speeding into a move, drying up into a level. */
function tapeSpeedHTML(sp, unit){
  if (!sp) return "";
  const cls = {"SPEEDING UP": "up", "SLOWING": "down", "STEADY": "flat", "QUIET": "flat"}[sp.trend] || "flat";
  const ser = sp.series || [], n = ser.length || 1, W = 180, H = 26, bw = W / n;
  const tot = ser.map(r => r[0] + r[1] + r[2]), mx = Math.max(1, ...tot);
  let bars = "";
  ser.forEach((r, i) => {
    let y = H; const x = (i * bw + 0.5).toFixed(1), w = Math.max(1, bw - 1).toFixed(1);
    [[r[0], "var(--buy)"], [r[1], "var(--sell)"], [r[2], "var(--dim)"]].forEach(([v, c]) => {
      if (!v) return; const h = v / mx * H; y -= h;
      bars += `<rect x="${x}" y="${y.toFixed(1)}" width="${w}" height="${h.toFixed(1)}" fill="${c}"/>`;
    });
  });
  const ratio = sp.ratio != null ? sp.ratio : sp.base_pps > 0 ? sp.pps / sp.base_pps : null;
  return `<div class="tspeed ${cls}" title="${sp.ratio != null ? "PACE: SPEEDING UP / SLOWING = the last seconds against the ones before; x = this stock's pace against its own normal (the same read the voice uses)." : "Prints per second over the last 10 s, against the minute before it."} Bars: the last 90 s, ${sp.bucket} s each (green paid up, red hit, grey between). A tape that speeds up with price is the move; one that dries up into a level is the wait to see who holds it.">
    <span class="tsv"><b>${sp.pps.toFixed(1)}</b><i>PRINTS/S</i></span><span class="tsv"><b>${sz(sp.sps)}</b><i>${unit || "SH/S"}</i></span>
    <span class="tst">${sp.trend}${ratio != null && sp.trend !== "QUIET" ? ` <em>${ratio.toFixed(1)}x</em>` : ""}</span>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${bars}</svg></div>`;
}
// the BIG ≥ / DEFAULT / huge row on the stock LEVEL II: hidden unless turned on in COLS
function applyBigSet(){ const b = document.querySelector(".pnl[data-p=book] .bigset"); if (b) b.style.display = store.get("bigset", false) === true ? "" : "none"; }
applyBigSet();
function applyLadCols(tbl){ if (!tbl) return; const c = store.get("ladcols", {}); const wrap = tbl.closest(".ladder-wrap"); if (wrap){ wrap.style.setProperty("--ladz", String(store.get("ladz", 1))); wrap.style.setProperty("--ladh", String(store.get("ladh", 1))); } tbl.classList.toggle("notrade", c.trade !== true); tbl.classList.toggle("nobars", c.bars === false); tbl.classList.toggle("nowho", c.who === false); tbl.classList.toggle("noflow", c.flow === false); if (tbl._applyCols) tbl._applyCols(); }
document.getElementById("colsMenu").querySelector("button").addEventListener("click", e => { e.stopPropagation(); const m = document.getElementById("colsMenu"), open = !m.classList.contains("open"); document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); m.classList.toggle("open", open); const c = store.get("ladcols", {}); const rs = m.querySelector("select[data-rows]"); if (rs) rs.value = String(store.get("ladRows", 12)); const lc = m.querySelector("select[data-ladclick]"); if (lc) lc.value = store.get("ladClick", "join"); const hs = m.querySelector("select[data-ladh]"); if (hs) hs.value = String(store.get("ladh", 1)); m.querySelectorAll("input[data-col]").forEach(i => { i.checked = i.dataset.col === "trade" ? c.trade === true : c[i.dataset.col] !== false; }); const z = m.querySelector("select[data-ladz]"); if (z) z.value = String(store.get("ladz", 1)); const bs = m.querySelector("input[data-bigset]"); if (bs) bs.checked = store.get("bigset", false) === true; const sl = m.querySelector("input[data-storyline]"); if (sl) sl.checked = store.get("storyline", true) !== false; });
document.getElementById("colsPop").addEventListener("change", e => {
  if (e.target.dataset.rows != null){ store.set("ladRowsAuto", false); post("/api/ladder", {half_rows: +e.target.value}); store.set("ladRows", +e.target.value); P.book.last = null; poll(true); return; }   // your pick: the ladder stops sizing itself
  if (e.target.dataset.ladclick != null){ store.set("ladClick", e.target.value); return; }
  if (e.target.dataset.ladh != null){ store.set("ladh", +e.target.value || 1); applyLadCols(P.book.pc.querySelector("table.lad")); return; }
  if (e.target.dataset.storyline != null){ store.set("storyline", e.target.checked); P.book.last = null; poll(true); return; }
  if (e.target.dataset.bigset != null){ store.set("bigset", e.target.checked); applyBigSet(); return; }
  if (e.target.dataset.ladz != null){ store.set("ladz", +e.target.value || 1); applyLadCols(P.book.pc.querySelector("table.lad")); P.book.last = null; poll(true); return; } const k = e.target.dataset.col; if (!k) return; const c = store.get("ladcols", {}); c[k] = e.target.checked; store.set("ladcols", c); applyLadCols(P.book.pc.querySelector("table.lad")); });
function renderLadQty(s){
  const t = (s && s.trading) || {}, q = document.getElementById("ladQty"), pr = document.getElementById("ladPresets"); if (!q) return;
  if (document.activeElement !== q && t.default_shares && +q.value !== t.default_shares) q.value = t.default_shares;
  const html = (t.qty_presets || [25, 50, 100, 200, 500, 1000]).map(n => `<button data-qp="${n}" class="${t.default_shares === n ? "on" : ""}">${n >= 1000 ? (n / 1000) + "k" : n}</button>`).join("");
  if (pr.dataset.h !== html){ pr.dataset.h = html; pr.innerHTML = html; }
}
async function setLadQty(n){ n = Math.max(1, Math.round(+n || 0)); if (!n) return; TK.qty = n; const out = await post("/api/trade/size", {shares: n}); if (!out.ok) toast("Size not set: " + (out.reason || ""), false); P.ticket.last = null; renderTicket(state, curData(), true); poll(true); }
document.getElementById("ladQty").addEventListener("change", e => setLadQty(e.target.value));
document.getElementById("ladQty").addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter"){ setLadQty(e.target.value); e.target.blur(); } });
document.getElementById("ladPresets").addEventListener("click", e => { const b = e.target.closest("button[data-qp]"); if (b) setLadQty(b.dataset.qp); });
(function(){ const b = document.getElementById("ladMode"); if (!b) return; const MODES = ["clean", "candle", "basket", "pro", "simple", "tight", "wide"];
  if (!store.get("ladClean1", false)){ store.set("ladClean1", true); store.set("ladMode", "clean"); }   // the CLEAN ladder arrives as the default once
  const paint = () => { b.textContent = store.get("ladMode", "clean").toUpperCase(); }; paint();
  b.addEventListener("click", () => { const m = store.get("ladMode", "clean"); store.set("ladMode", MODES[(MODES.indexOf(m) + 1) % MODES.length]); paint(); P.book.last = null; poll(true); }); })();
/* PIN BOX: the tape and the ladder move too fast to hover. Click a print, a reload $ cell, a FLOW tag or a price
   and what you would have read on hover stays in a small box at the bottom of that panel until the next click. */
function pinBox(panel){ let b = panel.pc.querySelector(".pinbox"); if (!b){ b = document.createElement("div"); b.className = "pinbox"; b.innerHTML = `<span class="txt"></span><button class="x" title="clear">✕</button>`; panel.pc.appendChild(b); b.querySelector(".x").addEventListener("click", () => { b.classList.remove("on"); b.querySelector(".txt").textContent = ""; }); } return b; }
function pinInfo(panel, el){ const t = el && (el.getAttribute("title") || (el.closest("[title]") || {}).getAttribute && el.closest("[title]").getAttribute("title")); if (!t) return false; const b = pinBox(panel); b.querySelector(".txt").textContent = t; b.classList.add("on"); return true; }
P.tape.el.addEventListener("click", e => { const tr = e.target.closest("tr[title]"); if (tr) pinInfo(P.tape, tr); });
if (P.bigtape) P.bigtape.el.addEventListener("click", e => { const tr = e.target.closest("tr[title]"); if (tr) pinInfo(P.bigtape, tr); });
P.book.el.addEventListener("click", e => { if (e.target.closest("td[data-act], .chip, button, input, select, th")) return; const cell = e.target.closest("td.flow, td.bars, td.px, td.whoc"); if (!cell) return;
  const t = cell.matches("td.px") ? null : (cell.querySelector("[title]") || (cell.hasAttribute("title") ? cell : null));
  if (cell.matches("td.px") && cell.closest("table.simple")){ const row = cell.closest("tr"), bb = row.querySelector("td.bsz"), aa = row.querySelector("td.asz"), b = pinBox(P.book);
    b.querySelector(".txt").textContent = `${px(+row.dataset.price)} — BID: ${bb && bb.getAttribute("title") || "nothing"} · ASK: ${aa && aa.getAttribute("title") || "nothing"}`; b.classList.add("on"); return; }
  if (t && pinInfo(P.book, t)) return;
  // a price with nothing of its own: the whole row, everything the hover would have told you, in one line
  const row = cell.closest("tr"), r = row && row.dataset.price, b = pinBox(P.book);
  const bits = [...row.querySelectorAll("[title]")].filter(x => !x.closest("td[data-act]") && !x.matches("button")).map(x => x.getAttribute("title")).filter(Boolean);
  const bid = row.querySelector("td.bsz .szn"), ask = row.querySelector("td.asz .szn");
  b.querySelector(".txt").textContent = `${px(+r)}: bid ${bid && bid.textContent || "—"} · ask ${ask && ask.textContent || "—"}` + (bits.length ? " · " + bits.join(" · ") : " · nothing traded or reloaded here yet"); b.classList.add("on"); });
P.book.el.addEventListener("change", async e => { if (e.target.id !== "bigIn" || !curSym) return; const v = Math.max(100, +e.target.value || 0); const out = await post("/api/ladder", {symbol: curSym, big_shares: v}); toast(out.ok ? curSym + ": big size is now " + sz(v) + " shares" : "Could not set", out.ok); poll(true); });
P.book.el.addEventListener("click", async e => { if (e.target.id !== "bigReset" || !curSym) return; const out = await post("/api/ladder", {symbol: curSym, big_shares: null}); toast(out.ok ? curSym + ": big size back to the config default" : "Could not reset", out.ok); poll(true); });
function renderPS60(d){
  if (!d){ panelHTML("ps60", `<div class="dim">${NA}</div>`); return; }
  const g = d.ps60 || {}, se = g.se || {}, mp = g.mp || {};
  panelHTML("ps60", `<div class="hl">${esc(d.headline || "")}</div>
    <div class="kv"><span>GRADE</span><span><span class="p-ps60" style="margin:0;height:auto;overflow:visible"><span class="g ${g.grade}">${g.grade || NA}</span></span> <span class="dim">${esc(g.why || "")}</span></span>
      <span>PIVOT</span><span>${px(d.play.trigger)} · 2nd ${px(d.play.second_entry)} · stop ${px(d.play.stop)}</span>
      <span>MP</span><span>${mp.level != null ? px(mp.level) + " · $" + (mp.dollars || 0).toFixed(2) + " of room" : NA}${mp.verdict === "CLEAR" || mp.verdict === "THIN" ? " · " + mp.verdict + " vs ATR" : ""}</span>
      <span>2ND ENTRY</span><span>${esc(se.text || NA)}</span>
      <span>FLOW</span><span>${doughHTML(g.dough)}</span>
      <span>TAPE</span><span>${esc((d.tape && d.tape.state) || "QUIET")}${d.tape && d.tape.buy_pct != null ? " · " + d.tape.buy_pct.toFixed(0) + "% buys" : ""}</span></div>
    <ul>${(d.lines || []).map(l => `<li>${esc(l)}</li>`).join("")}</ul>
    ${(g.sneaky || []).map(x => `<div class="dim">${esc(x.label)} ${px(x.price)} ×${x.touches} · room $${x.room.toFixed(2)}</div>`).join("")}
    ${se.extreme && ["BROKE", "RETRACE"].includes(se.state) ? `<button data-se="${se.extreme}" style="margin-top:4px">use ${px(se.extreme)} as 2nd entry</button>` : ""}`);
}
/* NO FLOW, NO DOUGH: the flow confirmation line, one look */
function doughHTML(dg){
  if (!dg) return NA;
  const cls = dg.state === "FLOW CONFIRMED" ? "ok" : dg.state === "FLOW AGAINST" ? "no" : dg.state === "FLOW STARTING" ? "gold" : "dim";
  const ic = dg.state === "FLOW CONFIRMED" ? "💰 " : dg.state === "FLOW AGAINST" ? "⛔ " : dg.state === "FLOW STARTING" ? "… " : "";
  return `<b class="${cls}" title="${esc(dg.text)}">${ic}${esc(dg.state === "NO FLOW" ? "NO FLOW, NO DOUGH" : dg.state)}</b> <span class="dim">${esc(dg.text)}</span>`;
}
/* ---------- PLAY SETUP: pivot, stop, MP level (the target), optional 2nd entry — everything derives from it */
const SU = {dirty: false, msg: "", saving: false};
const SETUPS = ["Macro break (60m supply)", "Macro breakdown (60m demand)", "Large MP", "Second entry", "Remount", "Sneaky pivot", "50-day breakout", "50-day breakdown", "200-day break", "MA bounce", "MA rejection", "Gap and go", "Gap fill", "Squeeze", "Capitulation bounce", "Range break", "Scalp", "Other"];
// shares within BOTH your caps: max shares per order and max dollars per order
function capShares(n, price){
  const t = (state && state.trading) || {};
  let cap = t.max_shares || Infinity;
  if (t.max_dollars && price > 0) cap = Math.min(cap, Math.floor(t.max_dollars / price));
  return Math.max(0, Math.min(n, cap));
}
const setupSel = (id, cur, extra) => `<select ${id ? `id="${id}"` : ""} ${extra || ""}><option value="">— setup —</option>${SETUPS.map(x => `<option value="${x}" ${cur === x ? "selected" : ""}>${x}</option>`).join("")}</select>`;
function riskDollars(){ return +store.get("riskDollars", 100) || 0; }
let RISK_SYNC = null;
function syncRisk(){ clearTimeout(RISK_SYNC); RISK_SYNC = setTimeout(() => post("/api/trade/risk", {dollars: riskDollars()}), 400); }   // the auto 2nd entry is sized from it on the server
function suFields(){
  const f = {}; for (const k of ["trigger", "second_entry", "stop", "target"]){ const el = document.getElementById("su_" + k); if (el) f[k] = el.value.trim(); }
  const side = document.getElementById("su_side"), notes = document.getElementById("su_notes"), su = document.getElementById("su_setup");
  if (side) f.side = side.value; if (notes) f.notes = notes.value; if (su) f.setup = su.value;
  return f;
}
function suDerive(d, f){
  const n = k => { const v = parseFloat(f[k]); return isNaN(v) || v <= 0 ? null : v; };
  const side = f.side || "long", sgn = side === "long" ? 1 : -1;
  const pivot = n("trigger"), stop = n("stop"), mp = n("target");
  // the entry the numbers run from: YOUR second entry if you typed one, else the one PS60 found once the pivot broke
  // (new high / low, a real retrace, back through it). Until then the pivot only stands in, and says so.
  const se = d && d.ps60 && d.ps60.se, found = se && se.state === "SECOND_ENTRY" && +se.second_entry > 0 ? +se.second_entry : null;
  const second = n("second_entry") || found;
  const entry = second || pivot || (d && d.last) || null, entryLbl = n("second_entry") ? "2nd entry" : found ? "2nd entry (found)" : pivot ? "pivot (no 2nd entry yet)" : "last";
  const seState = !pivot ? "NEEDS A PIVOT" : !se ? "" : se.state === "SECOND_ENTRY" ? `2ND ENTRY ${px(se.second_entry)} · ${se.build || ""}` : se.state === "RETRACE" ? `RETRACED to ${px(se.retrace)} · 2nd entry = back through ${px(se.extreme)}` : se.state === "BROKE" ? `PIVOT BROKE · ${side === "long" ? "high" : "low"} ${px(se.extreme)} · waiting for the retrace` : "WAITING FOR THE PIVOT TO BREAK";
  const risk = entry && stop ? Math.abs(entry - stop) : null;
  const room = mp && pivot ? Math.abs(mp - pivot) : null;                 // MP room: pivot to your MP level
  const reward = mp && entry ? sgn * (mp - entry) : null;               // what you make from where you get in (signed)
  const r = risk && reward > 0 ? reward / risk : null;
  const shares = risk ? capShares(Math.floor(riskDollars() / risk), entry) : null;
  const bad = [];
  if (pivot && second && sgn * (second - pivot) <= 0) bad.push("second_entry");
  // the stop sits on the risk side of the entry you take: your 2nd entry when one is drawn (a short's stop above
  // its 2nd entry can sit UNDER the pivot — that is the PS60 stop), else the pivot
  const stopRef = n("second_entry") || pivot, stopRefLbl = n("second_entry") ? "2nd entry" : "pivot";
  if (stop && stopRef && sgn * (stopRef - stop) <= 0) bad.push("stop");
  if ((pivot && mp && sgn * (mp - pivot) <= 0) || (mp && entry && sgn * (mp - entry) <= 0)) bad.push("target");
  return {side, pivot, second, stop, mp, entry, entryLbl, risk, room, r, shares, bad, seState, fromSecond: !!second, stopRefLbl};
}
// the play's OTHER SIDE (a short under a long, a long over a short): its levels, its entry order, and a clear button
function otherSideHTML(d){
  const alt = d.play && d.play.alt; if (!alt) return "";
  const a = ((state && state.trading) || {}).auto || {}, st = a[d.symbol + "|alt"], side = d.play.side === "long" ? "SHORT" : "LONG";
  const f = (k, l) => alt[k] ? `<span>${l} <b>${px(alt[k])}</b></span>` : `<span class="dim">${l} —</span>`;
  const cls = st && (st.state === "WORKING" || st.state === "PARTIAL") ? "ok" : st && st.state === "DONE" ? "gold" : "";
  return `<div class="auto other"><b class="${side === "SHORT" ? "s" : "b"}">${side === "SHORT" ? "SHORT ▼" : "LONG ▲"} SIDE</b>${f("trigger", "pivot")}${f("second_entry", "2nd")}${f("stop", "stop")}${f("target", "target")}
    ${st ? `<span class="${cls}"><b>${esc(st.state)}</b> ${esc(st.text || "")}</span>` : ""}<button data-clearalt="1" title="take the ${side.toLowerCase()} side off the chart (its entry order is cancelled)">✕</button></div>`;
}
document.addEventListener("click", async e => { if (!e.target.closest("button[data-clearalt]") || !curSym) return;
  const d = curData(); if (!d || !d.play || !d.play.alt) return;
  for (const r of ["second_entry", "stop", "target", "trigger"]) if (d.play.alt[r]) await post("/api/level", {symbol: curSym, role: "alt_" + r, price: null});
  toast(curSym + ": other side cleared", true); P.setup.last = null; poll(true); });
function autoEntryHTML(d){
  // the 2nd entry you draw is an automatic entry: what the desk has working for it right now, and why not when it has nothing
  const t = (state && state.trading) || {}, a = (t.auto || {})[d.symbol];
  if (!a) return "";
  const cls = a.state === "WORKING" || a.state === "PARTIAL" ? "ok" : a.state === "DONE" ? "gold" : a.state === "OFF" ? "dim" : a.state === "TRIGGERED" ? "no" : "";
  return `<div class="auto ${a.on ? "" : "off"}" id="suAuto"><label title="on: when a 2nd entry, a stop and a target are on the chart and the desk is ARMED, a stop-limit entry is placed through the 2nd entry with the stop and target attached, sized from your risk $. One entry per drawn level."><input type="checkbox" id="suAutoOn" ${a.on ? "checked" : ""}> AUTO 2ND ENTRY</label>
    <span class="${cls}"><b>${esc(a.state)}</b> ${esc(a.text || "")}</span>${a.state === "WAITING" && a.qty ? ` <span class="dim">· ${sz(a.qty)} sh when it goes</span>` : ""}</div>${otherSideHTML(d)}`;
}
function suDerivedHTML(d, f){
  const x = suDerive(d, f), $ = v => v == null ? NA : "$" + v.toFixed(2);
  return `<span>2ND ENTRY</span><span>${x.seState ? `<span class="${x.fromSecond ? "ok" : "dim"}">${esc(x.seState)}</span>` : NA}</span>
    <span>FLOW</span><span>${doughHTML(d && d.ps60 && d.ps60.dough)}</span>
    <span>TRAPPED</span><span>${(() => { const x = d && d.daytrap; if (!x) return NA; const cls = /HEAVY/.test(x.state) ? "no" : x.state ? "gold" : "dim"; return `<span class="${cls}" title="${esc(x.text || "")}">${esc(x.state || "nobody underwater on the day")}</span>${x.side === "long" && x.longs ? ` <span class="dim">${kfmt(x.longs.shares)} sh bought above here · avg ${px(x.longs.avg)} · ${x.longs.under_pct}% under · their exit ${px(x.longs.avg)}</span>` : x.side === "short" && x.shorts ? ` <span class="dim">${kfmt(x.shorts.shares)} sh sold below here · avg ${px(x.shorts.avg)} · ${x.shorts.under_pct}% under · their exit ${px(x.shorts.avg)}</span>` : ""}${(() => { const f = x.flow; if (!x.side || !f || !f.verdict) return x.side ? ` <span class="dim">· no option flow on it</span>` : ""; const what = x.side === "long" ? "puts" : "calls", other = x.side === "long" ? "calls" : "puts"; if (f.verdict === "PRESSES") return ` <span class="ok" title="option money is leaning the way the trapped crowd must exit">· FLOW PRESSES THEM ${kfmt(f.presses)} ${what}${f.fades ? " vs " + kfmt(f.fades) + " " + other : ""}</span>`; if (f.verdict === "FADES") return ` <span class="no" title="somebody is paying for the trapped side to get out">· FLOW FADES THE TRAP ${kfmt(f.fades)} ${other}${f.presses ? " vs " + kfmt(f.presses) + " " + what : ""}</span>`; return ` <span class="dim">· flow mixed ${kfmt(f.calls)} calls / ${kfmt(f.puts)} puts</span>`; })()}`; })()}</span>
    <span>ORDER FLOW</span><span>${(() => { const o = d && d.orderflow; if (!o) return NA; const cls = /BUYING/.test(o.state) ? "ok" : /SELLING/.test(o.state) ? "no" : "dim"; return `<span class="${cls}">${esc(o.state)} ${esc(o.arrow || "")}</span>${o.momentum ? ` <span class="gold">${esc(o.momentum)}</span>` : ""} <span class="dim" title="${esc(o.basis_note || "")}">${esc(o.basis)}</span>`; })()}</span>
    <span>5 SEC / 15 SEC</span><span>${(() => { const o = d && d.orderflow; if (!o) return NA; const f = v => (v >= 0 ? "+" : "−") + sz(Math.abs(v)); return `<span class="mono ${o.short_delta >= 0 ? "up" : "dn"}">${f(o.short_delta)}</span> <span class="dim">/</span> <span class="mono ${o.long_delta >= 0 ? "up" : "dn"}">${f(o.long_delta)}</span> <span class="dim">shares, buyers paid up minus sellers hit</span>`; })()}</span>
    <span>MP ROOM</span><span>${x.room != null ? `<span class="gold">${$(x.room)}</span> <span class="dim">PIVOT ${$(x.pivot)} → TARGET ${$(x.mp)}</span>` : `<span class="dim">NEEDS A PIVOT AND A TARGET</span>`}</span>
    <span>RISK / SHARE</span><span>${x.risk ? `${$(x.risk)} <span class="dim">${x.entryLbl} ${$(x.entry)} → stop ${$(x.stop)}</span>` : `<span class="dim">NEEDS A STOP${x.entry ? "" : " AND AN ENTRY"}</span>`}</span>
    <span>REWARD : RISK</span><span>${x.r ? `<span class="${x.r >= 2 ? "ok" : x.r >= 1 ? "" : "no"}">${x.r.toFixed(1)} R</span> <span class="dim">${x.entryLbl} → TARGET ÷ RISK${x.fromSecond ? "" : " · real number comes with the 2nd entry"}</span>` : NA}</span>
    <span>SIZE</span><span>${x.shares != null ? `<span class="gold">${sz(x.shares)} sh</span> <span class="dim">AT $${riskDollars()} RISK</span> <button data-usesize="${x.shares}" style="padding:1px 6px;font-size:10px">TO TICKET</button>` : `<span class="dim">NEEDS A STOP</span>`}</span>
    ${x.bad.length ? `<span></span><span class="no">${x.bad.map(k => k === "second_entry" ? "2nd entry must be beyond the pivot" : k === "stop" ? (f.side === "short" ? `stop must be above the ${x.stopRefLbl} for a short` : `stop must be below the ${x.stopRefLbl} for a long`) : (f.side === "short" ? "target must be below the pivot for a short" : "target must be above the pivot for a long")).join(" · ")}</span>` : ""}`;
}
function suRefresh(){ const el = document.getElementById("suDerived"); if (!el) return; const f = suFields(); el.innerHTML = suDerivedHTML(curData(), f); const x = suDerive(curData(), f); for (const k of ["second_entry", "stop", "target"]){ const i = document.getElementById("su_" + k); if (i) i.classList.toggle("bad", x.bad.includes(k)); } const b = document.getElementById("suSave"); if (b) b.disabled = SU.saving || x.bad.length > 0; }
function renderSetup(d){
  if (!d){ SU.dirty = false; panelHTML("setup", `<div class="dim" style="padding:8px">${NA}</div>`); return; }
  if (SU.dirty && P.setup.pc.querySelector("#suSave") && P.setup.pc.dataset.sym === curSym) return;   // never wipe what the trader is typing
  const p = d.play || {}, v = k => p[k] != null ? p[k] : "";
  const f = {side: p.side || "long", trigger: v("trigger"), second_entry: v("second_entry"), stop: v("stop"), target: p.target != null ? p.target : v("mp"), notes: p.notes || ""};
  const inp = (k, ph) => `<input id="su_${k}" type="number" step="0.01" min="0" value="${f[k]}" placeholder="${ph}">`;
  // the x beside an optional level clears it from the chart and the play at once (a change of mind)
  const clr = k => f[k] !== "" ? `<button class="suclr" data-clear="${k}" title="remove this level from the chart and the play">✕</button>` : "";
  const html = `<div class="ticket setup">
    <div class="hdr"><span><b>${esc(d.symbol)}</b> PLAY</span><span>LAST ${px(d.last)}</span></div>
    <label>SIDE</label><select id="su_side"><option value="long" ${f.side === "long" ? "selected" : ""}>LONG</option><option value="short" ${f.side === "short" ? "selected" : ""}>SHORT</option></select>
    <label>PIVOT</label>${inp("trigger", "")}
    <label>2ND ENTRY</label><div class="row">${inp("second_entry", "optional")}${clr("second_entry")}</div>
    <label>STOP</label><div class="row">${inp("stop", "")}${clr("stop")}</div>
    <label>TARGET</label><div class="row">${inp("target", "your take profit")}${clr("target")}</div>
    <label>RISK $</label><div class="row"><input id="su_risk" type="number" step="10" min="0" value="${riskDollars()}"><span class="dim" style="font-size:10.5px">PER TRADE</span></div>
    <label>SETUP</label>${setupSel("su_setup", p.setup || "", 'title="what kind of PS60 play this is; every trade on it is filed under this in the journal"')}
    <label>NOTES</label><input id="su_notes" type="text" maxlength="200" value="${esc(f.notes)}" placeholder="notes">
    <div class="derived" id="suDerived">${suDerivedHTML(d, f)}</div>
    ${autoEntryHTML(d)}
    <div class="go"><button class="save" id="suSave">SAVE PLAY</button><button id="suClear" class="danger" title="wipe the pivot, 2nd entry, stop, target and extra levels off this chart (the ticker stays on the desk)">CLEAR PLAY</button></div>
    <div class="msg ${SU.msg.startsWith("SAVED") ? "ok" : "no"}" id="suMsg">${esc(SU.msg)}</div></div>`;
  const pc = P.setup.pc;
  if (!pc.querySelector("#suForm")){
    pc.innerHTML = `<div id="suForm"></div><div class="tlog" id="suLog"><div class="tlog-hd"><span>TRADE LOG <b id="tlogSym"></b></span><span class="dim">levels you set · what you say · what you type</span></div>
      <div class="tlog-in"><input id="tlogIn" placeholder="type a note, Enter" maxlength="600" spellcheck="false"><button id="tlogMic" title="talk: what you say lands here as a journal entry (and on the recording when one is on)">🎙 MIC</button></div><div class="tlog-list" id="tlogList"></div></div>`;
    P.setup.last = null;
  }
  const form = pc.querySelector("#suForm");
  if (form.dataset.h !== html){ form.dataset.h = html; form.innerHTML = html; pc.dataset.sym = curSym; }
  renderTradeLog(d);
}
function renderTradeLog(d){
  const list = document.getElementById("tlogList"), hd = document.getElementById("tlogSym"); if (!list) return;
  if (hd.textContent !== (d.symbol || "")) hd.textContent = d.symbol || "";
  const rows = (d.log || []).slice().reverse();
  const icon = k => k === "voice" ? "🎙" : k === "level" ? "⟶" : "✎";
  const html = rows.length ? rows.map(n => `<div class="tl ${esc(n.kind || "typed")}"><span class="tm">${nyHM(n.t)}</span><span class="ic">${icon(n.kind)}</span><span class="tx">${esc(n.text)}</span></div>`).join("")
    : `<div class="dim" style="padding:6px 2px">Nothing yet. Set a level, press MIC and talk, or type a line.</div>`;
  if (list.dataset.h !== html){ list.dataset.h = html; list.innerHTML = html; }
  const mic = document.getElementById("tlogMic"); if (mic){ mic.classList.toggle("on", MIC.on); mic.textContent = MIC.on ? "● STOP" : "🎙 MIC"; }
}
async function tlogSend(){
  const inp = document.getElementById("tlogIn"), text = (inp.value || "").trim(); if (!text || !curSym) return;
  const out = await post("/api/desk/journal", {symbol: curSym, text});
  if (out.ok){ inp.value = ""; poll(true); } else toast("Note not saved", false);
}
document.getElementById("app").addEventListener("keydown", e => { if (e.target.id !== "tlogIn") return; e.stopPropagation(); if (e.key === "Enter") tlogSend(); if (e.key === "Escape") e.target.blur(); });
document.getElementById("app").addEventListener("click", async e => {
  if (e.target.id === "tlogMic"){ MIC.on ? micStop() : micStart(); return; }
  const c = e.target.closest("button[data-clear]"); if (!c || !curSym) return;
  const k = c.dataset.clear, names = {second_entry: "2nd entry", stop: "stop", target: "target"};
  const out = await post("/api/level", {symbol: curSym, role: k, price: null});
  toast(out.ok ? `${curSym} ${names[k]} removed` : "Could not remove the " + names[k], out.ok);
  SU.dirty = false; P.setup.last = null; poll(true);
});
document.getElementById("sideBtn").addEventListener("click", async () => {
  const d = curData(); if (!d || !d.play || !curSym) return;
  const side = d.play.side === "short" ? "long" : "short", out = await post("/api/play", {symbol: curSym, action: "side", side});
  const warn = (out.warnings || []).join(" · ");
  toast(out.ok ? `${curSym} is a ${side.toUpperCase()}${warn ? " — redraw: " + warn : ""}` : "Side not changed: " + (out.reason || ""), out.ok && !warn);
  SU.dirty = false; P.setup.last = null; poll(true);
});
P.setup.el.addEventListener("change", async e => {
  // SIDE applies the moment you pick it: the levels on the chart stay, the desk re-reads them for the new side
  if (e.target.id !== "su_side" || !curSym) return;
  const side = e.target.value, out = await post("/api/play", {symbol: curSym, action: "side", side});
  const warn = (out.warnings || []).join(" · ");
  SU.dirty = false; SU.msg = out.ok ? (warn ? `${side.toUpperCase()} · redraw: ${warn}` : `${side.toUpperCase()} · levels read for a ${side}`) : "REJECTED · " + (out.reason || "not saved");
  toast(out.ok ? `${curSym} is a ${side.toUpperCase()}${warn ? " — " + warn : ""}` : "Side not changed: " + (out.reason || ""), out.ok && !warn);
  P.setup.last = null; poll(true);
});
P.setup.el.addEventListener("input", e => { if (e.target.id === "su_risk"){ store.set("riskDollars", +e.target.value || 0); syncRisk(); P.ticket.last = null; renderTicket(state, curData()); } else SU.dirty = true; SU.msg = ""; const m = document.getElementById("suMsg"); if (m) m.textContent = ""; suRefresh(); });
P.setup.el.addEventListener("click", async e => {
  const u = e.target.closest("button[data-usesize]"); if (u){ TK.qty = Math.max(1, +u.dataset.usesize); P.ticket.last = null; renderTicket(state, curData()); post("/api/trade/size", {shares: TK.qty}); toast("Ticket size " + sz(TK.qty) + " shares", true); return; }
  if (e.target.id === "suClear" && curSym){
    if (!confirm(`Clear every level off ${curSym}? The pivot, 2nd entry, stop, target and extra lines go; the ticker stays on the desk.`)) return;
    const out = await post("/api/play", {symbol: curSym, action: "clear"});
    toast(out.ok ? curSym + " cleared — blank chart" : "Could not clear " + curSym, out.ok);
    SU.dirty = false; P.setup.last = null; poll(true); return;
  }
  if (e.target.id === "suAutoOn" && curSym){
    const out = await post("/api/trade/auto", {symbol: curSym, on: e.target.checked});
    toast(out.ok ? `${curSym} auto 2nd entry ${e.target.checked ? "ON" : "OFF"}` : "Could not switch", out.ok); poll(true); return;
  }
  if (e.target.id !== "suSave" || !curSym) return;
  saveSetup(false);
});
// PLAY SETUP saves itself: leave a box (Tab, Enter, click away) or pick from a list and the play is saved — the
// grade, the brackets, the conviction board and the ticket sizing follow at once. SAVE PLAY still works.
async function saveSetup(auto){
  if (!curSym || SU.saving) return;
  const sym = curSym, f = suFields();
  delete f.side;     // SIDE saves on its own when you pick it; the levels decide the side unless you picked it (L/S or SIDE)
  SU.saving = true; suRefresh();
  const out = await post("/api/play", {symbol: sym, action: "setup", fields: f});
  SU.saving = false;
  if (out.ok){ SU.dirty = false; SU.msg = auto ? "SAVED" : "SAVED · grade, brackets and sizing follow these numbers"; }
  else SU.msg = "NOT SAVED · " + (out.reason || "rejected");
  P.setup.last = null;
  if (!auto || !out.ok) toast(out.ok ? "Play saved for " + sym : "Not saved: " + (out.reason || ""), out.ok);
  poll(true);
}
let suAutoT = null;
P.setup.el.addEventListener("change", e => {
  if (!e.target.matches("input, select, textarea") || ["su_risk", "suAutoOn", "su_side"].includes(e.target.id)) return;
  clearTimeout(suAutoT); suAutoT = setTimeout(() => saveSetup(true), 250);
});
function renderReloads(d){
  if (!d){ panelHTML("reload", `<div class="dim">${NA}</div>`); return; }
  if (training()){ panelHTML("reload", `<div class="dim" style="padding:10px;line-height:1.5"><b style="color:var(--gold)">TRAINING</b> · the desk is not calling reloads for you. Read the tape and the ladder, mark your call with M, then check it.<br><button data-reveal="1" style="margin-top:8px">REVEAL 20s</button></div>`); return; }
  const lv = (d.levels || []).filter(l => l.state === "RELOAD" || l.proven || l.last_verdict || stageSlug(l.stage) === "gone");
  const rows = lv.sort((a, b) => (STAGE_ORDER[a.stage] == null ? 4 : STAGE_ORDER[a.stage]) - (STAGE_ORDER[b.stage] == null ? 4 : STAGE_ORDER[b.stage]) || b.absorbed_total - a.absorbed_total).slice(0, 8).map(l => {
    const who = l.side === "bid" ? "buyer" : "seller", live = l.state === "RELOAD" || l.proven, gone = !live;
    const stg = l.stage || (live ? "RELOADING" : ""), cv = l.conviction == null ? (live ? 1 : 0) : l.conviction;
    const head = gone ? (l.last_verdict || stg || "") : "RELOAD " + who.toUpperCase();
    const trust = live ? `<span class="k">CONVICTION</span><span class="v" title="${esc(stageWords(stg, l.side))}">${Math.round(cv * 100)}%<span class="cvbar"><i style="width:${Math.round(cv * 100)}%"></i></span><span class="stg ${stageSlug(stg)}">${stg}</span></span>
      <span class="k">SINCE RELOAD</span><span class="v">${l.refill_age != null ? ago(l.refill_age) + " ago" : NA}${l.since_refill ? ` · ${sz(l.since_refill)} traded through, not put back` : ""}</span>` : (stageSlug(stg) === "gone" ? `<span class="k">CONVICTION</span><span class="v"><span class="stg gone">${stg}</span> <span class="dim">${esc(stageWords(stg, l.side))}</span></span>` : "");
    const real = l.real ? `<span class="k">SIZE HERE</span><span class="v"><span class="rf ${l.real.label}">${l.real.label}</span> <span class="dim">${Math.round(l.real.pct * 100)}% of what left traded</span></span>` : "";
    const kn = l.knows, knows = kn && live ? (kn.knows ? `<span class="knowsline">⚡ ${esc(kn.words)}</span>` : kn.dollars > 0 ? `<span class="knowsline some">${esc(kn.words)}</span>` : "") : "";
    return `<div class="rl ${who} ${gone ? "gone" : ""} ${stg ? "st-" + stageSlug(stg) : ""} ${kn && kn.knows && live ? "knows" : ""}"><span class="t">${head}${kn && kn.knows && live ? ` <span class="knows" title="${esc(kn.words)}">⚡ SOMEBODY KNOWS SOMETHING</span>` : ""}</span>${trust}${real}${knows}
      <span class="k">PRICE</span><span class="v">$${px(l.price)} <span class="dim">${esc((l.role || "").split("+")[0] === "auto" ? "big level" : "your " + (l.role || "").split("+")[0].replace("trigger", "pivot").replace("_", " "))}</span></span>
      <span class="k">RELOADS</span><span class="v">${l.refreshes != null ? l.refreshes : NA}</span>
      <span class="k">SHARES OBSERVED</span><span class="v">${l.absorbed_total != null ? sz(l.absorbed_total) : NA}</span>
      <span class="k">SHOWING</span><span class="v">${l.displayed != null ? sz(l.displayed) : NA}</span></div>`;
  }).join("");
  panelHTML("reload", rows || `<div class="dim">No confirmed reload buyer or seller on ${esc(d.symbol)} right now.</div>`);
}
function renderWatch(s){
  panelHTML("watch", (s.ranking || []).map(r => `<div class="wlrow ${r.symbol === curSym ? "cur" : ""}" data-sym="${esc(r.symbol)}">
    <span><b>${esc(r.symbol)}</b>${r.depth ? ' <span style="color:var(--gold)">◆</span>' : ""}<span class="wlx" data-rm="${esc(r.symbol)}" title="take ${esc(r.symbol)} off the watchlist">✕</span></span><span style="color:var(--gold)">${px(r.last)}</span>
    <span class="gw"><span class="g ${r.ps60 ? r.ps60.grade : ""}">${r.ps60 ? r.ps60.grade : ""}</span>${r.ps60 && r.ps60.flow && r.ps60.flow.bias != null && Math.abs(r.ps60.flow.bias) >= 0.3 ? ` <span class="fb ${r.ps60.flow.bias > 0 ? "c" : "p"}" title="option flow last 30 min: ${r.ps60.flow.bias > 0 ? "call" : "put"} heavy">${r.ps60.flow.bias > 0 ? "C" : "P"}${Math.round(Math.abs(r.ps60.flow.bias) * 100)}</span>` : ""}</span>
    <span class="w">${r.rank ? "#" + r.rank + " · " : ""}${r.side} · ${esc(r.retired ? "RETIRED" : r.status)}</span></div>`).join("") || `<div class="dim" style="padding:8px">No plays.</div>`);
}
function renderCalls(s){
  const all = store.get("callsAll", false);
  const alerts = (s.alerts || []).filter(a => (all || a.symbol === curSym || /^UNUSUAL/.test(a.label)) && !(training() && /RELOAD|CLEANED|PULLED/.test(a.label))).slice(0, 40);
  const html = `<div class="dim" style="margin-bottom:4px;font-size:11px"><label><input type="checkbox" id="callsAll" ${all ? "checked" : ""}> every symbol</label></div>` + (alerts.length ? alerts.map(a => {
    const age = s.now - a.t;
    const gr = a.key ? `<span class="grade" data-key="${esc(a.key)}"><button data-v="good" class="${a.grade==="good"?"on":""}">GOOD</button><button data-v="bad" class="${a.grade==="bad"?"on":""}">BAD</button></span>` : "";
    const fb = a.flow && a.flow.ids && a.flow.ids.length ? `<button class="fbtn" data-flowkey="${esc(a.key || "")}" title="open OPTION FLOW on the exact prints this call added up">🔎 FLOW</button>` : "";
    return `<div class="say ${sayClass(a)} ${age < 15 ? "fresh" : ""}"><span class="age">${ago(age)}</span>${gr}${fb}<b>${esc(a.symbol)}</b> — ${esc(a.text || a.label)}</div>`;
  }).join("") : `<div class="say">No calls for ${esc(curSym || "this symbol")} yet.</div>`);
  const fb = document.getElementById("feedBody"); if (fb.dataset.h !== html){ fb.dataset.h = html; fb.innerHTML = html; }
}
document.getElementById("feedBody").addEventListener("click", ev => {
  const b = ev.target.closest("[data-flowkey]"); if (!b) return;
  const a = ((state && state.alerts) || []).find(x => x.key === b.dataset.flowkey); if (a && a.flow) showFlowRef(a.flow);
});
/* ---------- partial profit + breakeven: on the position row and in the ticket */
const PP = {};   // symbol -> {open, shares, px}: the partial-profit form, kept while you type
// getting out / protecting works disarmed and locked (paper / sim account), like the server allows
// a ticket order that takes the position down is a close: allowed disarmed and locked, like FLATTEN
function closesPosition(d, side, qty, type){ const q = d && d.position ? d.position.qty : 0; return !!q && canReduce() && (type || "LMT") === "LMT" && side === (q > 0 ? "SELL" : "BUY") && qty > 0 && qty <= Math.abs(q); }
function canReduce(){ const t = (state && state.trading) || {}; return t.mode === "SIM" || t.mode === "PAPER" || (t.mode === "LIVE" && t.can_trade); }
function ppDefaults(sym){
  const d = ((state && state.panes) || []).concat(Object.values((state && state.extra) || {})).find(x => x && x.symbol === sym);
  const pos = d && d.position; if (!pos) return null;
  const long = pos.qty > 0, q = Math.abs(pos.qty), last = d.last || pos.avg_cost, tgt = d.play && d.play.target;
  // default price: halfway from here to your target when it is on the profit side, else a little into profit
  let p = tgt && (long ? tgt > last : tgt < last) ? last + (tgt - last) / 2 : last * (long ? 1.005 : 0.995);
  return {long, q, px: snapPx(p), shares: Math.max(1, Math.floor(q / 2))};
}
function partialHTML(sym){
  const f = PP[sym], dd = ppDefaults(sym); if (!f || !f.open || !dd) return "";
  const sh = f.shares != null ? f.shares : dd.shares, pr = f.px != null ? f.px : dd.px;
  return `<div class="pp" data-pp="${esc(sym)}"><b>TAKE PARTIAL</b>
    <input class="pp-sh" type="number" min="1" max="${dd.q - 1}" step="1" value="${sh}" title="shares to take off"> sh
    ${[25, 50, 75].map(k => `<button data-pp-pct="${k}">${k}%</button>`).join("")}
    @ <input class="pp-px" type="number" step="${pr < 1 ? "0.0001" : "0.01"}" value="${pr}" title="the limit price for the partial">
    <button class="pp-send ${dd.long ? "s" : "b"}" data-pp-send="1">${dd.long ? "SELL" : "BUY"} PARTIAL</button><button data-pp-close="1" title="close this form">✕</button></div>`;
}
async function sendPartial(sym, el){
  const sh = +el.querySelector(".pp-sh").value, pr = +el.querySelector(".pp-px").value;
  if (!(sh > 0) || !(pr > 0)){ toast("Shares and price, please", false); return; }
  const out = await post("/api/trade/partial", {symbol: sym, shares: sh, price: pr});
  toast(out.ok ? "Sent: " + out.sent : "Partial blocked: " + (out.reason || ""), out.ok);
  if (out.ok){ PP[sym] = {open: false}; P.positions.last = null; P.ticket.last = null; poll(true); }
}
/* THE SIMPLE BLOCK at the top of ORDER ENTRY: what you have, in big letters, and plain buttons.
   BUY / SELL send the size in the box at the touch (ask to buy, bid to sell). SELL 5 / 10 / 20 / ALL take shares off a
   long (BUY ... on a short covers it). Taking off always works, armed or not. */
function contractBoxHTML(s, d){
  const l = OC.link, t = s.trading || {}, n = l.n || 1;
  const pos = ((s.account || {}).opt_positions || []).find(p => p.key === l.key), q = pos ? Math.abs(pos.qty) : 0, long = pos && pos.qty > 0;
  const f = v => v == null ? "—" : (+v).toFixed(2);
  const have = q ? `<div class="have"><span class="lbl">YOU HAVE</span><b class="${long ? "b" : "s"}">${long ? "" : "SHORT "}${q} ${q === 1 ? "CONTRACT" : "CONTRACTS"}</b><span>paid ${pos.per_contract != null ? pos.per_contract.toFixed(2) : "—"}</span>${pos.pnl != null ? `<b class="pl ${pos.pnl >= 0 ? "b" : "s"}">${pos.pnl >= 0 ? "+" : "−"}$${sz(Math.abs(Math.round(pos.pnl)))}</b>` : ""}</div>`
    : `<div class="have flat"><span class="lbl">YOU HAVE</span><b>NONE OF THIS CONTRACT</b></div>`;
  const pre = [1, 2, 5, 10, 20];
  return `<div class="simple contract"><div class="clink"><span class="lbl">TRADING THE CONTRACT</span><b class="${l.right === "C" ? "b" : "s"}">${esc(contractName(l))}</b><span class="dim">bid ${f(l.bid)} / ask ${f(l.ask)}</span><button data-ochart="${esc(l.key)}" title="chart this contract and trade it from the chart">📈 CHART</button><button data-unlink="1" title="go back to trading ${esc(l.sym)} shares">✕ BACK TO SHARES</button></div>
    ${have}
    <div class="cq"><span class="lbl">CONTRACTS</span>${pre.map(k => `<button data-cn="${k}" class="${k === n ? "on" : ""}">${k}</button>`).join("")}<input id="cnQty" type="number" min="1" step="1" value="${n}"></div>
    <div class="bs"><button class="big b" data-cb="BUY" title="BUY ${n} at the ask ${f(l.ask)}">BUY ${n}<i>${f(l.ask)} · $${sz(Math.round((l.ask || 0) * 100 * n))}</i></button><button class="big s" data-cb="SELL" title="${long ? `SELL ${n} of your ${q}` : `SELL ${n} to open`} at the bid ${f(l.bid)}">SELL ${n}<i>${f(l.bid)} · $${sz(Math.round((l.bid || 0) * 100 * n))}</i></button></div>
    ${(((s.account || {}).pending) || []).filter(o => o.symbol === l.key && !["FILLED", "CANCELED", "REJECTED"].includes(o.state)).map(o => `<div class="cwk"><span class="${o.action === "BUY" ? "b" : "s"}">WORKING ${esc(o.action)} ${sz(o.remaining ?? o.qty)} @ ${o.lmt ? (+o.lmt).toFixed(2) : "?"}</span> <span class="dim">not filled yet</span> <button class="danger" data-cxl="${o.order_id}">CANCEL</button></div>`).join("")}
    ${q ? `<div class="mgr"><button class="${long ? "s" : "b"} all" data-cb="ALL" title="close all ${q} at the touch">${long ? "SELL" : "BUY"} ALL ${q}</button></div>` : ""}</div>`;
}
document.addEventListener("input", e => { if (e.target.id === "cnQty" && OC.link){ OC.link.n = Math.max(1, Math.round(+e.target.value || 1)); } });
document.addEventListener("click", async e => {
  const cx = e.target.closest(".simple.contract button[data-cxl]"); if (cx){ cancelMine(+cx.dataset.cxl); return; }
  const b = e.target.closest("button[data-unlink], button[data-cn], button[data-cb]"); if (!b || !P.ticket.el.contains(b) || !OC.link) return;
  const l = OC.link;
  if (b.dataset.unlink){ OC.link = null; TMODE = "stock"; unpair(); P.ticket.last = null; poll(true); const bd = P.options && P.options.pc.querySelector(".oc-body"); if (bd) bd.dataset.h = ""; return; }
  if (b.dataset.cn){ l.n = +b.dataset.cn; P.ticket.last = null; poll(true); return; }
  const s = state || {}, pos = ((s.account || {}).opt_positions || []).find(p => p.key === l.key), q = pos ? Math.abs(pos.qty) : 0, long = pos && pos.qty > 0;
  const n = Math.max(1, +(document.getElementById("cnQty") || {}).value || l.n || 1);
  if (b.dataset.cb === "ALL"){        // getting out never waits on a confirm box
    const out = await post("/api/trade/opt_adjust", {key: l.key, contracts: 0, mode: "close", price: null}); toast(out.ok ? "OUT: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); P.ticket.last = null; poll(true); return; }
  const side = b.dataset.cb, touch = side === "BUY" ? l.ask : l.bid;
  const closing = q && ((long && side === "SELL") || (!long && side === "BUY"));
  if (!closing && !canTrade()){ toast(whyNot() + (/ARM/i.test(whyNot()) ? "" : " — click ARM"), false); const a = document.getElementById("armBtn"); if (a){ a.dataset.pulse = "1"; setTimeout(() => { delete a.dataset.pulse; }, 2400); } return; }
  if (touch == null){ toast("No quote on that contract — use the OPTION CHAIN's PX box to set a limit", false); return; }
  const send = async () => {
    const out = closing ? await post("/api/trade/opt_adjust", {key: l.key, contracts: Math.min(n, q), mode: "close", price: null})
      : await post("/api/trade/opt_open", {symbol: l.sym, expiry: l.expiry, strike: l.strike, right: l.right, action: side, contracts: n, price: null});
    toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); P.ticket.last = null; poll(true); };
  { const so = closing ? 0 : shortOpening(l.key, side, n); if (so) return shortOpenConfirm(`${n} ${contractName(l)} @ ${touch.toFixed(2)}`, so, send); }
  if (T().one_click) return send();
  confirmBox(`${side} ${closing ? Math.min(n, q) : n} ${contractName(l)}`, `${side === "BUY" ? "ask" : "bid"} ${touch.toFixed(2)} a contract · about $${sz(Math.round(touch * 100 * (closing ? Math.min(n, q) : n)))}${closing ? " · takes your contracts down" : ""}`, side === "BUY" ? "b" : "s", send);
});
function simpleBoxHTML(s, d){
  if (OC.link && OC.link.sym === d.symbol) return contractBoxHTML(s, d);
  const pos = d.position, q = pos && pos.qty ? Math.abs(pos.qty) : 0, long = pos && pos.qty > 0, t = s.trading || {};
  const n = TK.qty || t.default_shares || 100, red = canReduce();
  const pnl = q ? (pos.pnl != null ? pos.pnl : ((d.last || pos.avg_cost) - pos.avg_cost) * pos.qty) : null;
  const have = q ? `<div class="have"><span class="lbl">YOU HAVE</span><b class="${long ? "b" : "s"}">${long ? "LONG" : "SHORT"} ${sz(q)}</b><b>${esc(d.symbol)}</b><span>avg ${px(pos.avg_cost)}</span>
      <b class="pl ${pnl >= 0 ? "b" : "s"}">${pnl >= 0 ? "+" : "−"}$${sz(Math.abs(Math.round(pnl)))}</b></div>`
    : `<div class="have flat"><span class="lbl">YOU HAVE</span><b>NO ${esc(d.symbol)} POSITION</b></div>`;
  const out = long ? "SELL" : "BUY", pre = (t.manage_presets || [5, 10, 20]).filter(k => k < q);
  const mgr = q ? `<div class="mgr">${pre.map(k => `<button class="${long ? "s" : "b"}" data-sq="${k}" ${red ? "" : "disabled"} title="${out} ${k} shares at the ${long ? "bid" : "ask"}">${out} ${k}</button>`).join("")}<button class="${long ? "s" : "b"} all" data-sq="all" ${red ? "" : "disabled"} title="${out} all ${sz(q)} at the touch">${out} ALL ${sz(q)}</button></div>` : "";
  const pres = (t.qty_presets || [25, 50, 100, 200, 500, 1000]).slice(0, 6);
  return `<div class="simple">${have}
    <div class="cq"><span class="lbl">SHARES</span>${pres.map(k => `<button data-sqty="${k}" class="${k === n ? "on" : ""}">${k >= 1000 ? k / 1000 + "K" : k}</button>`).join("")}<input id="sbQty" type="number" min="1" step="1" value="${n}"></div>
    <div class="bs"><button class="big b" data-sb="BUY" title="BUY ${sz(n)} ${esc(d.symbol)} now: at the ask ${px(d.ask)}, never more than 3 ticks above it">BUY ${sz(n)}<i>${px(d.ask)}</i></button><button class="big s" data-sb="SELL" title="SELL ${sz(n)} ${esc(d.symbol)} now: at the bid ${px(d.bid)}, never more than 3 ticks below it">SELL ${sz(n)}<i>${px(d.bid)}</i></button></div>
    ${mgr}</div>`;
}
document.addEventListener("click", async e => {
  const b = e.target.closest("button[data-sb], button[data-sq]"); if (!b || !P.ticket.el.contains(b)) return;
  const d = curData(); if (!d) return;
  const pos = d.position, q = pos && pos.qty ? Math.abs(pos.qty) : 0, long = pos && pos.qty > 0;
  if (b.dataset.sq){
    if (b.dataset.sq === "all"){        // getting out never waits on a confirm box
      const out = await post("/api/trade/flatten", {symbol: d.symbol});
      toast(out.ok ? (out.flat ? d.symbol + " already flat" : "OUT: " + out.sent) : "Blocked: " + (out.reason || ""), out.ok); P.ticket.last = null; poll(true);
      return; }
    const out = await post("/api/trade/adjust", {symbol: d.symbol, shares: +b.dataset.sq, mode: "close"});
    toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); P.ticket.last = null; poll(true); return;
  }
  const side = b.dataset.sb, n = +(document.getElementById("tkQty") || {}).value || TK.qty || 100, touch = side === "BUY" ? d.ask : d.bid;
  if (!(touch > 0)){ toast("No quote yet", false); return; }
  // fills now like a market order, but capped: up to 3 ticks through the touch, never further
  const tk = tickOfPx(touch), price = snapPx(side === "BUY" ? touch + 3 * tk : touch - 3 * tk);
  const closing = q && ((long && side === "SELL") || (!long && side === "BUY")) && n <= q;
  if (!canTrade() && !closing){ toast(whyNot() + (/ARM/i.test(whyNot()) ? "" : " — click ARM"), false); const a = document.getElementById("armBtn"); if (a){ a.dataset.pulse = "1"; setTimeout(() => { delete a.dataset.pulse; }, 2400); } return; }
  const send = async () => { const out = await post("/api/trade/order", {symbol: d.symbol, action: side, price, qty: n, type: "LMT", bracket: closing ? false : !!T().bracket, tif: "DAY", nonce: "sb" + Date.now()});
    toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); P.ticket.last = null; poll(true); };
  if (T().one_click) return send();
  confirmBox(`${side} ${sz(n)} ${d.symbol} @ ${px(price)}`, `${side === "BUY" ? "ask" : "bid"} ${px(touch)} · fills now, never ${side === "BUY" ? "above" : "below"} ${px(price)} · about $${sz(Math.round(n * touch))}${closing ? " · takes your position down" : T().bracket ? " · with your stop and target" : ""}`, side === "BUY" ? "b" : "s", send);
});
/* OPTION POSITIONS on this ticker, in ORDER ENTRY: one line per contract with entry, quote, P&L and the buttons
   to take some off, add, or close it all (same orders as POSITIONS: a limit at the touch). */
function optPosHTML(s, d){
  const rows = ((s.account || {}).opt_positions || []).filter(p => p.symbol === d.symbol || String(p.key || "").split(" ")[0] === d.symbol);
  if (!rows.length) return "";
  const red = canReduce(), on = canTrade();
  return `<div class="simple opm">${rows.map(p => { const long = p.qty > 0, q = Math.abs(p.qty), half = Math.max(1, Math.floor(q / 2));
    const mark = long ? p.bid : p.ask, k = esc(p.key);
    const out = long ? "SELL" : "BUY", inn = long ? "BUY" : "SELL", pre = (T().manage_option_presets || [1, 2, 5]).filter(n => n < q);
    return `<div class="have"><span class="lbl">YOU HAVE</span><b class="${long ? "b" : "s"}">${long ? "" : "SHORT "}${q} ${q === 1 ? "CONTRACT" : "CONTRACTS"}</b><b>${esc(p.label || p.key)}</b>
      <span>paid ${p.per_contract != null ? p.per_contract.toFixed(2) : NA}</span><span class="dim" title="what you would get closing now">${mark != null ? (long ? "bid " : "ask ") + mark.toFixed(2) : "no quote"}</span>
      ${p.pnl != null ? `<b class="pl ${p.pnl >= 0 ? "b" : "s"}">${p.pnl >= 0 ? "+" : "−"}$${sz(Math.abs(Math.round(p.pnl)))}</b>` : ""}</div>
      <div class="mgr">${pre.map(n => `<button class="${long ? "s" : "b"}" data-tko="${k}" data-n="${n}" ${red ? "" : "disabled"} title="${out} ${n} contract${n > 1 ? "s" : ""} at the ${long ? "bid" : "ask"}">${out} ${n}</button>`).join("")}<button class="${long ? "s" : "b"} all" data-tko="${k}" data-n="0" ${red ? "" : "disabled"} title="${out} all ${q} at the touch">${out} ALL ${q}</button><button class="${long ? "b" : "s"} add" data-tka="${k}" data-n="1" ${on ? "" : "disabled"} title="${inn} 1 more contract">${inn} 1 MORE</button></div>`; }).join("")}</div>`;
}
document.addEventListener("click", async e => {
  const b = e.target.closest("button[data-tko], button[data-tka]"); if (!b || !P.ticket.el.contains(b)) return;
  const key = b.dataset.tko || b.dataset.tka, mode = b.dataset.tko != null ? "close" : "add", n = +b.dataset.n;
  if (mode === "close" && n === 0 && !confirm("CLOSE every contract of " + key + "?")) return;
  const out = await post("/api/trade/opt_adjust", {key, contracts: n, mode, price: null});
  toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); P.ticket.last = null; poll(true);
});
/* MANAGE THE POSITION from ORDER ENTRY, in one small box: where you are, the stop (by price or one click), a
   trailing stop, BE / PARTIAL / CLOSE, then the scale plan and take-offs folded to one line each. */
function posManagerHTML(s, d){
  const pos = d.position, long = pos.qty > 0, q = Math.abs(pos.qty), last = d.last || pos.avg_cost, red = canReduce();
  const pnl = pos.pnl != null ? pos.pnl : (last - pos.avg_cost) * pos.qty;
  const stopO = (d.orders || []).find(o => o.role === "stop" && o.action === (long ? "SELL" : "BUY"));
  const stopPx = stopO ? stopO.price : null, risk = stopPx != null ? (long ? stopPx - pos.avg_cost : pos.avg_cost - stopPx) * q : null;
  const trail = ((s.trading || {}).trails || {})[d.symbol];
  const tv = store.get("trailDollars", 0.5), sv = TK.stopPx != null && TK.stopSym === d.symbol ? TK.stopPx : (stopPx != null ? stopPx : snapPx(long ? last - 0.5 : last + 0.5));
  const offs = [0.25, 0.5, 1];
  return `<div class="pm">
    <div class="pmr">${stopPx != null ? `<span class="pmstop" title="your working stop">STOP ${px(stopPx)}${risk != null ? ` <i>${risk >= 0 ? "+" : "−"}$${sz(Math.abs(Math.round(risk)))}</i>` : ""}</span>` : `<span class="pmstop none" title="no stop order is working on this position">NO STOP</span>`}
      <span class="pmbtn"><button data-be="${esc(d.symbol)}" ${red ? "" : "disabled"} title="stop to your entry price">BE</button><button data-partial="${esc(d.symbol)}" ${red ? "" : "disabled"} title="take part off: shares and price">PART</button><button class="danger" data-close="${esc(d.symbol)}" ${red ? "" : "disabled"} title="close the whole position at the touch">CLOSE</button></span></div>
    <div class="pmr">
      <label>STOP</label><input id="pmStop" type="number" step="${last < 1 ? "0.0001" : "0.01"}" value="${sv}" title="the stop price"><button data-pmstop="set" ${red ? "" : "disabled"} title="put the stop at this price (moves the working stop)">SET</button>
      ${offs.map(o => `<button data-pmstop="${o}" ${red ? "" : "disabled"} title="stop ${long ? "under" : "over"} the price by $${o.toFixed(2)}: ${px(snapPx(long ? last - o : last + o))}">${long ? "−" : "+"}${o % 1 ? String(o).replace(/^0/, "") : o}</button>`).join("")}
      <label class="tl">TRAIL $</label><input id="pmTrail" type="number" step="0.05" min="0.01" value="${trail ? trail.dist : tv}" title="how far the stop trails behind the best price"><button data-pmtrail="${trail ? "off" : "on"}" class="${trail ? "on" : ""}" ${red ? "" : "disabled"} title="${trail ? `trailing: best ${px(trail.best)}, stop ${trail.stop != null ? px(trail.stop) : "—"} · click to stop trailing` : "trail the stop behind the price: it only moves in your favour"}">${trail ? "TRAILING" : "TRAIL"}</button></div>
    ${partialHTML(d.symbol)}${scalePlanHTML(s, d)}${takeoffHTML(d)}</div>`;
}
document.addEventListener("click", async e => {
  const d = curData(); if (!d || !d.position || !d.position.qty) return;
  const long = d.position.qty > 0, last = d.last || d.position.avg_cost;
  const sb = e.target.closest("button[data-pmstop]");
  if (sb){ const v = sb.dataset.pmstop === "set" ? +document.getElementById("pmStop").value : snapPx(long ? last - +sb.dataset.pmstop : last + +sb.dataset.pmstop);
    if (!(v > 0)){ toast("Type a stop price", false); return; }
    TK.stopPx = null; const out = await post("/api/trade/stop", {symbol: d.symbol, price: v}); toast(out.ok ? out.sent : "Stop: " + (out.reason || ""), out.ok); P.ticket.last = null; poll(true); return; }
  const tb = e.target.closest("button[data-pmtrail]");
  if (tb){ const on = tb.dataset.pmtrail === "on", dist = +document.getElementById("pmTrail").value; if (on) store.set("trailDollars", dist);
    const out = await post("/api/trade/trail", {symbol: d.symbol, dollars: dist, on}); toast(out.ok ? (on ? `Trailing $${dist.toFixed(2)} behind the best price` : "Trail off — the stop stays") : "Trail: " + (out.reason || ""), out.ok); P.ticket.last = null; poll(true); return; }
});
document.addEventListener("input", e => { if (e.target.id === "pmStop"){ TK.stopPx = e.target.value; TK.stopSym = curSym; } });
/* SCALE PLAN on the position: rungs measured from your average entry. MP = room to the target (a dollar, take a
   quarter; two, take a third; the rest rides). CASH = continuation, take more sooner. BUILD = add on strength, then
   scale out. TAKE pct is of what is LEFT; AUTO fires at the touch when the rung is reached, manual shows READY. */
const SPC = {};   // symbol -> custom rung rows being typed
function scalePlanHTML(s, d){
  const pos = d.position, long = pos.qty > 0, t = (s && s.trading) || {}, plan = (t.scale_plans || {})[d.symbol], tpls = t.scale_templates || {};
  const open = store.get("scaleOpen", false);
  const head = `<button class="tohead" data-sp-toggle="1" title="show / hide the scale plan">${open ? "▾" : "▸"} SCALE PLAN</button>`;
  if (!open) return `<div class="scale">${head}${plan ? ` <span class="dim">${esc(plan.kind)} · ${plan.left_pct}% left</span>` : ""}</div>`;
  if (!plan){
    const rows = SPC[d.symbol] || [];
    return `<div class="scale">${head}
      <span class="spk">${Object.keys(tpls).map(k => `<button data-sp-kind="${k}" title="${(tpls[k] || []).map(r => "+$" + r.move + " " + r.action + " " + r.pct + "%").join(" · ")}">${k === "MP" ? "MP TRADE" : k === "CASH" ? "CASH FLOW" : k}</button>`).join("")}</span>
      <span class="spc"><input class="sp-mv" type="number" step="0.05" min="0.05" placeholder="+$" title="dollars a share from your entry"><select class="sp-act"><option>TAKE</option><option>ADD</option></select><input class="sp-pct" type="number" min="1" max="100" placeholder="%" title="percent of what is left (TAKE) or of the position (ADD)"><button data-sp-addrow="1" title="add this rung to a custom plan">+ RUNG</button>${rows.length ? `<span class="dim">${rows.map(r => "+$" + r.move + " " + r.action + " " + r.pct + "%").join(" · ")}</span><button data-sp-custom="1">START CUSTOM</button>` : ""}</span>
      <span class="dim">templates in SETTINGS › Trading › scale plan</span></div>`;
  }
  const mv = plan.move == null ? "—" : (plan.move >= 0 ? "+" : "−") + "$" + Math.abs(plan.move).toFixed(2);
  const rungs = plan.rungs.map((r, i) => { const st = r.done ? "done" : r.ready ? "ready" : i === plan.next ? "next" : "";
    return `<div class="spr ${st} ${r.action === "ADD" ? "add" : ""}"><b>+$${(+r.move).toFixed(2)}</b><span>${r.action} ${r.pct}%</span>
      <i>${r.done ? `✓ ${sz(r.shares)} sh @ ${px(r.price)}` : r.ready ? "READY" : r.note ? esc(r.note) : ""}</i>
      ${r.done ? "" : `<button data-sp-fire="${i}" ${canReduce() ? "" : "disabled"} title="fire this rung now at the touch">${r.action === "ADD" ? "ADD" : "TAKE"} NOW</button>`}</div>`; }).join("");
  return `<div class="scale on">${head}
    <span class="spst"><b class="${long ? "b" : "s"}">${esc(plan.kind)}</b> from ${px(plan.entry)} · now ${mv}</span>
    <span class="spleft" title="${sz(plan.left)} of ${sz(plan.basis)} shares still on"><i style="width:${Math.max(0, Math.min(100, plan.left_pct || 0))}%"></i><b>${plan.left_pct}% LEFT · ${sz(plan.left)} sh</b></span>
    <button data-sp-auto="${plan.auto ? 0 : 1}" class="${plan.auto ? "on" : ""}" title="AUTO: a rung fires by itself the moment price reaches it. Off: it shows READY and you press">AUTO ${plan.auto ? "ON" : "OFF"}</button>
    <button data-sp-clear="1" title="take the plan off (the position stays)">✕</button>
    <div class="sprs">${rungs}</div></div>`;
}
document.addEventListener("click", async e => {
  const d = curData(); if (!d) return;
  if (e.target.closest("button[data-sp-toggle]")){ store.set("scaleOpen", !store.get("scaleOpen", false)); P.ticket.last = null; renderTicket(state, d, true); return; }
  const k = e.target.closest("button[data-sp-kind]"); if (k){ const out = await post("/api/trade/scale_plan", {symbol: d.symbol, kind: k.dataset.spKind}); toast(out.ok ? "Scale plan on: " + k.dataset.spKind : "Scale plan: " + (out.reason || ""), out.ok); poll(true); return; }
  if (e.target.closest("button[data-sp-addrow]")){ const box = e.target.closest(".scale"); const mv = +box.querySelector(".sp-mv").value, act = box.querySelector(".sp-act").value, pct = +box.querySelector(".sp-pct").value; if (!(mv > 0) || !(pct > 0)){ toast("Dollars and percent, please", false); return; } (SPC[d.symbol] = SPC[d.symbol] || []).push({move: mv, action: act, pct}); P.ticket.last = null; renderTicket(state, d, true); return; }
  if (e.target.closest("button[data-sp-custom]")){ const out = await post("/api/trade/scale_plan", {symbol: d.symbol, kind: "CUSTOM", rungs: SPC[d.symbol] || []}); if (out.ok) SPC[d.symbol] = []; toast(out.ok ? "Custom scale plan on" : "Scale plan: " + (out.reason || ""), out.ok); poll(true); return; }
  const a = e.target.closest("button[data-sp-auto]"); if (a){ const out = await post("/api/trade/scale_plan", {symbol: d.symbol, auto: a.dataset.spAuto === "1"}); toast(out.ok ? "AUTO " + (a.dataset.spAuto === "1" ? "on" : "off") : (out.reason || ""), out.ok); poll(true); return; }
  if (e.target.closest("button[data-sp-clear]")){ await post("/api/trade/scale_plan", {symbol: d.symbol, clear: true}); poll(true); return; }
  const f = e.target.closest("button[data-sp-fire]"); if (f){ const out = await post("/api/trade/scale_fire", {symbol: d.symbol, i: +f.dataset.spFire}); toast(out.ok ? "Sent: " + (out.sent || "rung fired") : "Rung: " + (out.reason || ""), out.ok); poll(true); return; }
});
// take-off presets: one press = a limit for your chosen share of the position at entry + $X a share (long) / − $X (short)
const TAKE_OFF = [0.75, 1, 1.5, 2, 2.5, 5];
function takeoffHTML(d){
  const pos = d.position, long = pos.qty > 0, q = Math.abs(pos.qty), open = store.get("takeoffOpen", false), pct = +store.get("takeoffPct", 50);
  const n = Math.max(1, Math.min(q - 1, Math.round(q * pct / 100)));
  return `<div class="takeoff"><button class="tohead" data-to-toggle="1" title="show / hide the take-off buttons">${open ? "▾" : "▸"} TAKE OFF</button>${open ? `
    <span class="topct">${[25, 50, 75].map(k => `<button data-to-pct="${k}" class="${pct === k ? "on" : ""}" title="take off ${k}% of the position">${k}%</button>`).join("")}<span class="dim">${sz(n)} sh</span></span>
    <span class="tobtns">${TAKE_OFF.map(x => { const p = snapPx(pos.avg_cost + (long ? x : -x));
      return `<button data-to="${x}" ${canReduce() && q > 1 ? "" : "disabled"} title="${long ? "SELL" : "BUY"} ${sz(n)} @ ${px(p)} (entry ${px(pos.avg_cost)} ${long ? "+" : "−"} $${x.toFixed(2)})">+$${x % 1 ? x.toFixed(2) : x}</button>`; }).join("")}</span>` : ""}</div>`;
}
document.addEventListener("click", async e => {
  if (e.target.closest("button[data-to-toggle]")){ store.set("takeoffOpen", !store.get("takeoffOpen", false)); P.ticket.last = null; renderTicket(state, curData(), true); return; }
  const pc = e.target.closest("button[data-to-pct]"); if (pc){ store.set("takeoffPct", +pc.dataset.toPct); P.ticket.last = null; renderTicket(state, curData(), true); return; }
  const b = e.target.closest("button[data-to]"); if (!b) return;
  const d = curData(); if (!d || !d.position || !d.position.qty) return;
  const pos = d.position, long = pos.qty > 0, q = Math.abs(pos.qty), x = +b.dataset.to;
  const n = Math.max(1, Math.min(q - 1, Math.round(q * (+store.get("takeoffPct", 50)) / 100)));
  const price = snapPx(pos.avg_cost + (long ? x : -x));
  const out = await post("/api/trade/partial", {symbol: d.symbol, shares: n, price});
  toast(out.ok ? `Take off at +$${x.toFixed(2)}: ${out.sent}` : "Take-off blocked: " + (out.reason || ""), out.ok);
  poll(true);
});
async function moveToBreakeven(sym){
  const out = await post("/api/trade/breakeven", {symbol: sym});
  toast(out.ok ? sym + ": " + out.sent : "Breakeven blocked: " + (out.reason || ""), out.ok);
  poll(true);
}
document.addEventListener("click", async e => {
  const be = e.target.closest("button[data-be]"); if (be){ moveToBreakeven(be.dataset.be); return; }
  const obe = e.target.closest("button[data-obe]"); if (obe){ const out = await post("/api/trade/opt_breakeven", {key: obe.dataset.obe});
    toast(out.ok ? obe.dataset.obe + ": " + out.sent : "Breakeven blocked: " + (out.reason || ""), out.ok); poll(true); return; }
  const op = e.target.closest("button[data-partial]"); if (op){ const s = op.dataset.partial; PP[s] = {open: !(PP[s] && PP[s].open)}; P.positions.last = null; P.ticket.last = null; renderPositions(state); renderTicket(state, curData(), true); return; }
  const box = e.target.closest(".pp[data-pp]"); if (!box) return;
  const sym = box.dataset.pp, dd = ppDefaults(sym);
  const pct = e.target.closest("button[data-pp-pct]");
  if (pct && dd){ const n = Math.max(1, Math.min(dd.q - 1, Math.round(dd.q * +pct.dataset.ppPct / 100))); PP[sym].shares = n; box.querySelector(".pp-sh").value = n; return; }
  if (e.target.closest("button[data-pp-send]")) sendPartial(sym, box);
  if (e.target.closest("button[data-pp-close]")){ PP[sym] = {open: false}; P.positions.last = null; P.ticket.last = null; renderPositions(state); renderTicket(state, curData(), true); }
});
document.addEventListener("input", e => {
  const box = e.target.closest && e.target.closest(".pp[data-pp]"); if (!box) return;
  const f = PP[box.dataset.pp] = PP[box.dataset.pp] || {open: true};
  if (e.target.classList.contains("pp-sh")) f.shares = +e.target.value;
  if (e.target.classList.contains("pp-px")) f.px = +e.target.value;
});
document.addEventListener("keydown", e => { const box = e.target.closest && e.target.closest(".pp[data-pp]"); if (!box) return; e.stopPropagation(); if (e.key === "Enter") sendPartial(box.dataset.pp, box); }, true);

function renderPositions(s){
  const A = s.account, on = canReduce();
  if (P.positions.pc.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;   // typing in the partial form
  const rows = (A.positions || []).map(p => {
    const long = p.qty > 0, pct = p.last && p.avg_cost ? ((p.last - p.avg_cost) / p.avg_cost * 100) * (long ? 1 : -1) : null;
    const q = Math.abs(p.qty);
    const usd = p.last && p.avg_cost ? (p.last - p.avg_cost) * p.qty : null;
    const red = (frac, lbl, tip) => `<button data-red="${esc(p.symbol)}" data-n="${Math.max(1, Math.floor(q * frac))}" ${on && q > 1 ? "" : "disabled"} title="${tip}: ${long ? "sell" : "buy back"} ${sz(Math.max(1, Math.floor(q * frac)))} at the touch">${lbl}</button>`;
    const ex = (A.pending || []).filter(o => o.symbol === p.symbol), stp = ex.find(o => o.role === "stop" || /^stop/.test(o.role || "")), tgt = ex.filter(o => /target|runner|cash_flow/.test(o.role || ""));
    return `<tr data-sym="${esc(p.symbol)}" class="posrow"><td class="l"><b>${esc(p.symbol)}</b> <span class="${long ? "b" : "s"}">${long ? "L" : "S"} ${sz(q)}</span></td><td>${px(p.avg_cost)}</td><td>${px(p.last)}</td>
      <td class="pct ${pct == null ? "" : pct >= 0 ? "up" : "dn"}"><b>${pctFmt(pct)}</b> <span class="dim">${usd == null ? "" : (usd >= 0 ? "+" : "−") + "$" + sz(Math.abs(usd).toFixed(0))}</span></td>
      <td class="mono dim" title="working stop / targets on this symbol">${stp ? `<span class="s">S ${px(stp.aux || stp.lmt)}</span>` : "—"} ${tgt.length ? tgt.map(o => `<span class="b">T ${px(o.lmt)}</span>`).join(" ") : ""}</td>
      <td class="l ctl">${red(0.25, "25", "take off a quarter")}${red(0.5, "50", "take off half")}${red(0.75, "75", "take off three quarters")}<button data-red="${esc(p.symbol)}" data-n="ask" ${on ? "" : "disabled"} title="reduce by a number of shares you type">…</button>
        <span class="sep"></span><button data-add="${esc(p.symbol)}" data-n="${Math.max(1, Math.floor(q / 2))}" ${canTrade() ? "" : "disabled"} title="scale in: add half again (${sz(Math.max(1, Math.floor(q / 2)))} sh) at the touch">+½</button><button data-add="${esc(p.symbol)}" data-n="${q}" ${canTrade() ? "" : "disabled"} title="scale in: double it (${sz(q)} sh) at the touch">+1×</button><button data-add="${esc(p.symbol)}" data-n="ask" ${canTrade() ? "" : "disabled"} title="scale in by a number of shares you type">+…</button>
        <button data-partial="${esc(p.symbol)}" ${on ? "" : "disabled"} title="take part of the profit at a price you pick">@</button><button data-be="${esc(p.symbol)}" ${on ? "" : "disabled"} title="move the stop to your entry price (breakeven); any other stop orders on ${esc(p.symbol)} are cancelled">BE</button>
        <button class="danger" data-close="${esc(p.symbol)}" ${on ? "" : "disabled"} title="CLOSE the whole position with a limit at the touch">X</button></td></tr>${PP[p.symbol] && PP[p.symbol].open ? `<tr><td colspan="6" class="l">${partialHTML(p.symbol)}</td></tr>` : ""}`;
  }).join("");
  // option positions (from TWS): contracts, with their own quotes; scaled with the same buttons in contracts
  const orows = (A.opt_positions || []).map(p => {
    const long = p.qty > 0, q = Math.abs(p.qty), ct = n => n + " ct";
    const off = (n, lbl, tip) => `<button data-oclose="${esc(p.key)}" data-n="${n}" ${on && n > 0 ? "" : "disabled"} title="${tip}: ${long ? "sell" : "buy back"} ${ct(n)} at the ${long ? "bid" : "ask"}">${lbl}</button>`;
    const add = (n, lbl) => `<button data-oadd="${esc(p.key)}" data-n="${n}" ${canTrade() ? "" : "disabled"} title="scale in: ${long ? "buy" : "sell"} ${ct(n)} more at the ${long ? "ask" : "bid"}">${lbl}</button>`;
    const quote = p.bid != null || p.ask != null ? `${p.bid != null ? p.bid.toFixed(2) : NA} / ${p.ask != null ? p.ask.toFixed(2) : NA}` : `<span class="dim">no quote</span>`;
    return `<tr class="posrow opt" data-okey="${esc(p.key)}" title="right-click: show this contract on the OPTION CHART"><td class="l"><b>${esc(p.label)}</b> <span class="${long ? "b" : "s"}">${long ? "L" : "S"} ${ct(q)}</span>${p.delta != null ? ` <span class="dim" title="delta">Δ${(p.delta * p.qty).toFixed(1)}</span>` : ""}</td><td>${p.per_contract.toFixed(2)}</td><td>${quote}</td>
      <td class="pct ${p.pnl == null ? "" : p.pnl >= 0 ? "up" : "dn"}">${p.pnl == null ? NA : (p.pnl >= 0 ? "+" : "−") + "$" + sz(Math.abs(p.pnl).toFixed(0))}</td><td class="mono dim">${(() => { const os = (T().opt_stops || {})[p.key]; return os ? `<span class="s" title="${os.source === "chart" ? "your chart STOP line" : "the stop you set"}">S ${os.on === "stock" ? esc(p.symbol) + " " : ""}${(+os.price).toFixed(2)}</span>` : `<span class="gold" title="no stop on this contract: set one on the OPTION CHART, or draw a STOP on the stock chart">no stop</span>`; })()}</td>
      <td class="l ctl">${off(Math.max(1, Math.floor(q / 4)), "25", "take off a quarter")}${off(Math.max(1, Math.floor(q / 2)), "50", "take off half")}${off(Math.max(1, Math.floor(q * 3 / 4)), "75", "take off three quarters")}<button data-oclose="${esc(p.key)}" data-n="ask" ${on ? "" : "disabled"} title="take off a number of contracts you type, at a price you type">…</button>
        <span class="sep"></span>${add(1, "+1")}${add(Math.max(1, Math.floor(q / 2)), "+½")}${add(q, "+1×")}<button data-oadd="${esc(p.key)}" data-n="ask" ${canTrade() ? "" : "disabled"} title="scale in by a number of contracts you type, at a price you type">+…</button>
        <button data-obe="${esc(p.key)}" ${on ? "" : "disabled"} title="move this contract's stop to what you paid (${p.per_contract.toFixed(2)}): out at no loss if it comes back">BE</button>
        <button class="danger" data-oclose="${esc(p.key)}" data-n="0" ${on ? "" : "disabled"} title="CLOSE every contract with a limit at the touch">X</button></td></tr>`;
  }).join("");
  // option orders that have not filled yet: they are not a position, so say so where you look for it
  const wk = (A.pending || []).filter(o => / \d{8} /.test(o.symbol || "") && !["FILLED", "CANCELED", "REJECTED"].includes(o.state)).map(o => o.role === "backup_stop" ?
    `<tr class="posrow opt wk bk"><td class="l"><b>${esc(o.symbol)}</b> <span class="s">BACKUP STOP</span></td><td>${o.aux ? (+o.aux).toFixed(2) : NA}</td><td colspan="3" class="l dim" title="a real stop order held at IBKR: it protects the contract with the desk or the computer off. The desk's own stop goes first; this one sits a little past it, follows your stop, and comes off when you are out">at IBKR · ${esc(o.action)} ${sz(o.remaining ?? o.qty)} ct if the contract trades ${o.aux ? (+o.aux).toFixed(2) : NA} (limit ${o.lmt ? (+o.lmt).toFixed(2) : NA}, ${esc(o.tif || "")}) · works with the desk off</td><td></td></tr>` :
    `<tr class="posrow opt wk"><td class="l"><b>${esc(o.symbol)}</b> <span class="${o.action === "BUY" ? "b" : "s"}">${esc(o.action)} ${sz(o.remaining ?? o.qty)} ct</span></td><td>${o.lmt ? (+o.lmt).toFixed(2) : NA}</td><td colspan="3" class="l gold">WORKING · not filled yet — it shows here as a position once it fills</td>
      <td class="l ctl"><button class="danger" data-cxl="${o.order_id}" title="cancel this option order">CANCEL</button></td></tr>`).join("");
  panelHTML("positions", `<table class="grid pos2"><tr><th>POSITION</th><th>ENTRY</th><th>LAST</th><th>P&amp;L %</th><th>STOP · TGT</th><th style="text-align:left" title="25 / 50 / 75 = take that much off at the touch · … = your own number · @ = partial at your price · BE = stop to breakeven · X = close · +½ +1× +… = scale in at the touch">OUT 25 · 50 · 75 · … · @ · BE · X &nbsp; IN +½ · +1× · +…</th></tr>${rows + orows + wk || `<tr><td colspan="6" class="dim l">${A.seen ? "FLAT" : "NO ACCOUNT DATA"}</td></tr>`}</table>`);
}
/* right-click a position: an option one goes on the OPTION CHART (with its L2, T&S and ORDER ENTRY), the stock
   chart switches to its underlying; a stock one opens its chart */
async function showHeldContract(key){
  const [sym, exp, rest] = String(key).split(" "); if (!rest) return;
  const strike = parseFloat(rest.slice(0, -1)), right = rest.slice(-1);
  if (curSym !== sym && typeof openTab === "function") await openTab(sym, true);
  OC.expiry = exp; OC.right = right; OC.sel = strike;
  const pos = ((state && state.account && state.account.opt_positions) || []).find(x => x.key === key) || {};
  OC.link = {sym, expiry: exp, strike, right, key, bid: pos.bid, ask: pos.ask, n: Math.abs(pos.qty || 1) || 1};
  chartOption(key, true); P.ticket.last = null;
  if (typeof pollChain === "function") pollChain();
  if (typeof renderContractL2 === "function"){ renderContractL2(); renderContractTape(); }
  toast(`${contractName(OC.link)} — on the OPTION CHART, its LEVEL II and T&S${state && state.feeds && state.feeds.options && state.feeds.options.label === "SIM" ? " (SIMULATED: market closed)" : ""}`, true);
}
P.positions.el.addEventListener("contextmenu", e => {
  const tr = e.target.closest("tr.posrow[data-okey], tr.posrow[data-sym]"); if (!tr) return;
  e.preventDefault();
  const old = document.getElementById("cmenu"); if (old) old.remove();
  const m = document.createElement("div"); m.id = "cmenu"; m.className = "pop cmenu";
  const k = tr.dataset.okey, sy = tr.dataset.sym;
  m.innerHTML = k ? `<div class="dim" style="font-size:11px;margin-bottom:4px">${esc(k)}<span class="x" title="close (Esc)">✕</span></div>
      <button data-do="och">📈 Show on the OPTION CHART</button><button data-do="und">Open the ${esc(k.split(" ")[0])} stock chart</button>`
    : `<div class="dim" style="font-size:11px;margin-bottom:4px">${esc(sy)}<span class="x" title="close (Esc)">✕</span></div><button data-do="und">Open the ${esc(sy)} chart</button>`;
  m.style.left = Math.min(e.clientX, innerWidth - 240) + "px"; m.style.top = Math.min(e.clientY, innerHeight - 120) + "px";
  document.body.appendChild(m);
  m.addEventListener("click", ev => { const b = ev.target.closest("button[data-do]"); if (ev.target.closest(".x") || b) m.remove(); if (!b) return;
    if (b.dataset.do === "och") showHeldContract(k);
    else if (typeof openTab === "function") openTab(k ? k.split(" ")[0] : sy, true); });
  setTimeout(() => document.addEventListener("click", function off(ev){ if (!m.contains(ev.target)){ m.remove(); document.removeEventListener("click", off); } }), 0);
});
let showHistory = false, selOrder = null;
function renderOrders(s){
  const A = s.account;
  const live = (A.pending || []), done = (A.done || []), mineLive = live.filter(o => o.order_id != null && o.state !== "CANCEL PENDING");
  const row = o => `<tr class="${selOrder === o.order_id ? "sel" : ""}" data-oid="${o.order_id ?? ""}" data-sym="${esc(o.symbol)}"><td class="l mono dim">${nyT(o.t || o.first_seen || 0)}</td><td class="l"><b>${esc(o.symbol)}</b> <span class="dim">${esc(o.role || "")}</span></td><td class="${o.action === "BUY" ? "b" : "s"}">${esc(o.action)}</td><td>${sz(o.qty)}</td><td>${esc(o.type)}</td>
    <td>${o.lmt ? px(o.lmt) : NA}${o.aux ? ` <span class="dim">stp ${px(o.aux)}</span>` : ""}</td><td>${sz(o.filled || 0)}</td><td>${sz(o.remaining ?? o.qty)}</td><td><span class="stt ${(o.state || "").split(" ")[0]}">${esc(o.state || o.status || NA)}</span></td>
    <td class="l">${["FILLED", "CANCELED", "REJECTED"].includes(o.state) ? "" : o.state === "CANCEL PENDING" ? `<span class="dim">cancelling…</span>`
      : o.order_id != null ? `<button data-mod="${o.order_id}" data-px="${o.lmt || o.aux || ""}" title="change the price">MODIFY</button> <button class="danger" data-cxl="${o.order_id}">CANCEL</button>`
      : `<span class="dim" title="IBKR only lets the program that placed an order cancel it through the API">placed in TWS — cancel it in TWS</span>`}</td></tr>`;
  panelHTML("orders", `<div style="display:flex;gap:8px;align-items:center;padding:3px 6px;font-size:11px" class="dim"><label><input type="checkbox" id="ordHist" ${showHistory ? "checked" : ""}> history</label><span class="spacer" style="flex:1"></span><button data-cxlall="1" class="danger" ${mineLive.length ? "" : "disabled"} title="cancels every order TED placed (orders typed in TWS are cancelled in TWS)">CANCEL ALL (${mineLive.length})</button></div>
    <table class="grid"><tr><th>TIME</th><th>SYMBOL</th><th>SIDE</th><th>QTY</th><th>TYPE</th><th>LIMIT / STOP</th><th>FILLED</th><th>REMAIN</th><th>STATUS</th><th style="text-align:left"></th></tr>
    ${live.map(row).join("") || `<tr><td colspan="10" class="dim l">${A.seen ? "NO WORKING ORDERS" : "NO ACCOUNT DATA"}</td></tr>`}
    ${showHistory ? done.map(row).join("") : ""}</table>`);
}

/* ---------- order ticket */
const TK = {side: "BUY", type: "LMT", tif: "DAY", qty: null, inflight: false, log: []};
function tkNonce(){ return Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }
function renderTicket(s, d, force){
  // the price in the ticket belongs to ONE symbol: switching symbols clears it (never send AAPL's price on SOFI)
  if (TK.sym !== curSym){ TK.sym = curSym; TK.px = null; TK.aux = null; force = true; }
  // never rebuild the ticket under your fingers: while you are typing in it, only the quote line updates
  const ae = document.activeElement;
  if (!force && ae && P.ticket.el.contains(ae) && /^(INPUT|SELECT)$/.test(ae.tagName)){
    const q = document.getElementById("tkQuote"); if (q && d) q.textContent = `${px(d.bid)} / ${px(d.ask)}`;
    return;
  }
  const t = s.trading || {}, on = canTrade();
  if (TK.qty == null) TK.qty = t.default_shares || 100;
  const allowMkt = !!(t.allow_market);
  const price = d ? (TK.side === "BUY" ? d.bid : d.ask) : null;
  // compact: three short rows (side · size · price · send / sizing · type · tif · exits / the position and its
  // take-offs), so the ticket takes a few lines and the screen stays with the chart, ladder and tape
  const sizing = (() => { const stop = d && d.play && d.play.stop, ent = TK.px != null ? TK.px : price; if (!stop || !ent) return `<span class="dim">NO STOP</span>`; const r = Math.abs(ent - stop); if (r < tickOfPx(ent) / 2) return `<span class="dim">entry = stop</span>`; const n = capShares(Math.floor(riskDollars() / r), ent); return `<button data-q="set:${Math.max(1, n)}" class="szb" title="size the ticket from your risk $: $${riskDollars()} ÷ $${r.toFixed(2)} a share">${sz(n)} sh</button><span class="dim">$${r.toFixed(2)}/sh</span>`; })();
  TK.type = "LMT"; TK.tif = "DAY";                 // limit, day: the only order you send by hand
  const optMode = !!(OC.link && OC.link.sym === curSym) || TMODE === "opt", more = store.get("tkmore", false);
  const modeBar = `<div class="tmode"><button data-tmode="stock" class="${optMode ? "" : "on"}">STOCK · ${esc(curSym || "")}</button><button data-tmode="opt" class="${optMode ? "on" : ""}">OPTIONS</button></div>`;
  const body = !d ? "" : optMode && !(OC.link && OC.link.sym === curSym) ? optPickHTML(d) : simpleBoxHTML(s, d);
  const html = `<div class="ticket compact">${modeBar}${body}
    ${optMode ? "" : `<div class="tmore"><button data-tkmore="1">${more ? "LESS ▴" : "MORE ▾"}</button><span class="dim">${more ? "limit price, risk sizing, bracket" : "limit price · risk sizing · bracket"}</span></div>`}
    <div class="trow ${optMode || !more ? "hidden" : ""}">
      <b class="sym">${esc(curSym || NA)}</b><span class="dim q" id="tkQuote">${d ? `${px(d.bid)} / ${px(d.ask)}` : ""}</span>
      <span class="sides"><button class="b ${TK.side === "BUY" ? "on" : ""}" data-side="BUY">BUY</button><button class="s ${TK.side === "SELL" ? "on" : ""}" data-side="SELL">SELL</button><button class="opt" data-openchain="1" title="open the OPTION CHAIN for this ticker: pick expiry and strike, BUY or SELL to open, price box, SEND">OPTIONS</button></span>
      <span class="row qty"><button class="qbtn" data-q="-100">−</button><input id="tkQty" type="number" min="1" step="100" value="${TK.qty}" title="shares"><button class="qbtn" data-q="100">+</button>${(t.qty_presets || [100, 500]).slice(0, 6).map(n => `<button class="qbtn" data-q="set:${n}">${n >= 1000 ? (n / 1000) + "k" : n}</button>`).join("")}</span>
      ${TK.type !== "MKT" ? `<span class="row pxr"><input id="tkPx" type="number" step="${price != null && price < 1 ? "0.0001" : "0.01"}" value="${TK.px != null ? TK.px : (price != null ? price : "")}" title="${TK.type === "STP" ? "stop" : "limit"} price"><button data-px="bid">bid</button><button data-px="ask">ask</button><button data-px="mid">mid</button><button data-px="last">last</button></span>` : ""}
      ${TK.type === "STP LMT" ? `<span class="row"><input id="tkAux" type="number" step="0.01" value="${TK.aux != null ? TK.aux : ""}" placeholder="stop" title="stop trigger"></span>` : ""}
      <button class="tx ${TK.side === "BUY" ? "b" : "s"}" id="tkGo" ${(on || closesPosition(d, TK.side, TK.qty, TK.type)) && d && !TK.inflight ? "" : "disabled"}>${TK.inflight ? "SENDING…" : "SEND"}</button>
    </div>
    <div class="trow sub ${optMode || !more ? "hidden" : ""}">
      <span class="risk"><label>RISK $</label><input id="tkRisk" type="number" step="10" min="0" value="${riskDollars()}"><span class="out">${sizing}</span></span>
      <span class="opts"><label><input type="checkbox" id="tkBracket" ${t.bracket ? "checked" : ""}> bracket</label><select id="tkTpl" title="what the bracket is: PLAY = the stop and target you drew; a template brackets from the entry price (stop −$, targets +$ with share splits)">${["PLAY"].concat(t.bracket_templates || []).map(n => `<option value="${esc(n)}" ${(t.bracket_template || "PLAY") === n ? "selected" : ""}>${esc(n)}</option>`).join("")}</select><label><input type="checkbox" id="tkScale" ${t.scale ? "checked" : ""}> PS60 exits</label></span>
      <button id="tkCxl" ${d && d.orders && d.orders.length ? "" : "disabled"} class="danger" title="cancel every working order on this symbol">CXL ALL</button>
    </div>
    ${d && d.position && d.position.qty ? posManagerHTML(s, d) : ""}${d ? optPosHTML(s, d) : ""}
    ${on ? "" : `<div class="why">${esc(whyNot())}${d && d.position && d.position.qty ? " · closing still works: CLOSE, FLATTEN, or a " + (d.position.qty > 0 ? "SELL" : "BUY") + " up to " + sz(Math.abs(d.position.qty)) : ""}</div>`}
    ${TK.log.length ? `<div class="st">${TK.log.slice(0, 2).map(l => `<div>${esc(l)}</div>`).join("")}</div>` : ""}</div>`;
  panelHTML("ticket", html);
}
function tkNote(txt){ TK.log.unshift(nyT(Date.now() / 1000) + " " + txt); TK.log = TK.log.slice(0, 20); P.ticket.last = null; renderTicket(state, curData(), true); }
async function transmit(){
  const d = curData(), t = T();
  if (TK.inflight) return;
  const qty = +document.getElementById("tkQty").value, type = TK.type, tif = TK.tif;
  const pxEl = document.getElementById("tkPx"), auxEl = document.getElementById("tkAux");
  const price = pxEl ? +pxEl.value : null, aux = auxEl ? +auxEl.value : null;
  if (!d){ tkNote("no symbol"); return; }
  if (d.symbol !== TK.sym){ tkNote("symbol changed — check the price and send again"); return; }
  if (!(t.can_trade && t.armed) && !closesPosition(d, TK.side, qty, type)){ tkNote("blocked: " + whyNot()); return; }
  if (!(qty > 0)){ tkNote("quantity must be positive"); return; }
  if (type !== "MKT" && !(price > 0)){ tkNote("price required"); return; }
  if (type === "STP LMT" && !(aux > 0)){ tkNote("stop price required"); return; }
  if (!d.bid && !d.ask && !d.last){ tkNote("no quote for " + d.symbol + " — not sending"); return; }
  const send = async () => {
    TK.inflight = true; P.ticket.last = null; renderTicket(state, d, true);
    const nonce = tkNonce();
    try {
      const out = await post("/api/trade/order", {symbol: d.symbol, action: TK.side, price, qty, type, aux, tif, nonce, bracket: document.getElementById("tkBracket").checked});
      tkNote(out.ok ? "SUBMITTED #" + out.id + " " + out.sent + " — waiting for IBKR acknowledgement" : "REJECTED: " + (out.reason || ""));
      toast(out.ok ? "Submitted: " + out.sent : "Rejected: " + out.reason, out.ok);
    } catch (e) { tkNote("send failed: " + e.message); }
    TK.inflight = false; P.ticket.last = null; renderTicket(state, d, true); poll(true);
  };
  if (t.one_click) return send();
  confirmBox(`${TK.side} ${sz(qty)} ${d.symbol} ${type}${type !== "MKT" ? " @ " + px(price) : ""}${aux ? " stop " + px(aux) : ""}`, `about $${sz(Math.round(qty * (price || d.last || 0)))} · ${tif}` + (d.ps60 && d.ps60.grade === "PASS" ? ` · PS60 PASS: ${d.ps60.why}` : "") + flowAgainst(d, TK.side), TK.side === "BUY" ? "b" : "s", send);
}
P.ticket.el.addEventListener("click", e => {
  const d = curData();
  const sb = e.target.closest("button[data-side]"); if (sb){ TK.side = sb.dataset.side; TK.px = null; P.ticket.last = null; renderTicket(state, d); return; }
  const qb = e.target.closest("button[data-q]"); if (qb){ const v = qb.dataset.q; TK.qty = v.startsWith("set:") ? +v.slice(4) : Math.max(1, (+document.getElementById("tkQty").value || 0) + +v); P.ticket.last = null; renderTicket(state, d); return; }
  const pb = e.target.closest("button[data-px]"); if (pb && d){ const m = pb.dataset.px; TK.px = m === "bid" ? d.bid : m === "ask" ? d.ask : m === "last" ? d.last : (d.bid && d.ask ? snapPx((d.bid + d.ask) / 2) : d.last); P.ticket.last = null; renderTicket(state, d, true); return; }
  if (e.target.id === "tkGo") transmit();
  if (e.target.id === "tkCxl" && d) cancelAll(d.symbol);
});
P.ticket.el.addEventListener("change", e => {
  if (e.target.id === "tkType"){ TK.type = e.target.value; TK.px = null; P.ticket.last = null; renderTicket(state, curData(), true); }
  if (e.target.id === "tkTif") TK.tif = e.target.value;
  if (e.target.id === "tkQty"){ TK.qty = +e.target.value; post("/api/trade/size", {shares: TK.qty}); }
  if (e.target.id === "tkPx") TK.px = +e.target.value;
  if (e.target.id === "tkAux") TK.aux = +e.target.value;
  if (e.target.id === "tkRisk"){ store.set("riskDollars", +e.target.value || 0); syncRisk(); P.ticket.last = null; renderTicket(state, curData()); P.setup.last = null; SU.dirty = false; renderSetup(curData()); }
  if (e.target.id === "tkBracket") post("/api/trade/bracket", {on: e.target.checked});
  if (e.target.id === "tkTpl"){ post("/api/trade/bracket_template", {name: e.target.value}).then(out => { toast(out.ok ? "Bracket: " + out.template : "Not set: " + (out.reason || ""), out.ok); poll(true); }); }
  if (e.target.id === "tkScale") post("/api/trade/scale", {on: e.target.checked});
});
// Enter sends the ticket only from the ticket's own boxes (qty / price / stop); Enter in STOP, TRAIL, the simple box
// or the scale plan never fires an order
P.ticket.el.addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter" && e.target.tagName === "INPUT" && /^(tkQty|tkPx|tkAux)$/.test(e.target.id || "")) transmit(); });
P.positions.el.addEventListener("click", async e => {
  const c = e.target.closest("button[data-close]"); if (c){ if (!confirm("CLOSE the whole " + c.dataset.close + " position?")) return; flatten(c.dataset.close); return; }
  const ad = e.target.closest("button[data-add]"); if (ad){ let n = ad.dataset.n; if (n === "ask"){ n = prompt("Add how many shares to " + ad.dataset.add + "?"); if (!n) return; } if (!canTrade()) return toast("Can't trade: " + whyNot(), false);
    const out = await post("/api/trade/adjust", {symbol: ad.dataset.add, shares: +n, mode: "add"}); toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); return; }
  const oc = e.target.closest("button[data-oclose], button[data-oadd]"); if (oc){ const key = oc.dataset.oclose || oc.dataset.oadd, mode = oc.dataset.oclose != null ? "close" : "add"; let n = oc.dataset.n, price = null;
    if (n === "ask"){ n = prompt((mode === "close" ? "Take off" : "Add") + " how many contracts of " + key + "?"); if (!n) return; price = prompt("Limit price per contract (blank = at the touch)"); if (price === null) return; price = price.trim() === "" ? null : +price; }
    if (mode === "close" && +n === 0 && !confirm("CLOSE every contract of " + key + "?")) return;
    const out = await post("/api/trade/opt_adjust", {key, contracts: +n, mode, price}); toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); return; }
  const r = e.target.closest("button[data-red]"); if (r){ let n = r.dataset.n; if (n === "ask"){ n = prompt("Reduce " + r.dataset.red + " by how many shares?"); if (!n) return; } if (!canReduce()) return toast("Can't trade: " + whyNot(), false);
    const out = await post("/api/trade/adjust", {symbol: r.dataset.red, shares: +n, mode: "close"}); toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); return; }
  const cw = e.target.closest("button[data-cxl]"); if (cw){ cancelMine(+cw.dataset.cxl); return; }
  const tr = e.target.closest("tr[data-sym]"); if (tr) openTab(tr.dataset.sym, false);
});
P.orders.el.addEventListener("click", async e => {
  if (e.target.id === "ordHist") return;
  const m = e.target.closest("button[data-mod]"); if (m){ const np = prompt("New price for order #" + m.dataset.mod + ":", m.dataset.px); if (!np) return; const out = await post("/api/trade/modify", {id: +m.dataset.mod, price: +np}); toast(out.ok ? "Modified" : "Modify blocked: " + (out.reason || ""), out.ok); return; }
  const c = e.target.closest("button[data-cxl]"); if (c){ cancelMine(+c.dataset.cxl); return; }
  if (e.target.closest("button[data-cxlall]")){ if (confirm("Cancel ALL working orders?")) cancelAll(null); return; }
  const tr = e.target.closest("tr[data-sym]"); if (tr){ selOrder = +tr.dataset.oid || null; if (tr.dataset.sym && tr.dataset.sym !== curSym) openTab(tr.dataset.sym, false); P.orders.last = null; }
});
P.orders.el.addEventListener("change", e => { if (e.target.id === "ordHist"){ showHistory = e.target.checked; P.orders.last = null; poll(true); } });
P.watch.el.addEventListener("click", async e => {
  const x = e.target.closest(".wlx");
  if (x){ e.stopPropagation(); const sym = x.dataset.rm; if (!confirm(`Take ${sym} off the watchlist? Its quotes, flow marks and alerts go with it.`)) return;
    const out = await post("/api/play", {symbol: sym, action: "remove"}); if (out.ok){ TABS.list = TABS.list.filter(t => t !== sym); if (TABS.active === sym){ TABS.active = TABS.list[0] || null; curSym = TABS.active; } savePrefs({tabs: TABS.list, active: TABS.active}); renderTabs(); toast(sym + " removed", true); poll(true); } else toast("Could not remove " + sym, false); return; }
  const r = e.target.closest(".wlrow"); if (r) openTab(r.dataset.sym, false); });
async function wlAdd(){ const inp = document.getElementById("wlAdd"), sym = inp.value.trim().toUpperCase(); if (!sym) return;
  const out = await post("/api/play", {symbol: sym, action: "add"}); if (!out.ok){ toast(sym + " is not a valid ticker", false); return; }
  inp.value = ""; toast(sym + " added to the watchlist", true); poll(true); }
document.getElementById("wlAddBtn").addEventListener("click", wlAdd);
document.getElementById("wlAdd").addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter") wlAdd(); if (e.key === "Escape") e.target.blur(); });
/* ---------- your alerts: a price to hit, option flow arriving, a big equity print */
function alertLine(a){
  const $ = v => v >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : "$" + Math.round(v / 1e3) + "K";
  if (a.kind === "price") return `${a.when === "hit" ? "hits" : "goes " + a.when} ${px(a.price)}`;
  if (a.kind === "flow") return `${a.cp === "C" ? "call" : a.cp === "P" ? "put" : "option"} flow ≥ ${$(a.min_premium)}`;
  return `equity print ≥ ${$(a.min_dollars)}`;
}
function renderMyAlerts(s){
  const el = document.getElementById("alList"); if (!el) return;
  const list = s.user_alerts || [];
  const html = list.length ? list.map(a => `<div class="alrow"><b>${esc(a.symbol)}</b><span>${esc(alertLine(a))}${a.repeat ? ' <i class="dim">every time</i>' : ""}${a.last ? ` <i class="dim">· last ${ago(s.now - a.last)}</i>` : ""}</span><span class="wlx" data-al="${a.id}" title="remove">✕</span></div>`).join("")
    : `<div class="dim" style="padding:8px">No alerts. Set one above, or right-click a price on the chart.</div>`;
  if (el.dataset.h !== html){ el.dataset.h = html; el.innerHTML = html; }
  const sym = document.getElementById("alSym"); if (sym && !sym.value && curSym && document.activeElement !== sym) sym.placeholder = curSym;
}
async function addAlert(body){ const out = await post("/api/alerts", body); toast(out.ok ? `Alert set: ${body.symbol} ${alertLine(out.alert)}` : "Could not set the alert: " + (out.reason || ""), out.ok); if (out.ok) poll(true); return out.ok; }
document.getElementById("alAdd").addEventListener("click", async () => {
  const sym = (document.getElementById("alSym").value.trim() || curSym || "").toUpperCase(), k = document.getElementById("alKind").value, v = parseFloat(document.getElementById("alVal").value);
  const rep = document.getElementById("alRepeat").checked, msg = document.getElementById("alMsg");
  if (!sym){ msg.textContent = "ticker?"; return; }
  let body;
  if (k === "price" || k === "above" || k === "below"){ if (!(v > 0)){ msg.textContent = "price?"; return; } body = {symbol: sym, kind: "price", price: v, when: k === "price" ? "hit" : k, repeat: rep}; }
  else if (k.startsWith("flow")) body = {symbol: sym, kind: "flow", min_premium: v > 0 ? v : undefined, cp: k === "flowC" ? "C" : k === "flowP" ? "P" : "any", repeat: rep};
  else body = {symbol: sym, kind: "equity", min_dollars: v > 0 ? v : undefined, repeat: rep};
  msg.textContent = ""; if (await addAlert(body)){ document.getElementById("alVal").value = ""; }
});
["alSym", "alVal"].forEach(id => document.getElementById(id).addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter") document.getElementById("alAdd").click(); }));
document.getElementById("alList").addEventListener("click", async e => { const x = e.target.closest(".wlx"); if (!x) return; const out = await post("/api/alerts", {action: "remove", id: +x.dataset.al}); if (out.ok) poll(true); });
/* ---------- equity flow: big stock prints, on and off the exchanges */
function renderEquity(s){
  const el = document.getElementById("eqList"); if (!el) return;
  const dark = document.getElementById("eqDark").checked, mine = document.getElementById("eqMine").checked;
  const rows = (s.equity || []).filter(p => (!dark || p.dark) && (!mine || (s.symbols || []).includes(p.symbol))).slice(0, 80);
  const src = document.getElementById("eqSrc"); const st = s.connection && s.connection.state === "DEMO" ? "PRACTICE PRINTS" : (s.equity_status && s.equity_status.detail ? "NO PRINTS READ · hover" : "QUANT DATA"); if (src.textContent !== st){ src.textContent = st; src.title = (s.equity_status && s.equity_status.detail) || ""; }
  const html = rows.length ? rows.map(p => `<div class="fl eq ${p.dark ? "dk" : "lt"} ${p.side === "ask" ? "c" : p.side === "bid" ? "p" : ""}" title="${p.dark ? "off-exchange print" : "on the tape"}${p.side === "ask" ? " · at the ask (buyer paid up)" : p.side === "bid" ? " · at the bid (seller hit it)" : ""}">
      <div class="tm">${nyHM(p.t)}</div>
      <div class="top"><span class="tk">${esc(p.symbol)}</span><span class="prem">${kfmt$(p.dollars)}</span><span class="venue ${p.dark ? "dk" : ""}">${p.dark ? "OFF-EX" : esc(p.venue || "LIT")}</span></div>
      <div class="cols"><span><i>SHARES</i>${sz(p.size)}</span><span><i>PRICE</i>${px(p.price)}</span><span><i>SIDE</i>${p.side === "ask" ? "PAID UP" : p.side === "bid" ? "HIT" : "MID"}</span></div></div>`).join("")
    : `<div class="dim" style="padding:10px">${s.connection && s.connection.state === "DEMO" ? "Practice prints are warming up." : (s.equity_status && s.equity_status.detail) ? "Quant Data answered but no equity print could be read: " + esc(s.equity_status.detail) : "No big equity prints yet (prints under the minimum in SETTINGS, Quant Data, are left out)."}</div>`;
  if (el.dataset.h !== html){ el.dataset.h = html; el.innerHTML = html; }
}
["eqDark", "eqMine"].forEach(id => document.getElementById(id).addEventListener("input", () => renderEquity(state)));
/* ---------- urgent flow: short-dated OTM contracts getting pounded */
/* URGENT FLOW search: one ticker's chased contracts live, plus everything that came in on it earlier this session */
const UR = {q: "", data: null, at: 0, busy: false};
async function urFetch(force){
  if (!UR.q || UR.busy || (!force && Date.now() - UR.at < 2000)) return;
  UR.busy = true;
  try { const r = await fetch("/api/urgency?symbol=" + encodeURIComponent(UR.q)); UR.data = await r.json(); UR.at = Date.now(); }
  catch (e) {} finally { UR.busy = false; }
  renderUrgency(state);
}
function urSet(q){ UR.q = (q || "").trim().toUpperCase(); UR.data = null; const i = document.getElementById("urQ"); if (i && i.value.toUpperCase() !== UR.q) i.value = UR.q; urFetch(true); renderUrgency(state); }
function renderUrgency(s){
  const el = document.getElementById("urList"); if (!el) return;
  const mine = document.getElementById("urMine").checked, hotOnly = document.getElementById("urHot").checked;
  if (UR.q) urFetch(false);
  const rows = UR.q ? ((UR.data && UR.data.symbol === UR.q && UR.data.live) || []).filter(u => !hotOnly || u.hot)
                    : (s.urgency || []).filter(u => (!mine || (s.symbols || []).includes(u.symbol)) && (!hotOnly || u.hot));
  const strike = k => Number.isInteger(+k) ? String(k) : (+k).toFixed(2).replace(/\.?0+$/, "");
  const exp = e => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(e || ""); return m ? `${m[2]}/${m[3]}` : (e || NA); };
  const top = rows.length ? rows[0].score : 1;
  const html = rows.length ? rows.map(u => `<div class="fl ur ${u.cp === "C" ? "c" : "p"} ${u.hot ? "hot" : ""}" title="${u.prints} prints bought at the ask in the window, ${u.sweeps} sweeps · ${kfmt$(u.pace)} a minute${u.accel ? " · speeding up" : ""}${u.hot ? " · CALLED: urgent" : ""}">
      <div class="tm">${nyHM12(u.last_t)} <span class="dim">· since ${nyHM12(u.first_t)}</span>${u.hot ? ` <span class="urg">⚡ URGENT</span>` : ""}${u.accel ? ` <span class="acc">▲ SPEEDING UP</span>` : ""}</div>
      <div class="top"><span class="tk">${esc(u.symbol)}</span><span class="prem">${kfmt$(u.dollars)}</span><span class="dots a">${u.sweeps ? "<i></i><i></i>" : ""}</span><span class="bar"><i style="width:${Math.max(4, 100 * u.score / top).toFixed(0)}%"></i></span></div>
      <div class="cols"><span><i>EXP</i>${exp(u.expiry)}${u.dte != null ? ` (${Math.round(u.dte)}d)` : ""}</span><span><i>STRIKE</i>${strike(u.strike)}</span><span><i>C/P</i>${u.cp}</span><span><i>OTM</i>${u.otm_pct != null ? u.otm_pct.toFixed(1) + "%" : NA}</span><span><i>PRINTS</i>${u.prints}${u.sweeps ? ` <b class="dim">${u.sweeps} sw</b>` : ""}</span><span><i>PACE</i>${kfmt$(u.pace)}/m</span>${u.spot != null ? `<span><i>SPOT</i>${(+u.spot).toFixed(2)}</span>` : ""}</div></div>`).join("")
    : `<div class="dim" style="padding:10px">${UR.q ? `Nothing on ${esc(UR.q)} being chased right now.` : "Nothing short-dated and out of the money is being chased right now."}</div>`;
  let full = html;
  if (UR.q){
    const D = UR.data && UR.data.symbol === UR.q ? UR.data : null, hist = D ? D.history : [];
    const head = `<div class="ur-head"><b>${esc(UR.q)}</b> <span class="dim">urgent-type flow this session:</span> <span class="c">calls ${kfmt$(D ? D.calls : 0)}</span> · <span class="p">puts ${kfmt$(D ? D.puts : 0)}</span> · ${hist.length} prints${D ? "" : ' <span class="dim">loading…</span>'}</div><div class="ur-sec">RIGHT NOW</div>`;
    const earlier = hist.length ? hist.map(h => `<div class="ur-h ${h.cp === "C" ? "c" : "p"}" title="${esc(`${h.size || "?"} contracts @ ${h.price != null ? (+h.price).toFixed(2) : "?"} · stock ${h.spot != null ? (+h.spot).toFixed(2) : "?"} · ${h.otm_pct}% out of the money · ${h.kind}${h.called ? " · this contract was CALLED urgent" : ""}`)}">
        <span class="tm">${nyHM12(h.t)}</span><span class="ct">${flowStrike(h.strike)}${h.cp} ${esc((h.expiry || "").slice(5))}</span><span class="dte">${Math.round(h.dte)}d</span><span class="pr">${kfmt$(h.premium)}</span><span class="k">${esc(h.kind)}</span><span class="otm">${h.otm_pct}%</span>${h.called ? `<span class="urg">⚡</span>` : "<span></span>"}</div>`).join("")
      : `<div class="dim" style="padding:6px 10px">Nothing urgent-type on ${esc(UR.q)} yet this session.</div>`;
    full = head + html + `<div class="ur-sec">EARLIER · newest first</div>` + earlier;
  }
  if (el.dataset.h !== full){ el.dataset.h = full; el.innerHTML = full; }
}
document.getElementById("urQ").addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Enter") urSet(e.target.value); if (e.key === "Escape"){ urSet(""); e.target.blur(); } });
document.getElementById("urQ").addEventListener("input", e => { const v = e.target.value.trim(); if (!v) urSet(""); else if (v.length >= 1){ clearTimeout(UR.tm); UR.tm = setTimeout(() => urSet(v), 350); } });
document.getElementById("urThis").addEventListener("click", () => urSet(curSym || ""));
document.getElementById("urClr").addEventListener("click", () => urSet(""));
["urMine", "urHot"].forEach(id => document.getElementById(id).addEventListener("input", () => renderUrgency(state)));
document.querySelectorAll(".fa-tabs [data-go]").forEach(t => t.addEventListener("click", () => showPanel(t.dataset.go)));
P.calls.el.addEventListener("change", e => { if (e.target.id === "callsAll"){ store.set("callsAll", e.target.checked); poll(true); } });
P.ps60.el.addEventListener("click", async e => { const b = e.target.closest("button[data-se]"); if (!b || !curSym) return; const out = await post("/api/level", {symbol: curSym, role: "second_entry", price: +b.dataset.se}); toast(out.ok ? "2nd entry set to " + px(+b.dataset.se) : "Could not set", out.ok); poll(true); });
{ const wrap = P.book.pc.querySelector(".ladder-wrap");
  wrap.addEventListener("wheel", () => { bookUserScroll = Date.now(); }, {passive: true});
  wrap.addEventListener("dragstart", e => { bookHold = null; const chip = e.target.closest(".chip[data-id]"); if (!chip){ e.preventDefault(); return; } e.dataTransfer.setData("text/plain", "order:" + chip.dataset.id); bookDragging = true; });
  wrap.addEventListener("dragend", () => { bookDragging = false; bookHold = null; P.book.last = null; });
  window.addEventListener("blur", () => { bookHold = null; bookDragging = false; });
  wrap.addEventListener("dragover", e => { const row = e.target.closest("tr"); if (row && row.querySelector("td.px")) e.preventDefault(); });
  wrap.addEventListener("drop", async e => { const row = e.target.closest("tr"); const data = e.dataTransfer.getData("text/plain"); if (!row || !data.startsWith("order:")) return; e.preventDefault(); const cell = row.querySelector("td[data-act]"); if (!cell) return; const out = await post("/api/trade/modify", {id: +data.slice(6), price: +cell.dataset.px}); toast(out.ok ? "Moved to " + px(out.price) : "Move blocked: " + (out.reason || ""), out.ok); });
  // the price is taken when you PRESS the button, and the ladder holds still until you let go: a ladder that
  // re-centres under the mouse can never turn your click into a different price
  wrap.addEventListener("contextmenu", e => { const row = e.target.closest("tr[data-price]"); const d = curData(); if (!row || !d) return; e.preventDefault(); ladderMenu(d, +row.dataset.price, e.clientX, e.clientY, e.target.closest(".chip[data-id]")); });
  wrap.addEventListener("mousedown", e => { if (e.button !== 0) return; const cell = e.target.closest("td[data-act]"); const d = curData();
    const flip = store.get("ladClick", "join") === "hit" && cell && cell.matches("td.sz");   // HIT mapping: a size cell trades against it
    bookHold = cell && d ? {side: flip ? (cell.dataset.act === "BUY" ? "SELL" : "BUY") : cell.dataset.act, px: +cell.dataset.px, sym: d.symbol, cell} : {cell: null}; });
  window.addEventListener("mouseup", () => setTimeout(() => { bookHold = null; }, 0));
  wrap.addEventListener("mouseleave", () => { if (bookHold && !bookHold.cell) bookHold = null; });
  wrap.addEventListener("click", e => { if (bookDragging) return; const h = bookHold; const chip = e.target.closest(".chip[data-id]"); if (chip){ if (chip.dataset.id && chip.dataset.id !== "null") cancelMine(+chip.dataset.id); return; }
    const cell = e.target.closest("td[data-act]"); const d = curData();
    if (!cell || !d || !h || h.cell !== cell || h.sym !== d.symbol) return;   // pressed one row, released on another: nothing
    sendOrder(h.sym, h.side, h.px); });
}

/* ---------- hotkeys: configurable, dangerous ones unassigned until you set them */
const HK_ACTIONS = [["focusSymbol", "Focus symbol box", false], ["focusTicket", "Focus order ticket", false], ["qtyUp", "Increase quantity", false], ["qtyDown", "Decrease quantity", false],
  ["buy", "BUY at ticket price (or bid)", true], ["sell", "SELL at ticket price (or ask)", true], ["joinBid", "Join the bid (BUY at bid)", true], ["joinAsk", "Join the ask (SELL at ask)", true],
  ["cancelSel", "Cancel selected order", true], ["cancelSym", "Cancel symbol orders (emergency)", true], ["cancelAll", "Cancel EVERY working order", true], ["flatten", "FLATTEN current symbol", true], ["reverse", "REVERSE current position", true],
  ["optBuy", "OPTION: BUY (contracts on the option chart) now", true], ["optSell", "OPTION: SELL now", true], ["optHalf", "OPTION: ½ OUT now", true], ["optOut", "OPTION: ALL OUT now", true],
  ["rec", "Record on / off", false], ["mark", "Marker", false], ["shot", "Screenshot", false], ["arm", "Arm / disarm", false], ["mic", "Voice note (mic) on / off", false], ["clip", "Clip the last minutes", false]];
const HK_DEFAULT = {focusSymbol: "Ctrl+L", focusTicket: "T", qtyUp: "+", qtyDown: "-", rec: " ", mark: "M", shot: "P", arm: "A", cancelSym: "Escape"};
function hotkeys(){ return Object.assign({}, HK_DEFAULT, PREFS.hotkeys || {}); }
function keyName(e){ const k = e.key === " " ? "Space" : e.key.length === 1 ? e.key.toUpperCase() : e.key; return (e.ctrlKey || e.metaKey ? "Ctrl+" : "") + (e.altKey ? "Alt+" : "") + (e.shiftKey && e.key.length > 1 ? "Shift+" : "") + k; }
function renderHK(){
  const hk = hotkeys();
  document.getElementById("hkPop").innerHTML = `<h5>HOTKEYS — click a key cell, press the keys, Esc to clear</h5><table class="hk">` + HK_ACTIONS.map(([id, label, danger]) => `<tr><td>${label}${danger ? ' <span class="danger">execution</span>' : ""}</td><td class="k" data-hk="${id}">${esc(hk[id] === " " ? "Space" : (hk[id] || "—"))}</td></tr>`).join("") + `</table><div class="dim" style="font-size:10.5px;margin-top:4px">Execution hotkeys go through the same checks as the mouse: connection, ARM, caps, quotes.</div>`;
}
document.getElementById("hkMenu").querySelector("button").addEventListener("click", e => { e.stopPropagation(); const m = document.getElementById("hkMenu"), open = !m.classList.contains("open"); document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); m.classList.toggle("open", open); renderHK(); });
document.getElementById("hkPop").addEventListener("click", e => { const td = e.target.closest("td.k"); if (!td) return; document.querySelectorAll("td.k.cap").forEach(x => x.classList.remove("cap")); td.classList.add("cap"); td.textContent = "press keys…"; });
document.addEventListener("keydown", e => {
  const cap = document.querySelector("td.k.cap"); if (!cap) return;
  e.preventDefault(); e.stopPropagation();
  const hk = Object.assign({}, PREFS.hotkeys || {});
  if (e.key === "Escape") hk[cap.dataset.hk] = null; else if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return; else hk[cap.dataset.hk] = keyName(e);
  savePrefs({hotkeys: hk}); renderHK();
}, true);
function runHotkey(e){
  const hk = hotkeys(), name = keyName(e), d = curData();
  const act = Object.keys(hk).find(k => hk[k] && (hk[k] === name || (hk[k] === " " && name === "Space")));
  if (!act) return false;
  e.preventDefault();
  const q = document.getElementById("tkQty");
  switch (act){
    case "optBuy": case "optSell": case "optHalf": case "optOut": {
      const od = OCH.data; if (!od){ toast("Pick a contract first (OPTIONS, then a strike)", false); break; }
      const pos = od.position, q = pos ? Math.abs(pos.qty) : 0, long = pos && pos.qty > 0;
      if (act === "optBuy") ochOrder("BUY", null, OCH.n);
      else if (act === "optSell") ochOrder("SELL", null, OCH.n);
      else if (!q) toast("No position in " + od.label, false);
      else ochOrder(long ? "SELL" : "BUY", null, act === "optOut" ? q : Math.max(1, Math.floor(q / 2)), true);
      break; }
    case "focusSymbol": document.getElementById("symIn").focus(); break;
    case "focusTicket": showPanel("ticket"); if (q) q.focus(); break;
    case "qtyUp": TK.qty = (TK.qty || 0) + 100; P.ticket.last = null; renderTicket(state, d); break;
    case "qtyDown": TK.qty = Math.max(1, (TK.qty || 0) - 100); P.ticket.last = null; renderTicket(state, d); break;
    case "buy": if (d){ TK.side = "BUY"; TK.px = chartPrice(charts.chart) || chartPrice(charts.foot) || d.bid; P.ticket.last = null; renderTicket(state, d, true); transmit(); } break;
    case "sell": if (d){ TK.side = "SELL"; TK.px = chartPrice(charts.chart) || chartPrice(charts.foot) || d.ask; P.ticket.last = null; renderTicket(state, d, true); transmit(); } break;
    case "cancelSel": if (selOrder) cancelMine(selOrder); else toast("select an order first", false); break;
    case "cancelSym": if (document.querySelector(".menu.open, #cmenu, .confirm")) return false; if (d && d.orders && d.orders.length) cancelAll(d.symbol); break;
    case "cancelAll": post("/api/trade/cancel_all", {}).then(out => toast(`Cancelled ${out.cancelled} working order${out.cancelled === 1 ? "" : "s"}`, true)); break;
    case "flatten": if (d) flatten(d.symbol); break;
    case "reverse": if (d && d.position && d.position.qty) confirmBox(`REVERSE ${d.symbol}`, "closes the position and opens the same size the other way", "s", async () => { const out = await post("/api/trade/reverse", {symbol: d.symbol}); toast(out.ok ? "Reverse sent" : "Blocked: " + (out.reason || ""), out.ok); }); break;
    case "joinBid": if (d && d.bid) sendOrder(d.symbol, "BUY", d.bid); break;
    case "joinAsk": if (d && d.ask) sendOrder(d.symbol, "SELL", d.ask); break;
    case "rec": if (state && state.replay) post("/api/replay", {paused: !state.replay.paused}); else deskRec(); break;
    case "mark": deskMark(); break;
    case "mic": document.getElementById("micBtn").click(); break;
    case "clip": document.getElementById("clipBtn").click(); break;
    case "shot": deskShot(); break;
    case "arm": document.getElementById("armBtn").click(); break;
  }
  return true;
}

/* ---------- voice: reload buyer / seller only, active tab only */
function reloadWords(a){
  // the numbers are the ladder's own: the size showing at that price when the call fires, exact, never rounded.
  // "traded into it" is every print that hit the level while it refilled, so it can add up past anything the ladder shows at once
  const who = a.side === "bid" ? "buyer" : "seller", num = n => Math.round(n).toLocaleString("en-US");
  const n = a.refreshes != null ? a.refreshes : null;
  const showing = a.showing != null ? `${num(a.showing)} showing.` : "";
  const traded = a.absorbed ? ` He's ${a.side === "bid" ? "bought" : "sold"} ${num(a.absorbed)}${a.dollars ? ", " + (a.dollars >= 1e6 ? (a.dollars / 1e6).toFixed(1) + " million dollars" : Math.round(a.dollars / 1e3) + " thousand dollars") : ""}.` : "";
  if (a.label.startsWith("RELOAD") && a.back){ const nth = {2: "second", 3: "third", 4: "fourth"}[a.back.n] || (a.back.n + "th"), mins = Math.max(1, Math.round((a.back.away || 0) / 60));
    return `The reload ${who} at ${px(a.price)} is back. ${nth} visit. He was ${a.back.prior === "PULLED" ? "pulled" : "cleaned up"} ${mins} minute${mins === 1 ? "" : "s"} ago and he's refilling again.${a.absorbed_all ? ` He's ${a.side === "bid" ? "bought" : "sold"} ${num(a.absorbed_all)} across every visit.` : ""}`; }
  // the tell, said the way a tape reader says it: who is reloading, how much the other side has thrown into him, and
  // when his liquidity is gone and price goes through, that he is exhausted
  const took = a.absorbed_all || a.absorbed;
  const other = a.side === "bid" ? "Sellers hit him for" : "Buyers absorbed";
  if (a.label.startsWith("RELOAD")) return `${who === "buyer" ? "Buyer" : "Seller"} reloading at ${px(a.price)}.${took ? ` ${other} ${num(took)} shares.` : ""}${n != null ? ` Refilled ${n} time${n === 1 ? "" : "s"}.` : ""} ${showing}`.trim();
  if (a.label === "CLEANED UP") return `${who === "buyer" ? "Buyer" : "Seller"} exhausted at ${px(a.price)}${took ? ` after ${num(took)} shares` : ""}. ${a.side === "bid" ? "Sellers" : "Buyers"} breaking through.`;
  if (a.label === "PULLED") return `Reload ${who} at ${px(a.price)} pulled.`;
  return null;
}
const voiceFlow = () => store.get("voiceFlow", true);      // option flow in the voice
const solo = () => store.get("solo", false);                // THIS TICKER: voice and the flow panel follow the active tab only
const FLOW_ROLES = new Set(["flow", "dough", "urgency", "equity"]);
function speakNew(s){
  const items = [];
  for (const a of (s.alerts || []).slice(0, 8)){
    if (spoken.has("a" + a.key) || s.now - a.t > 8) continue;   // stale calls stay quiet: the ladder has moved on
    spoken.add("a" + a.key);
    if (training()) continue;                                    // training mode says nothing
    const mine = a.symbol === TABS.active;
    if (a.role === "alert"){ if (a.words) items.push(a.words.includes(a.symbol) ? a.words : `${a.symbol}. ${a.words}`); continue; }   // YOUR alerts: always said, any ticker
    if (a.role === "conviction"){ if (a.words && (mine || !solo())) items.push(a.words); continue; }   // READY TO GO / AGAINST YOU
    const isFlow = FLOW_ROLES.has(a.role) || /^UNUSUAL|REPEAT FLOW|FLOW/.test(a.label || "");
    if (isFlow){ const fw = flowWords(a); if (fw && voiceFlow() && (mine || !solo())) items.push(fw); continue; }
    if (a.role === "flip"){ if (a.words && mine) items.push(a.words); continue; }   // FLIP at a level: the tab you are on
    if (a.role === "trap" || a.role === "breaktrap"){ if (a.words && mine) items.push(a.words); continue; }   // trapped crowd / BREAK TRAPS: the tab you are on
    if (a.role === "inst"){ if (a.words && mine && store.get("voiceInst", true)) items.push(a.words); continue; }   // a program / fund footprint
    if (a.role === "dark"){ if (a.words && mine && store.get("voiceDark", true)) items.push(a.words); continue; }   // a large order
    // THE PS60 STORY: your trade and your second entry first, the reload buyer / seller and the money next, the levels
    // and the averages after that, the colour last. The tab you are on. One mouth: a bigger moment drops the smaller
    // ones still waiting, and the colour is said at most once every voiceGapSecs
    if (a.role === "story"){ if (a.words && mine) items.push({text: a.words, pri: +a.pri || 3, sym: a.symbol}); continue; }
    // the KEY LEVELS (rejected / bounced / took) and the PACE at them (pushing / stalling / breakout): the tab you are on
    if (a.role === "level" || a.role === "pace"){
      // AT / COMING INTO said only while it is still true: price that already left the level is not "at" it
      if ((a.label === "AT" || a.label === "COMING INTO") && a.zone){ const d = dataFor(s, a.symbol), lp = d && +d.last;
        if (lp && Math.abs(lp - +a.price) > (a.label === "AT" ? 1.5 : 3) * a.zone) continue; }
      if (a.words && mine && store.get("voiceLevels", true)) items.push(a.words); continue; }
    if (!mine) continue;                                         // background tabs never speak
    const w = reloadWords(a); if (w) items.push(w);
  }
  if (voiceFirst){ voiceFirst = false; return; }
  if (!store.get("voice", true)) return;
  // the story lines: the highest priority first; the colour (4) only when nothing bigger is in the same batch and it
  // has been quiet for a while on that ticker
  const story = items.filter(x => typeof x === "object").sort((a, b) => a.pri - b.pri), plain = items.filter(x => typeof x === "string");
  for (const t of plain.slice(-4)) say(t);                       // a reloader AND the flow on him both get said, in order
  if (story.length){
    const top = story[0].pri, gap = (+store.get("voiceGapSecs", 20) || 20) * 1000, now = Date.now();
    window._lastLow = window._lastLow || {};
    for (const x of story.slice(0, 2)){
      if (x.pri >= 4 && (x.pri > top || now - (window._lastLow[x.sym] || 0) < gap)) continue;
      if (x.pri >= 3) window._lastLow[x.sym] = now;
      say(x.text, false, x.pri);
    }
  }
}
function renderVoiceBtns(){
  const f = document.getElementById("voiceFlowBtn"), so = document.getElementById("soloBtn");
  if (f){ f.textContent = voiceFlow() ? "FLOW VOICE" : "FLOW MUTED"; f.classList.toggle("off", !voiceFlow()); }
  if (so){ so.textContent = solo() ? "THIS TICKER" : "ALL TICKERS"; so.classList.toggle("on", solo()); }
}
document.getElementById("voiceFlowBtn").addEventListener("click", () => { store.set("voiceFlow", !voiceFlow()); renderVoiceBtns(); say(voiceFlow() ? "Flow voice on." : "Flow voice off. Reloaders only.", true); });
document.getElementById("soloBtn").addEventListener("click", () => { store.set("solo", !solo()); renderVoiceBtns(); const el = document.getElementById("flowList"); if (el) el.dataset.h = ""; if (state) renderFlow(state); say(solo() ? "This ticker only." : "All tickers.", true); });
renderVoiceBtns();
document.getElementById("replayBtn").addEventListener("click", () => replayLast());
/* THE DESK THEME: white (light) or dark, for the whole desk (the ladder, the tape, the panels). The chart keeps its own
   screen colour. Saved per browser */
(function(){ const b = document.getElementById("deskTheme"); if (!b) return;
  const paint = () => { const w = store.get("deskTheme", "white") === "white"; document.body.classList.toggle("whitedesk", w); b.textContent = w ? "DESK WHITE" : "DESK DARK"; }; paint();
  b.addEventListener("click", () => { store.set("deskTheme", store.get("deskTheme", "white") === "white" ? "dark" : "white"); paint(); if (P.book) P.book.last = null; if (P.tape) P.tape.last = null; Object.values(charts || {}).forEach(c => { try { drawChart(c); } catch (e) {} }); }); })();
document.getElementById("voiceBtn").addEventListener("click", () => { const on = !store.get("voice", true); store.set("voice", on); document.getElementById("voiceBtn").textContent = on ? "VOICE ON" : "VOICE OFF"; if (on) say("Voice on.", true); renderTabs(); });
document.getElementById("voiceVol").value = store.get("voiceVol", 1);
document.getElementById("voiceVol").addEventListener("change", e => store.set("voiceVol", +e.target.value));

/* ---------- status bar + command bar */
const PAGE_BUILD = (document.querySelector('meta[name="build"]') || {}).content || "";
/* OPTION FLOW: the feed, shaped like FlowAlgo. Green = calls, red = puts; the dot row is the trade type;
   a gold WAYS AWAY tag marks size bought at the ask well out of the money. */
const kfmt$ = v => v >= 1e6 ? "$" + (v / 1e6).toFixed(v >= 1e7 ? 0 : 1) + "M" : v >= 1e3 ? "$" + Math.round(v / 1e3) + "K" : "$" + Math.round(v);
// ONE TICKER'S FLOW: a ticker typed in the box (or the panel locked to your stock) loads EVERY print the desk holds for it
// today, not just the market-wide latest. A call's RECEIPT (🔎 FLOW on the call) shows exactly the prints it added up.
const FSYM = {sym: "", data: null, at: 0, busy: false};
let FLOWREF = null, FLOWREF_ALL = false;
function fetchFlowSym(sym){
  if (FSYM.busy || (sym === FSYM.sym && Date.now() - FSYM.at < 1500)) return;
  FSYM.busy = true;
  fetch("/api/flow/symbol?s=" + encodeURIComponent(sym)).then(r => r.json()).then(j => { FSYM.sym = sym; FSYM.data = j; FSYM.at = Date.now(); })
    .catch(() => {}).finally(() => { FSYM.busy = false; if (state) renderFlow(state); });
}
function showFlowRef(ref){
  if (!ref || !ref.ids || !ref.ids.length) return;
  FLOWREF = Object.assign({}, ref, {idset: new Set(ref.ids)}); FLOWREF_ALL = false;
  const f = document.getElementById("flowFilter"); if (f) f.value = ref.symbol;
  if (typeof showPanel === "function") showPanel("flow");
  FSYM.at = 0; if (state) renderFlow(state);
}
function renderFlow(s){
  const el = document.getElementById("flowList"); if (!el) return;
  const filt = (document.getElementById("flowFilter").value || "").trim().toUpperCase();
  const onlyU = document.getElementById("flowUnusual").checked, mine = document.getElementById("flowMine").checked;
  const fc = (state && state.flow_cfg) || {otm_pct: 3, min_premium: 250000};
  if (FLOWREF && filt !== FLOWREF.symbol) FLOWREF = null;          // you typed another ticker: that call's receipt is closed
  const one = filt || (solo() ? curSym : "");
  if (one) fetchFlowSym(one);
  const full = one && FSYM.sym === one && FSYM.data ? FSYM.data : null;
  let base = full && full.prints.length ? full.prints : (s.flow || []);
  if (FLOWREF && !FLOWREF_ALL) base = base.filter(p => FLOWREF.idset.has(p.id));
  const rows = base.filter(p => (!filt || p.symbol.startsWith(filt)) && (one || !mine || (s.symbols || []).includes(p.symbol)) && (!solo() || p.symbol === curSym))
    .map(p => { const away = p.side === "ask" && p.otm_pct != null && p.otm_pct >= fc.otm_pct && p.premium >= 50000; return Object.assign({away}, p); })
    .filter(p => FLOWREF || !onlyU || p.away).slice(0, full ? 400 : 60);
  // the call you clicked: what it said, and the prints it counted (their total is the number you heard)
  let head = "";
  if (FLOWREF){
    const got = (full ? full.prints : (s.flow || [])).filter(p => FLOWREF.idset.has(p.id)), tot = got.reduce((a, p) => a + (p.premium || 0), 0);
    head = `<div class="fref"><b>THE CALL</b> ${kfmt$(FLOWREF.dollars)} of ${esc(FLOWREF.symbol)} ${FLOWREF.cp === "C" ? "CALLS" : "PUTS"} · ${FLOWREF.prints} print${FLOWREF.prints === 1 ? "" : "s"}${FLOWREF.what ? " · " + esc(FLOWREF.what) : ""}`
      + (full && got.length < FLOWREF.ids.length ? ` <span class="dim">(${got.length} of ${FLOWREF.ids.length} still in today's memory, ${kfmt$(tot)})</span>` : "")
      + `<span class="frb"><button data-fref="all">${FLOWREF_ALL ? "ONLY THESE" : "ALL " + esc(FLOWREF.symbol)}</button><button data-fref="x" title="close">✕</button></span></div>`;
  }
  // one ticker: the read the voice uses on it right now (short-dated, out of the money, bought at the ask)
  if (full && full.reads && !FLOWREF){
    const r = full.reads, b = cp => { const x = r[cp] || {}; return `<button class="${cp === "C" ? "c" : "p"} ${x.knows ? "kn" : ""}" data-fread="${cp}" ${x.ids && x.ids.length ? "" : "disabled"} title="show these prints">${cp === "C" ? "CALLS" : "PUTS"} ${kfmt$(x.dollars || 0)} · ${x.prints || 0}${x.knows ? " · SOMEBODY KNOWS" : ""}</button>`; };
    const c = r.C || {};
    head = `<div class="fread"><span>${esc(full.symbol)} · last ${c.window_minutes || 10} min · ${c.max_dte != null ? c.max_dte : 7} days or less · out of the money · bought at the ask</span>${b("C")}${b("P")}</div>`;
  }
  const src = document.getElementById("flowSrc"), fsim = !!(s.feeds && s.feeds.options && s.feeds.options.label === "SIM");
  const st = s.connection && s.connection.state === "DEMO" ? "PRACTICE FLOW" : fsim ? "SIM · market closed" : "QUANT DATA";
  if (src.textContent !== st){ src.textContent = st; src.classList.toggle("simtag", fsim); src.title = fsim ? s.feeds.options.detail : ""; }
  { const pn = src.closest(".pnl"); if (pn) pn.classList.toggle("simmode", fsim); }
  const exp = e => { if (!e) return NA; const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(e); return m ? `${m[2]}/${m[3]}/${m[1].slice(2)}` : e; };
  const strike = k => Number.isInteger(k) ? String(k) : (+k).toFixed(2).replace(/\.?0+$/, "");
  const typ = p => p.kind === "sweep" ? `<b class="ic o"></b>S` : p.kind === "block" ? `<b class="ic sq"></b>B` : p.kind === "split" ? `<b class="ic eq">=</b>S` : `<b class="ic dot"></b>T`;
  const urgent = new Set((s.urgency || []).filter(u => u.hot).map(u => u.key));
  // somebody may know something: SIZE bought at the ask that expires today / this week, and the same far-out strike
  // being bought again and again (counted over the whole feed, not just the rows on screen)
  const KNOW_USD = fc.know_premium || 100000, dteOf = p => p.dte != null ? +p.dte : (p.expiry ? (new Date(p.expiry + "T16:00:00-04:00") - new Date(p.t * 1000)) / 864e5 : null);
  const again = {};
  for (const p of (s.flow || [])) if (p.side === "ask" && p.premium >= 50000){ const k = [p.symbol, p.strike, p.cp, p.expiry].join("|"); again[k] = (again[k] || 0) + 1; }
  const html = rows.length ? rows.map(p => { const d = new Date(p.t * 1000), cp = p.cp === "C" ? "C" : "P"; const urg = urgent.has([p.symbol, p.strike, p.cp, p.expiry].join("|"));
    const dte = dteOf(p), sized = p.side === "ask" && p.premium >= KNOW_USD;
    const soon = sized && dte != null && dte < 1 ? "EXPIRES TODAY" : sized && dte != null && dte <= 5 ? "THIS WEEK" : "";
    const n = again[[p.symbol, p.strike, p.cp, p.expiry].join("|")] || 0, far = p.otm_pct != null && p.otm_pct >= fc.otm_pct;
    const rep = p.side === "ask" && n >= 2 && far ? `AGAIN ×${n} · ${p.otm_pct.toFixed(0)}% OUT` : "";
    const deep = p.otm_pct != null && p.otm_pct <= -3 ? `${Math.abs(p.otm_pct).toFixed(0)}% IN THE MONEY` : "";
    return `<div class="fl ${cp === "C" ? "c" : "p"} ${p.away ? "away" : ""} ${soon || rep ? "know" : ""} ${FLOWREF && FLOWREF.idset.has(p.id) ? "said" : ""}" title="${p.side === "ask" ? "bought at the ask" : p.side === "bid" ? "sold at the bid" : "mid"}${p.otm_pct != null ? ` · ${p.otm_pct > 0 ? p.otm_pct.toFixed(1) + "% out of the money" : Math.abs(p.otm_pct).toFixed(1) + "% in the money"}` : ""}${soon ? " · size this close to expiry: somebody may know something" : ""}${rep ? " · the same far-out strike keeps getting bought with size" : ""}${deep ? " · deep in the money: delta near one, moves dollar for dollar with the stock. That is a hedge or stock replacement, not a bet on a move — not the short-dated out-of-the-money dough we wait for" : ""}">
      <div class="tm">${nyHM12(p.t)}</div>
      <div class="top"><span class="tk">${esc(p.symbol)}</span><span class="prem">${kfmt$(p.premium)}</span><span class="dots ${p.side === "ask" ? "a" : ""}">${p.kind === "sweep" || p.kind === "split" ? "<i></i><i></i>" : p.kind === "block" ? "<i></i>" : ""}</span>${soon ? `<span class="kn">${soon}</span>` : ""}${rep ? `<span class="kn rep">${rep}</span>` : ""}${deep ? `<span class="itm">${deep}</span>` : ""}${p.away && !rep ? `<span class="aw">WAYS AWAY</span>` : ""}${urg ? `<span class="urg" title="this contract is being bought in a hurry: short-dated, out of the money, print after print">⚡ URGENT</span>` : ""}</div>
      <div class="cols"><span><i>EXP</i>${exp(p.expiry)}</span><span><i>STRIKE</i>${strike(p.strike)}</span><span><i>C/P</i>${cp}</span><span><i>SPOT</i>${p.spot != null ? (+p.spot).toFixed(2) : NA}</span><span><i>TYPE</i><span class="ty">${typ(p)}</span></span><span><i>DETAILS</i>${sz(p.size)} @ ${p.price != null ? p.price.toFixed(2) : NA}</span></div></div>`; }).join("")
    : `<div class="dim" style="padding:10px">${(s.flow || []).length ? "Nothing matches the filter." : (s.connection && s.connection.state === "DEMO" ? "Practice flow is warming up." : "No option flow. Add your Quant Data key in SETTINGS, Quant Data, then RESTART NOW.")}</div>`;
  const out = head + html;
  if (el.dataset.h !== out){ el.dataset.h = out; el.innerHTML = out; }
}
document.getElementById("flowList").addEventListener("click", ev => {
  const a = ev.target.closest("[data-fref]"), r = ev.target.closest("[data-fread]");
  if (a){ if (a.dataset.fref === "x") FLOWREF = null; else FLOWREF_ALL = !FLOWREF_ALL; renderFlow(state); return; }
  if (r && FSYM.data && FSYM.data.reads){ const x = FSYM.data.reads[r.dataset.fread] || {};
    showFlowRef({symbol: FSYM.data.symbol, cp: r.dataset.fread, ids: x.ids || [], dollars: x.dollars, prints: x.prints,
                 what: `${x.max_dte} days or less, out of the money, bought at the ask, last ${x.window_minutes} min`}); }
});
document.getElementById("flowScope").addEventListener("click", async () => {
  const on = !(state && state.flow_scope !== "watchlist");
  const out = await post("/api/flow", {scope: on ? "all" : "watchlist"});
  if (out.ok){ savePrefs({flowScope: out.scope}); toast(out.scope === "all" ? "Whole market flow ON" : "Whole market flow OFF: watchlist only", true); poll(true); }
});
document.getElementById("flowAlerts").addEventListener("click", async () => {
  const all = !(state && state.flow_alerts === "all");
  const out = await post("/api/flow", {alerts: all ? "all" : "watchlist"});
  if (out.ok){ savePrefs({flowAlerts: out.alerts}); toast(out.alerts === "all" ? `UNUSUAL alerts for every ticker (index products need ${kfmt$(state.flow_index_min || 5e6)}+)` : "UNUSUAL alerts: watchlist only", true); poll(true); }
});
function renderFlowScope(s){ const a = document.getElementById("flowAlerts"); if (a){ const all = s.flow_alerts === "all"; a.classList.toggle("on", all); const t = all ? "ALL" : "WATCHLIST"; if (a.querySelector("b").textContent !== t) a.querySelector("b").textContent = t; }
  const b = document.getElementById("flowScope"); if (!b) return; const on = s.flow_scope !== "watchlist"; b.classList.toggle("on", on); const t = on ? "ON" : "OFF"; if (b.lastChild.textContent !== t) b.querySelector("b").textContent = t; }
["flowFilter", "flowUnusual", "flowMine"].forEach(id => document.getElementById(id).addEventListener("input", () => renderFlow(state)));
function flowWords(a){
  if (a.words) return `${a.symbol}: ${a.words}`;                                   // PRICE ALERT / FLOW ALERT / EQUITY FLOW
  if (a.label === "REPEAT FLOW"){ const what = a.cp === "C" ? "call" : "put"; return `${a.symbol}: repeat ${what} flow, ${px(a.strike)} strike${a.dte != null ? ", " + Math.round(a.dte) + " days out" : ""}, ${a.premium >= 1e6 ? (a.premium / 1e6).toFixed(1) + " million" : Math.round(a.premium / 1e3) + " thousand"} total.`; }
  if (!/^UNUSUAL/.test(a.label)) return null;
  const what = a.cp === "C" ? "call" : "put";
  return `${a.symbol}: unusual ${what} buying, ${a.premium >= 1e6 ? (a.premium / 1e6).toFixed(1) + " million" : Math.round(a.premium / 1e3) + " thousand"} premium${a.otm_pct != null ? ", " + Math.round(a.otm_pct) + " percent out of the money" : ""}${a.dte != null ? ", " + Math.round(a.dte) + " days out" : ""}.`;
}
/* THE TRADE JOURNAL. On top: the trade(s) you are IN — name it while you trade, the plan, live P&L, every order /
   fill / line / mark / spoken word so far. Below: every closed trade with its RESULT (win / loss, $, %, R against the
   stop you planned), the name, setup, grade and note to fill in, ▸ for the transcript, the marks (what the screen showed)
   and the whole log, and SAVE (one page per trade in recordings/journal, re-saved whenever you change it). */
const JOPEN = new Set();
const money2 = v => v == null ? NA : (v >= 0 ? "+$" : "−$") + Math.abs(v).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
function tradeDetails(t){
  const tr = (t.transcript || []), mk = (t.marks || []), lg = (t.log || "").split(" | ").filter(Boolean);
  return `<div class="jdet">
    <div><b>🎙 WHAT YOU SAID</b>${tr.length ? tr.map(x => `<div class="jl"><i>${nyHM(x.t)}</i> ${esc(x.text)}</div>`).join("") : `<div class="dim">nothing recorded — press MIC while you trade</div>`}</div>
    <div><b>⚑ MARKS</b>${mk.length ? mk.map(m => `<div class="jl"><i>${nyHM(m.t)}</i> ${m.price != null ? px(m.price) : ""} ${esc(m.note || "")}<span class="dim"> ${esc(m.context || "")}</span>${m.shot ? ` <a href="/recordings/${esc(m.shot)}" target="_blank">📷</a>` : ""}</div>`).join("") : `<div class="dim">no marks — press MARK (M) to capture the screen</div>`}</div>
    <div><b>EVERYTHING THAT HAPPENED</b>${lg.length ? lg.map(x => `<div class="jl">${esc(x)}</div>`).join("") : `<div class="dim">—</div>`}</div></div>`;
}
function planTxt(p){ p = p || {}; return [["trigger", "pivot"], ["second_entry", "2nd"], ["stop", "stop"], ["target", "target"]].filter(([k]) => p[k]).map(([k, n]) => `${n} ${px(p[k])}`).join(" · ") || "no lines drawn"; }
function renderTrades(s){
  const el = document.getElementById("jTrades"); if (!el) return;
  const D = s.desk || {}, trades = (D.trades || []).slice().reverse(), open = D.open || [];
  const unit = t => t.opt ? "ct" : "sh";
  const openH = open.map(t => `<div class="jopen" data-id="${esc(t.id)}">
      <div class="jh"><span class="live">● IN TRADE</span><input data-tname="${esc(t.id)}" value="${esc(t.name || "")}" placeholder="name this play" title="name the play — it is saved with the trade">
        <b class="${t.side === "long" ? "b" : "s"}">${esc(t.symbol)} ${t.side.toUpperCase()} ${sz(Math.abs(t.qty || t.entry_qty || 0))} ${unit(t)}</b>
        <span>@ ${t.opt ? (+t.entry).toFixed(2) : px(t.entry)} · now ${t.now != null ? (t.opt ? (+t.now).toFixed(2) : px(t.now)) : NA}</span>
        <b class="${(t.pnl || 0) >= 0 ? "b" : "s"}">${money2(t.pnl)}</b>
        <span class="dim">plan: ${esc(planTxt(t.plan))}</span>
        <span class="dim">🎙 ${(t.transcript || []).length} · ⚑ ${(t.marks || []).length}</span></div>
      ${tradeDetails(t)}</div>`).join("");
  const n = trades.length, tot = trades.reduce((a, t) => a + (t.pnl || 0), 0), w = trades.filter(t => t.result === "WIN" || (!t.result && (t.pnl || 0) > 0)).length, l = trades.filter(t => t.result === "LOSS" || (!t.result && (t.pnl || 0) < 0)).length;
  const head = `<h5>TRADES <a class="btn" href="/api/desk/trades.csv" download title="the whole journal as a spreadsheet" style="float:right;font-size:10px;padding:1px 8px">EXPORT</a>${n ? `<span class="dim">${n} · <b class="${tot >= 0 ? "b" : "s"}">${money2(tot)}</b> · ${w}W / ${l}L${w + l ? ` · ${Math.round(100 * w / (w + l))}% wins` : ""}</span>` : ""}</h5>`;
  const rows = trades.map(t => { const res = t.result || ((t.pnl || 0) > 0 ? "WIN" : (t.pnl || 0) < 0 ? "LOSS" : "SCRATCH"), op = JOPEN.has(t.id);
    return `<tr data-id="${esc(t.id)}" class="${op ? "open" : ""}">
      <td class="l"><button class="jx" data-jx="${esc(t.id)}" title="the transcript, the marks and everything that happened">${op ? "▾" : "▸"}</button> ${nyT(t.closed || t.opened)}</td>
      <td class="l"><input class="jname" data-tname="${esc(t.id)}" value="${esc(t.name || "")}" placeholder="name this play"></td>
      <td class="l">${esc(t.symbol)}</td><td class="${t.side === "long" ? "b" : "s"}">${t.side.toUpperCase()} ${sz(t.shares || 0)}${t.opt ? " ct" : ""}</td>
      <td>${t.opt ? (+t.entry).toFixed(2) : px(t.entry)} → ${t.opt ? (+t.exit).toFixed(2) : px(t.exit)}</td>
      <td><span class="res ${res.toLowerCase()}">${res}</span> <b class="${(t.pnl || 0) >= 0 ? "b" : "s"}">${money2(t.pnl)}</b> <span class="dim">${t.pnl_pct != null ? (t.pnl_pct >= 0 ? "+" : "") + t.pnl_pct.toFixed(2) + "%" : ""}</span></td>
      <td title="the result in R: the move against the stop you planned (${esc(planTxt(t.plan))})">${t.r != null ? (t.r >= 0 ? "+" : "") + t.r.toFixed(2) + "R" : NA}</td>
      <td class="l">${setupSel("", t.setup, `data-tsetup="${esc(t.id)}"`)}</td>
      <td><select data-tgrade="${esc(t.id)}"><option value="">—</option>${["A+", "A", "B", "C", "F"].map(g => `<option ${t.grade === g ? "selected" : ""}>${g}</option>`).join("")}</select></td>
      <td class="l"><input data-tnote="${esc(t.id)}" value="${esc(t.note || "")}" placeholder="what you saw, what you did"></td>
      <td><button data-jsave="${esc(t.id)}" title="${t.file ? "saved: recordings/journal/" + esc(t.file) + " — save again" : "save this trade's page"}">${t.file ? "✓ SAVED" : "SAVE"}</button></td></tr>
      ${op ? `<tr class="jdetrow"><td colspan="11">${tradeDetails(t)}</td></tr>` : ""}`; }).join("");
  const html = openH + head + (n ? `<table class="grid trades"><tr><th>TIME</th><th class="l">PLAY</th><th class="l">SYM</th><th>SIDE</th><th>IN → OUT</th><th>RESULT</th><th>R</th><th class="l">SETUP</th><th>GRADE</th><th class="l">NOTE</th><th></th></tr>${rows}</table>`
    : `<div class="dim">No closed trades yet. Every trade you take — stock or option — lands here when it is flat: named, with its result, what you said and what you marked.</div>`);
  if (el.dataset.h !== html && !el.contains(document.activeElement)){ el.dataset.h = html; el.innerHTML = html; }
}
document.addEventListener("change", async e => {
  const k = e.target.dataset.tsetup ? "setup" : e.target.dataset.tgrade ? "grade" : e.target.dataset.tnote ? "note" : e.target.dataset.tname ? "name" : null; if (!k) return;
  const id = e.target.dataset.tsetup || e.target.dataset.tgrade || e.target.dataset.tnote || e.target.dataset.tname;
  const out = await post("/api/desk/trade", {id, [k]: e.target.value}); if (out.ok) toast(k === "name" ? "Play named: " + e.target.value : "Journal updated", true); const el = document.getElementById("jTrades"); if (el) el.dataset.h = ""; poll(true);
});
document.addEventListener("keydown", e => { if (e.target.dataset && e.target.dataset.tname && e.key === "Enter") e.target.blur(); });
document.addEventListener("click", async e => {
  const x = e.target.closest("button[data-jx]"); if (x){ const id = x.dataset.jx; JOPEN.has(id) ? JOPEN.delete(id) : JOPEN.add(id); const el = document.getElementById("jTrades"); if (el) el.dataset.h = ""; renderTrades(state); return; }
  const sv = e.target.closest("button[data-jsave]"); if (sv){ const out = await post("/api/desk/save_trade", {id: sv.dataset.jsave}); toast(out.ok ? "Saved: " + out.dir + "/" + out.file : "Not saved: " + (out.reason || ""), out.ok); const el = document.getElementById("jTrades"); if (el) el.dataset.h = ""; poll(true); }
});
/* training mode: the desk stops telling you where the reload buyers and sellers are. You read the tape; REVEAL checks your call. */
function training(){ return store.get("training", false) && (state ? state.now : 0) > (window._revealUntil || 0); }
/* SETTINGS: every setting on the desk, saved to config.json for you */
const SET = {sections: null, dirty: {}, cur: null, restartPending: false};
async function openSettings(){
  const r = await fetch("/api/settings", {cache: "no-store"}); const j = await r.json();
  SET.sections = j.sections; SET.dirty = {}; SET.canRestart = j.can_restart; SET.cur = SET.cur || j.sections[0].key;
  document.getElementById("settings").hidden = false; renderSettings(); document.getElementById("setFind").focus();
}
function setField(f){
  const id = "sf_" + f.path.replace(/\./g, "_"), dis = f.locked ? "disabled" : "", v = SET.dirty.hasOwnProperty(f.path) ? SET.dirty[f.path] : f.value;
  let inp;
  if (f.type === "bool") inp = `<label class="sw"><input type="checkbox" id="${id}" data-path="${f.path}" ${v ? "checked" : ""} ${dis}><span></span></label>`;
  else if (f.type === "select") inp = `<select id="${id}" data-path="${f.path}" ${dis}>${f.choices.map(c => `<option value="${esc(JSON.stringify(c.value))}" ${JSON.stringify(c.value) === JSON.stringify(v) ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select>`;
  else if (f.type === "secret") inp = `<div class="keyst ${f.set ? "ok" : "no"}">${f.set ? "KEY SAVED " + esc(f.hint) + " · in use now (the box below stays empty on purpose; the key is never shown again)" : "NO KEY SAVED"}</div><input type="password" id="${id}" data-path="${f.path}" placeholder="${f.set ? "type a new key here only to replace it" : "paste your key, then SAVE"}" autocomplete="off">${f.set ? `<button data-clear="${f.path}">REMOVE</button>` : ""}`;
  else if (f.type === "color") inp = `<input type="color" id="${id}" data-path="${f.path}" value="${esc(v || "#9e9e9e")}" ${dis}> <span class="mono dim">${esc(v || "")}</span>`;
  else if (f.type === "json") inp = `<textarea id="${id}" data-path="${f.path}" rows="2" spellcheck="false" ${dis}>${esc(v)}</textarea>`;
  else inp = `<input type="${f.type === "int" || f.type === "float" ? "number" : "text"}" ${f.type === "float" ? 'step="any"' : ""} id="${id}" data-path="${f.path}" value="${esc(v == null ? "" : v)}" ${dis}>`;
  return `<div class="sf ${SET.dirty.hasOwnProperty(f.path) ? "dirty" : ""} ${f.locked ? "locked" : ""}"><div class="sl"><b>${esc(f.label)}</b>${f.restart ? `<i class="rs" title="saved at once, used after RESTART NOW">RESTART</i>` : `<i class="lv" title="takes effect the moment you save">LIVE</i>`}<div class="sh">${esc(f.locked || f.help || "")}</div><code>${esc(f.path)}</code></div><div class="si">${inp}</div></div>`;
}
function renderSettings(){
  const q = (document.getElementById("setFind").value || "").trim().toLowerCase();
  const secs = SET.sections || [];
  const match = f => !q || (f.label + " " + f.help + " " + f.path).toLowerCase().includes(q);
  document.getElementById("setNav").innerHTML = secs.map(s => { const n = s.fields.filter(match).length; const d = s.fields.filter(f => SET.dirty.hasOwnProperty(f.path)).length;
    return `<div class="sn ${s.key === SET.cur && !q ? "on" : ""} ${n ? "" : "none"}" data-sec="${s.key}">${esc(s.title)}${d ? ` <i>${d}</i>` : ""}${q && n ? ` <span class="dim">${n}</span>` : ""}</div>`; }).join("");
  const show = q ? secs.filter(s => s.fields.some(match)) : secs.filter(s => s.key === SET.cur);
  document.getElementById("setForm").innerHTML = show.map(s => `<div class="ss"><h4>${esc(s.title)}</h4><div class="sb">${esc(s.blurb)}</div>${s.key === "speech" ? `<div class="vtest"><button id="voiceTest" type="button">TEST VOICE</button> <span id="voiceTestOut" class="dim">says one line in your ElevenLabs voice and tells you if it answered (save changes first)</span></div>` : ""}${s.fields.filter(match).map(setField).join("")}</div>`).join("") || `<div class="dim" style="padding:20px">No setting matches.</div>`;
  const n = Object.keys(SET.dirty).length;
  const sv = document.getElementById("setSave"); sv.disabled = !n; sv.textContent = n ? `SAVE ${n}` : "SAVE";
  document.getElementById("setRestart").hidden = !(SET.restartPending && SET.canRestart);
}
function readInput(el){
  const path = el.dataset.path, f = SET.sections.flatMap(s => s.fields).find(x => x.path === path); if (!f) return;
  let v = f.type === "bool" ? el.checked : f.type === "select" ? JSON.parse(el.value) : el.value;
  if (path === "trading.allow_live" && v === true && !confirm("LIVE TRADING: with TWS logged into your LIVE account, orders from this desk are REAL MONEY.\n\nPaper (DU) accounts still work as before. Turn live trading ON?")) { el.checked = false; v = false; }
  if (f.type === "secret" && !v) { delete SET.dirty[path]; return; }
  const orig = f.type === "bool" ? !!f.value : f.value;
  if (String(v) === String(orig) && f.type !== "secret") delete SET.dirty[path]; else SET.dirty[path] = v;
}
document.getElementById("setBtn").addEventListener("click", openSettings);
document.getElementById("setClose").addEventListener("click", () => { if (Object.keys(SET.dirty).length && !confirm("Close without saving your changes?")) return; document.getElementById("settings").hidden = true; });
document.getElementById("setFind").addEventListener("input", renderSettings);
// TEST VOICE: ask ElevenLabs for one line (not the cache), say if it answered, and play it
document.getElementById("setForm").addEventListener("click", async e => {
  if (!e.target.closest("#voiceTest")) return;
  const out = document.getElementById("voiceTestOut"); out.className = "dim"; out.textContent = "asking ElevenLabs…";
  try {
    const j = await (await fetch("/api/tts/test")).json();
    out.className = j.ok ? "vok" : "vbad"; out.textContent = (j.ok ? "✓ " : "✗ ") + j.reason;
    if (j.ok){ const a = new Audio("/api/tts?text=" + encodeURIComponent("Voice check. The desk is live.")); a.play().catch(() => {}); }
  } catch (err) { out.className = "vbad"; out.textContent = "✗ the desk did not answer"; }
});
document.getElementById("setNav").addEventListener("click", e => { const s = e.target.closest("[data-sec]"); if (!s) return; SET.cur = s.dataset.sec; document.getElementById("setFind").value = ""; renderSettings(); });
document.getElementById("setForm").addEventListener("change", e => { if (!e.target.dataset.path) return; readInput(e.target); const n = Object.keys(SET.dirty).length; const sv = document.getElementById("setSave"); sv.disabled = !n; sv.textContent = n ? `SAVE ${n}` : "SAVE"; e.target.closest(".sf").classList.toggle("dirty", SET.dirty.hasOwnProperty(e.target.dataset.path)); });
document.getElementById("setForm").addEventListener("input", e => { if (e.target.dataset.path && e.target.type !== "checkbox") e.target.dispatchEvent(new Event("change", {bubbles: true})); });
document.getElementById("setForm").addEventListener("click", e => { const c = e.target.dataset.clear; if (!c) return; if (!confirm("Remove the saved key?")) return; SET.dirty[c] = "__clear__"; renderSettings(); });
document.getElementById("setForm").addEventListener("keydown", e => e.stopPropagation());
document.getElementById("setFind").addEventListener("keydown", e => { e.stopPropagation(); if (e.key === "Escape") document.getElementById("setClose").click(); });
document.getElementById("setSave").addEventListener("click", async () => {
  const out = await post("/api/settings", {changes: SET.dirty});
  const m = document.getElementById("setMsg");
  if (!out.ok){ m.textContent = "NOT SAVED · " + out.reason; m.className = "no"; toast("Not saved: " + out.reason, false); return; }
  SET.sections = out.sections; SET.dirty = {};
  if (out.restart.length) SET.restartPending = true;
  m.className = "ok"; m.textContent = `SAVED ${out.applied.length}` + (out.restart.length ? ` · ${out.restart.length} after RESTART` : " · live now");
  toast(out.restart.length ? `Saved. ${out.restart.length} setting${out.restart.length > 1 ? "s apply" : " applies"} after RESTART NOW.` : "Saved. In effect now.", true);
  renderSettings(); poll(true);
});
document.getElementById("setRestart").addEventListener("click", async () => {
  if (!confirm("Restart TED now? Working orders stay at IBKR; the page reconnects by itself in a few seconds.")) return;
  const out = await post("/api/restart", {}); if (!out.ok){ toast(out.reason || "Restart not available", false); return; }
  SET.restartPending = false; document.getElementById("settings").hidden = true; toast("Restarting TED…", true);
});
function renderLeds(s){
  const f = s.feeds || {};
  for (const [id, k, name] of [["ledMkt", "market", "Market data"], ["ledOpt", "options", "Option data"]]){
    const el = document.getElementById(id), v = f[k]; if (!el || !v) continue;
    const cls = "ld " + v.color; if (el.className !== cls) el.className = cls;
    const tip = `${name}: ${v.label}\n${v.detail}`; if (el.title !== tip) el.title = tip;
  }
}
function renderStatus(s){
  renderLeds(s);
  document.querySelector("#stBuild b").textContent = PAGE_BUILD || "—";
  // an old tab left open from a previous run: reload it onto the build the server is now serving
  // only onto a NEWER build, and only once per build (a page newer than the server never loops)
  let _tried = null; try { _tried = sessionStorage.getItem("tedReloadedFor"); } catch (e) {}
  // the other way round: a NEW page on an OLD running TED (a build unzipped over the folder while TED was running).
  // Buttons the old program does not know would just fail: say so, plainly, until TED is restarted
  { let rb = document.getElementById("restartBanner");
    if (s.build && PAGE_BUILD && s.build < PAGE_BUILD){
      if (!rb){ rb = document.createElement("div"); rb.id = "restartBanner"; document.body.appendChild(rb); }
      rb.innerHTML = `<b>TED WAS UPDATED — RESTART IT.</b> The page is build ${esc(PAGE_BUILD)}, but the TED program still running is build ${esc(s.build)}. Close the black TED window, then start TED again (start_twiney). Until then some buttons (UNLOCK, ARM…) can't work.`;
    } else if (rb) rb.remove(); }
  if (s.build && PAGE_BUILD && s.build > PAGE_BUILD && _tried !== s.build && !window._reloading){ window._reloading = true; try { sessionStorage.setItem("tedReloadedFor", s.build); } catch (e) {} toast("New build " + s.build + " is running: reloading", true); setTimeout(() => location.reload(), 800); }
  const c = s.connection, t = s.trading || {};
  const led = document.querySelector("#stConn .led"), cls = c.state === "CONNECTED" ? "ok" : ["CONNECTING", "REPLAY", "DEMO"].includes(c.state) ? "warn" : "bad";
  led.className = "led " + cls; document.querySelector("#stConn b").textContent = c.state + (c.detail && c.state !== "CONNECTED" ? " · " + c.detail.slice(0, 40) : "");
  document.querySelector("#stData b").textContent = c.market_data_type ? (MDT[c.market_data_type] || c.market_data_type) : (c.state === "DEMO" ? "DEMO" : c.state === "REPLAY" ? "REPLAY" : NA);
  const oled = document.querySelector("#stOrders .led"); oled.className = "led " + (t.locked ? "bad" : t.can_trade ? (t.armed ? "ok" : "warn") : "bad");
  document.querySelector("#stOrders b").textContent = t.locked ? "LOCKED" : t.can_trade ? (t.armed ? "ARMED · " + (t.mode || "") : "READY · disarmed") : "OFF · " + (t.why_not || "");
  document.querySelector("#stLadders b").textContent = `${s.depth.length}/${s.slots}`;
  document.getElementById("stRec").innerHTML = s.desk && s.desk.recording ? `<span class="led bad"></span>REC <b>${fmtDur(s.now - (s.desk.started || s.now))}</b>` : "";
  if (t.pnl) document.querySelector("#stLoss b").textContent = `${t.pnl.total >= 0 ? "+" : "−"}$${sz(Math.abs(t.pnl.total).toFixed(0))}` + (t.loss_lock_on ? ` / −$${sz(t.max_daily_loss || 0)}` : " · no lock (paper)");
  document.getElementById("stClock").textContent = nyT(Date.now() / 1000) + " ET";
  const arm = document.getElementById("armBtn");
  // always visible: ARM / ARMED; LOCKED on a live account; on paper a lock is one click away from gone (UNLOCK)
  const paperLock = t.locked && !(t.mode === "LIVE" && t.allow_live);
  arm.textContent = paperLock ? "UNLOCK" : t.locked ? "LOCKED" : t.armed ? "ARMED" : "ARM"; arm.className = t.locked ? "locked" : t.armed ? "armed" : "off";
  arm.disabled = !t.can_trade && !paperLock; arm.title = paperLock ? "the daily loss lock is on — click to lift it (paper account), then ARM" : t.can_trade ? "" : (t.why_not || "");
  // the reason, in words, right beside the button — never only in a hover
  const why = document.getElementById("armWhy");
  if (why){ const acct = (t.accounts || []).filter(a => a && a !== "SIM").join(", ");
    const who = `${t.mode === "SIM" ? "PRACTICE" : t.mode === "NONE" ? "NO ACCOUNT YET" : t.mode}${acct ? " " + acct : ""}`;
    const txt = t.armed ? `${who} · orders go out`
      : paperLock ? `${who} · loss lock on — click UNLOCK`
      : t.can_trade ? `${who} · ← click ARM to trade`
      : `${who} · CAN'T ARM: ` + String(t.why_not || "no account connected").replace(/^LOCKED for today: /, "locked: ");
    if (why.textContent !== txt) why.textContent = txt;
    why.className = t.armed ? "ok" : (!t.can_trade && !paperLock) ? "bad" : "go"; }
  const sd = curData(), sb = document.getElementById("sideBtn"), side = sd && sd.play && sd.play.side;
  sb.textContent = side === "short" ? "S" : "L"; sb.className = side === "short" ? "short" : "long"; sb.disabled = !side; sb.title = side ? `${curSym} is a ${side.toUpperCase()} — click for ${side === "short" ? "LONG" : "SHORT"} (your levels stay)` : "no ticker on screen";
  document.getElementById("oneclick").checked = !!t.one_click; document.getElementById("bracket").checked = !!t.bracket; document.getElementById("scale").checked = !!t.scale;
  { const sp = s.speech || {}, vb = document.getElementById("voiceBtn");
    const who = sp.engine === "cloud" ? (sp.ok === false ? " · ELEVENLABS ✗" : " · ELEVENLABS") : "";
    vb.textContent = (store.get("voice", true) ? "VOICE ON" : "VOICE OFF") + who;
    vb.classList.toggle("vfail", sp.engine === "cloud" && sp.ok === false);
    vb.title = sp.engine === "cloud" ? (sp.ok === false ? "ElevenLabs did not answer the last call, so the browser voice said it: " + (sp.error || "") + " (SETTINGS > Voice > TEST VOICE)"
                                                        : "Your ElevenLabs voice says the calls" + (sp.ok ? " (last call: OK)" : ""))
             : sp.wanted === "cloud" ? "Browser voice: the cloud voice needs its API key and voice ID (SETTINGS > Voice)" : "Browser voice (SETTINGS > Voice to use ElevenLabs)"; }
  document.getElementById("soundBtn").textContent = store.get("sound", true) ? "BEEP ON" : "BEEP OFF";
  const rot = document.getElementById("rotate"); rot.textContent = "ROTATE " + (s.auto_rotate ? "ON" : "OFF");
  const rec = document.getElementById("recBtn"); rec.className = s.desk && s.desk.recording ? "on" : ""; rec.textContent = s.desk && s.desk.recording ? "STOP REC" : "REC";
  const rp = s.replay, rb = document.getElementById("replaybar"); rb.classList.toggle("on", !!rp);
  if (rp){ document.getElementById("rpFile").textContent = rp.file || ""; document.getElementById("rpPlay").textContent = rp.done ? "FINISHED" : rp.paused ? "PLAY" : "PAUSE";
    if (document.activeElement !== document.getElementById("rpSpeed")) document.getElementById("rpSpeed").value = rp.speed || 5; document.getElementById("rpSpeedV").textContent = (rp.speed || 5) + "×"; document.getElementById("rpPos").textContent = rp.position ? nyT(rp.position) + (rp.end ? " / " + nyT(rp.end) : "") : "";
    const sc = document.getElementById("rpScrub");
    if (rp.start && rp.end && !scrubbing){ sc.min = Math.floor(rp.start); sc.max = Math.ceil(rp.end); if (rp.position) sc.value = Math.round(rp.position); }
    if (rp.clip_done && !window._clipToast){ window._clipToast = true; toast("End of the clip — paused. Press space to keep going.", true); } }
}

/* ---------- the frame: one snapshot in, each panel decides if it changes */
let focusAsked = 0;
/* STREAMING: the ticker on screen is pushed by TED the moment its LEVEL II, T&S or quote changes (Server-Sent
   Events), drawn on the next frame. The regular refresh still carries everything else; whichever is newer wins */
const STREAM = {es: null, sym: null, last: null, pend: false, chartT: 0, n: 0, t: 0};
function streamTo(sym){
  if (STREAM.sym === sym && STREAM.es && STREAM.es.readyState !== 2) return;
  if (STREAM.es) STREAM.es.close();
  STREAM.es = null; STREAM.sym = sym; STREAM.last = null;
  if (!sym || typeof EventSource === "undefined") return;
  const es = new EventSource("/api/stream?sym=" + encodeURIComponent(sym));
  STREAM.es = es;
  es.onmessage = e => {
    let m; try { m = JSON.parse(e.data); } catch (x){ return; }
    if (m.symbol !== curSym) return;
    STREAM.last = m; STREAM.n++; STREAM.t = Date.now();
    if (!STREAM.pend){ STREAM.pend = true; requestAnimationFrame(streamDraw); }
  };
}
// put the newest pushed book / prints / quote / candle onto the pane (only if newer than what it already has)
function streamApply(d, m){
  if (!d || !m || d.symbol !== m.symbol || (d.sv != null && m.sv <= d.sv)) return false;
  d.last = m.last; d.bid = m.bid; d.ask = m.ask; d.spread = m.spread; d.ladder = m.ladder; d.sv = m.sv;
  if (d.tape) d.tape.recent = m.recent;
  const c = BARS[m.symbol], b = m.bar;
  if (b && c && c.bars){
    const k = c.bars.length - 1;
    if (k >= 0 && c.bars[k][0] === b[0]) c.bars[k] = b; else if (k < 0 || b[0] > c.bars[k][0]) c.bars.push(b);
    if (d.bars !== c.bars) d.bars = c.bars;
  }
  return true;
}
function streamDraw(){
  STREAM.pend = false;
  const d = curData();
  if (!streamApply(d, STREAM.last)) return;
  try {
    renderQuote(d); renderBook(d); renderTape(d); renderFast(d);
    const now = performance.now();
    if (now - STREAM.chartT > 120){ STREAM.chartT = now; drawChart(charts.chart); }     // the candle: ~8 a second is plenty
  } catch (e){ console.error("TED stream draw", e); }
}
function render(s){
  state = s;
  // the ticker on screen owns a ladder: after a TED restart (or any drift) claim it again
  if (curSym && s.focus !== curSym && (s.symbols || []).includes(curSym) && Date.now() - focusAsked > 3000){ focusAsked = Date.now(); post("/api/play", {symbol: curSym, action: "focus"}); }
  if (!TABS.list.length && s.symbols && s.symbols.length){ TABS.list = (PREFS.tabs || []).filter(x => s.symbols.includes(x)); if (!TABS.list.length) TABS.list = [s.focus || s.symbols[0]]; TABS.active = (PREFS.active && TABS.list.includes(PREFS.active)) ? PREFS.active : TABS.list[0]; curSym = TABS.active; renderTabs(); }
  const d = dataFor(s, curSym);
  // the top chart switched to another stock: the option chart (and its Level II / T&S, ORDER ENTRY) goes blank
  // instead of showing a contract on a different stock
  if (curSym && OCH.key && OCH.key.split(" ")[0] !== curSym){ unloadContract(true); OCH.dismissed = null; }
  if (curSym !== OCH.symSeen){ OCH.symSeen = curSym; OCH.dismissed = null; }
  // back on a stock you are in a contract on (or whose lines trade one): it comes back on the option chart
  if (curSym && !OCH.key){ const c = contractFor(curSym, s); if (c && c.key !== OCH.dismissed) loadContract(c); }
  streamTo(curSym);
  if (d && STREAM.last) streamApply(d, STREAM.last);       // a pushed update newer than this refresh stays on screen
  for (const c of Object.values(charts)){
    if (c.sym !== curSym){ if (c.sym) VIEWS[c.sym] = VIEWS[c.sym] || {}, VIEWS[c.sym][c.id] = Object.assign({}, c.view); c.sym = curSym; Object.assign(c.view, viewFor(curSym || "_", c.id), {cross: null, rightT: null}); }
    c.data = d;
  }
  focusedPane = charts.chart;
  renderStatus(s);
  renderQuote(d);
  charts.chart.el.classList.toggle("clean", store.get("clean", true));
  drawChart(charts.chart); drawChart(charts.foot); drawChart(charts.chart2); drawChart(charts.chart3); renderFast(d);
  renderBook(d); renderTape(d); renderSetup(d); renderPS60(d); renderReloads(d); renderConviction(d); renderStory(d); renderScore(s);
  renderTicket(s, d);
  renderWatch(s); renderCalls(s); renderPositions(s); renderOrders(s);
  renderDesk(s); renderTrades(s); renderFlow(s); renderFlowScope(s); renderEquity(s); renderMyAlerts(s); renderUrgency(s); renderBigMoney(curData());
  const msgs = s.messages.map(m => `<div class="msg-${esc(m.level)} mono" style="font-size:11px">${ago(s.now - m.t)} · ${m.category ? `<span class="cat cat-${esc(m.category.replace(/\s+/g, "-").toLowerCase())}">${esc(m.category)}</span> ` : ""}${esc(m.text)}${m.n > 1 ? ` <span class="dim">×${m.n}</span>` : ""}</div>`).join("") || `<span class="dim">—</span>`;
  const me = document.getElementById("messages"); if (me.dataset.h !== msgs){ me.dataset.h = msgs; me.innerHTML = msgs; }
  for (const a of s.alerts.slice(0, 10)){ const key = a.t + a.symbol + a.label; if (!seenAlerts.has(key)){ seenAlerts.add(key); if (!firstFeed && store.get("alerts", true) && store.get("sound", true) && a.symbol === TABS.active) beep(sayClass(a)); } }
  firstFeed = false;
  speakNew(s);
}
let timer = null, lastGood = Date.now();
// how long a full cycle takes on THIS machine: the answer from TED, and the time the page needs to draw it. The poll
// paces itself on it (never piles requests up), and the greying only happens when a real answer is overdue
const CYCLE = {fetch: 0, draw: 0, bytes: 0, interval: 250, lostAfter: 6000};
const JOURNAL = {ver: null, trades: []};
const cycleWords = () => `last answer ${CYCLE.fetch} ms (${Math.round(CYCLE.bytes / 1024)} KB), drawn in ${CYCLE.draw} ms, polling every ${CYCLE.interval} ms` +
  (STREAM.es && STREAM.es.readyState === 1 ? ` · LIVE STREAM on ${STREAM.sym}: ${STREAM.n} pushes, last ${STREAM.t ? Math.max(0, Date.now() - STREAM.t) + " ms ago" : "—"}` : " · live stream off");
function markLost(){
  const lost = Date.now() - lastGood > CYCLE.lostAfter;
  document.body.classList.toggle("stale", lost);
  if (lost) for (const id of ["ledMkt", "ledOpt"]){ const el = document.getElementById(id); if (el){ el.className = "ld red"; el.title = "No answer from TED for " + Math.round((Date.now() - lastGood) / 1000) + " s — prices on screen are NOT live · " + cycleWords(); } }
  return lost;
}
setInterval(markLost, 1000);
const BARS = {};   // symbol -> {bars, daily, ver}: the page's own copy of the history
const HVER = {};   // symbol -> the history version the engine last reported
async function poll(now){
  clearTimeout(timer);
  try {
    const extra = [...new Set(TABS.list.concat(curSym ? [curSym] : []))].join(",");
    // history is fetched once per symbol and kept here; every poll after that carries only the last bars
    // fetch it again whenever the engine's history for that symbol has changed (IBKR history lands after startup)
    const need = [...new Set(TABS.list.concat(curSym ? [curSym] : []).concat((state && state.symbols) || []))].filter(s => !BARS[s] || (HVER[s] != null && BARS[s].ver !== HVER[s]));
    const ac = new AbortController(), to = setTimeout(() => ac.abort(), 15000);   // a hung request never freezes the desk; a slow one is still an answer
    const t0 = performance.now();
    const r = await fetch("/api/state?extra=" + encodeURIComponent(extra) + "&full=" + encodeURIComponent(need.join(",")) + (JOURNAL.ver != null ? "&tv=" + JOURNAL.ver : ""), {cache: "no-store", signal: ac.signal});
    clearTimeout(to);
    const txt = await r.text(); CYCLE.bytes = txt.length; const s = JSON.parse(txt);
    // the trade journal only comes when it changed: keep the last one
    if (s.desk){ if (s.desk.trades == null) s.desk.trades = JOURNAL.trades; else { JOURNAL.trades = s.desk.trades; JOURNAL.ver = s.desk.trades_ver; } }
    CYCLE.fetch = Math.round(performance.now() - t0);
    for (const d of (s.panes || []).concat(Object.values(s.extra || {}))){
      if (!d) continue;
      const c = BARS[d.symbol];
      HVER[d.symbol] = d.hist_ver;
      if (d.bars_full){ BARS[d.symbol] = {bars: d.bars || [], daily: d.daily || [], m5: d.m5 || [], m30: d.m30 || [], ver: d.hist_ver}; continue; }
      if (!c){ d.daily = []; continue; }   // only the live tail came: show it, never keep it as the history
      // the tail must join onto what we hold (no missing minutes); if not, fetch the full history next poll
      const tb = (d.bars || [])[0], lastC = c.bars.length ? c.bars[c.bars.length - 1][0] : null;
      if (tb && lastC != null && tb[0] > lastC + 60){ c.ver = -1; d.bars = c.bars.concat(d.bars); d.daily = c.daily; d.m5 = c.m5; d.m30 = c.m30; continue; }
      // merge the tail: replace bars we have by timestamp, append new ones
      for (const b of d.bars || []){ const i = c.bars.findIndex(x => x[0] >= b[0]); if (i < 0) c.bars.push(b); else if (c.bars[i][0] === b[0]) c.bars[i] = b; else c.bars.splice(i, 0, b); }
      if (c.bars.length > 2600) c.bars.splice(0, c.bars.length - 2600);
      d.bars = c.bars; d.daily = c.daily; d.m5 = c.m5; d.m30 = c.m30;
    }
    const t1 = performance.now();
    render(s);
    CYCLE.draw = Math.round(performance.now() - t1);
    lastGood = Date.now();
    const sb = document.getElementById("stCycle"); if (sb){ const w = `${CYCLE.fetch + CYCLE.draw} ms`; if (sb.textContent !== w){ sb.textContent = w; sb.title = cycleWords(); } sb.className = CYCLE.fetch + CYCLE.draw > 1500 ? "bad" : CYCLE.fetch + CYCLE.draw > 600 ? "warn" : ""; }
  } catch (e){
    if (e && e.name !== "AbortError" && !(e instanceof TypeError && /fetch|network/i.test(String(e.message)))){
      // the answer came, the DRAW failed: that is a page bug, not a lost connection — say so and keep going
      console.error("TED draw error", e); lastGood = Date.now();
      const el = document.getElementById("stCycle"); if (el){ el.textContent = "DRAW ERROR: " + String(e.message).slice(0, 80); el.className = "bad"; el.title = String(e.stack || e); }
    } else { document.querySelector("#stConn b").textContent = "DASHBOARD LOST CONTACT WITH TED"; document.querySelector("#stConn .led").className = "led bad"; }
  }
  // pace on this machine: 4 a second when it keeps up, slower when a cycle takes longer, never two requests at once
  CYCLE.interval = Math.min(3000, Math.max(250, Math.round(1.5 * (CYCLE.fetch + CYCLE.draw))));
  CYCLE.lostAfter = Math.max(6000, 4 * CYCLE.interval);
  markLost();
  timer = setTimeout(poll, document.hidden ? Math.max(1000, CYCLE.interval) : CYCLE.interval);
}


/* ---------- replay: rewind / fast-forward / scrub / clip IN-OUT ---------- */
let scrubbing = false;
const CLIPSEL = {t0: null, t1: null};
function rpSeek(t){ const rp = state && state.replay; if (!rp) return; if (rp.start) t = Math.max(rp.start, t); if (rp.end) t = Math.min(rp.end, t); post("/api/replay", {seek: t}); }
document.getElementById("replaybar").addEventListener("click", e => {
  const j = e.target.closest("button[data-jump]"); const rp = state && state.replay;
  if (j && rp && rp.position){ rpSeek(rp.position + +j.dataset.jump); return; }
  if (e.target.id === "rpIn" && rp && rp.position){ CLIPSEL.t0 = rp.position; showInOut(); }
  if (e.target.id === "rpOut" && rp && rp.position){ CLIPSEL.t1 = rp.position; showInOut(); }
  if (e.target.id === "rpSaveClip") saveReplayClip();
  if (e.target.id === "rpStep") post("/api/replay", {step: true});
  if (e.target.id === "rpRestart") post("/api/replay", {restart: true});
});
function showInOut(){ document.getElementById("rpInOut").textContent = (CLIPSEL.t0 ? nyT(CLIPSEL.t0) : "—") + " → " + (CLIPSEL.t1 ? nyT(CLIPSEL.t1) : "—"); }
async function saveReplayClip(){
  if (!CLIPSEL.t0 || !CLIPSEL.t1){ toast("Set IN and OUT first", false); return; }
  const note = prompt("Note for this clip (what to look at):", "") ?? "";
  const out = await post("/api/clips/add", {t0: CLIPSEL.t0, t1: CLIPSEL.t1, symbol: curSym, note});
  toast(out.ok ? `Clip saved to the journal (${fmtDur(Math.abs(CLIPSEL.t1 - CLIPSEL.t0))})` : "Clip not saved: " + (out.reason || ""), out.ok);
  if (out.ok){ CLIPSEL.t0 = CLIPSEL.t1 = null; showInOut(); clipListT = 0; }
}
{ const sc = document.getElementById("rpScrub");
  sc.addEventListener("input", () => { scrubbing = true; document.getElementById("rpPos").textContent = nyT(+sc.value); });
  sc.addEventListener("change", () => { scrubbing = false; rpSeek(+sc.value); }); }
// Shift+← / Shift+→ = 30 s back / forward (plain arrows still change the speed); runs before the other key handlers
document.addEventListener("keydown", e => {
  if (!(state && state.replay) || !e.shiftKey || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test((document.activeElement || {}).tagName || "")) return;
  e.preventDefault(); e.stopImmediatePropagation();
  const rp = state.replay; if (rp.position) rpSeek(rp.position + (e.key === "ArrowRight" ? 30 : -30));
}, true);

/* ---------- live: CLIP the last minutes of the recording ---------- */
document.getElementById("clipBtn").addEventListener("click", async () => {
  if (!(state && state.desk && state.desk.recording)){ toast("Start a recording first (REC) — a clip is a piece of a recording", false); return; }
  const secs = +document.getElementById("clipLen").value || 120;
  const note = prompt(`Clip the last ${fmtDur(secs)} — a note (what to look at):`, "") ?? "";
  const out = await post("/api/clips/add", {seconds: secs, symbol: curSym, note});
  toast(out.ok ? `Clip saved to the journal: last ${fmtDur(secs)}` : "Clip not saved: " + (out.reason || ""), out.ok);
  clipListT = 0;
});

/* ---------- clips in the journal: watch / remove ---------- */
document.addEventListener("click", async e => {
  const pl = e.target.closest("button[data-clip-play]"), dl = e.target.closest("button[data-clip-del]");
  if (!pl && !dl) return;
  const c = (clipList || []).find(x => x.id === (pl || dl).dataset[pl ? "clipPlay" : "clipDel"]); if (!c) return;
  if (dl){ if (!confirm("Remove this clip from the journal? (The recording stays.)")) return; const out = await post("/api/clips/delete", {id: c.id}); toast(out.ok ? "Clip removed" : "Could not remove", out.ok); clipListT = 0; return; }
  if (state && state.replay){
    if (state.replay.file !== c.rec){ toast("This replay desk is on another recording — open the clip from the main desk", false); return; }
    window._clipToast = false; await post("/api/replay", {seek: c.t0, pause_at: c.t1, paused: false}); toast("Watching the clip " + nyT(c.t0) + " → " + nyT(c.t1), true); return;
  }
  const out = await post("/api/desk/replay", {name: c.rec, speed: 1, start: c.t0, end: c.t1});
  if (out.ok){ toast("Opening the clip in the replay desk…", true); setTimeout(() => window.open(out.url, "_blank"), 2500); } else toast(out.reason || "Could not open", false);
});

/* ---------- ★ good sessions ---------- */
document.addEventListener("click", async e => {
  const f = e.target.closest("button[data-flag]"); if (!f) return;
  const out = await post("/api/desk/flag", {name: f.dataset.flag, on: f.dataset.on === "1"});
  if (out.ok){ const r = (deskList || []).find(x => x.name === f.dataset.flag); if (r) r.flag = f.dataset.on === "1"; renderDesk(state); toast(f.dataset.on === "1" ? "★ Flagged as a good session" : "Flag removed", true); }
});
document.addEventListener("change", e => { if (e.target.id === "recFlagOnly"){ store.set("recFlagOnly", e.target.checked); renderDesk(state); } });

/* ---------- voice markers: hear them; journal voice notes jump the replay ---------- */
document.addEventListener("click", e => {
  const a = e.target.closest("button[data-audio]"); if (a){ e.stopPropagation(); new Audio(a.dataset.audio).play().catch(() => toast("Could not play the audio", false)); return; }
  const jn = e.target.closest(".jn[data-jt]"); if (jn && state && state.replay){ rpSeek(+jn.dataset.jt); toast("Jumping to " + nyT(+jn.dataset.jt), true); }
}, true);

/* ---------- MIC: talk during a recording; the words become the journal entry ---------- */
const MIC = {on: false, n: null, t0: 0, text: "", interim: "", rec: null, media: null, chunks: [], stream: null};
function micUI(){
  const b = document.getElementById("micBtn"); if (!b) return;
  b.disabled = !!(state && state.replay);
  b.title = state && state.desk && state.desk.recording ? "Voice note: it lands in the trade log and on the recording as a marker" : "Voice note: what you say lands in the symbol's trade log (start REC to put it on a recording too)";
  b.className = MIC.on ? "on mic" : "";
  b.textContent = MIC.on ? "● MIC " + fmtDur(Date.now() / 1000 - MIC.t0) : "MIC";
  let live = document.getElementById("micLive");
  if (MIC.on){
    if (!live){ live = document.createElement("div"); live.id = "micLive"; document.body.appendChild(live); }
    live.innerHTML = `<b>🎙 LISTENING — press MIC again to save</b><span>${esc((MIC.text + " " + MIC.interim).trim()) || "<i>say what you see…</i>"}</span>`;
  } else if (live) live.remove();
}
setInterval(micUI, 500);
async function micStart(){
  if (state && state.replay){ toast("No voice notes during a replay", false); return; }
  const out = await post("/api/desk/mic_start", {symbol: curSym});
  if (!out.ok){ toast(out.reason || "Mic not available", false); return; }
  Object.assign(MIC, {on: true, n: out.mark.n, t0: Date.now() / 1000, text: "", interim: "", chunks: []});
  toast((out.mark.n > 0 ? "🎙 Marked at " + nyT(out.mark.t) : "🎙 " + (curSym || "") + " trade log") + " — talking…", true);
  try {                                     // the audio itself, kept with the marker
    MIC.stream = await navigator.mediaDevices.getUserMedia({audio: true});
    MIC.media = new MediaRecorder(MIC.stream);
    MIC.media.ondataavailable = ev => { if (ev.data && ev.data.size) MIC.chunks.push(ev.data); };
    MIC.media.start(1000);
  } catch (err){ MIC.media = null; toast("No microphone access — allow the mic for this page (the marker is still saved)", false); }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;   // the words (Chrome / Edge)
  if (SR){
    const r = MIC.rec = new SR(); r.lang = "en-US"; r.continuous = true; r.interimResults = true;
    r.onresult = ev => { let interim = ""; for (let i = ev.resultIndex; i < ev.results.length; i++){ const t = ev.results[i][0].transcript; if (ev.results[i].isFinal) MIC.text += (MIC.text ? " " : "") + t.trim(); else interim += t; } MIC.interim = interim; };
    r.onend = () => { if (MIC.on) try { r.start(); } catch (e) {} };   // keeps listening through pauses
    try { r.start(); } catch (e) {}
  } else toast("This browser can't transcribe — the audio is saved; use Chrome or Edge for words", false);
  micUI();
}
async function micStop(){
  if (!MIC.on) return;
  MIC.on = false;
  const rec = MIC.rec; MIC.rec = null; if (rec) try { rec.stop(); } catch (e) {}
  await new Promise(res => setTimeout(res, 600));              // the last words arrive after stop
  const text = (MIC.text + " " + MIC.interim).trim(), n = MIC.n;
  const out = await post("/api/desk/mic_text", {n, text});
  toast(out.ok ? "🎙 Journal entry saved: " + (text ? text.slice(0, 80) + (text.length > 80 ? "…" : "") : "(no words picked up — audio kept)") : "Voice note not saved: " + (out.reason || ""), out.ok);
  const media = MIC.media; MIC.media = null;
  if (media && media.state !== "inactive"){
    await new Promise(res => { media.onstop = res; media.stop(); });
    if (MIC.stream) MIC.stream.getTracks().forEach(t => t.stop());
    const type = (media.mimeType || "audio/webm").split(";")[0];
    const blob = new Blob(MIC.chunks, {type});
    if (blob.size) fetch("/api/desk/mic_audio?n=" + n, {method: "POST", headers: {"Content-Type": type}, body: blob}).catch(() => {});
  }
  micUI(); poll(true);
}
document.getElementById("micBtn").addEventListener("click", () => MIC.on ? micStop() : micStart());

/* HOW TO READ IT: the ladder in plain words, the way a prop desk teaches a new trader */
document.addEventListener("click", e => {
  if (!e.target.dataset || !e.target.dataset.howto) return;
  let m = document.getElementById("howtoPop"); if (m){ m.remove(); return; }
  m = document.createElement("div"); m.id = "howtoPop"; m.className = "pop howto-pop";
  m.innerHTML = `<div class="cs-hd"><b>READING LEVEL II</b><button data-howclose="1">✕</button></div>
  <p><b>Left is buyers, right is sellers.</b> Each row is one price. The middle column is the price.</p>
  <p><b>BID</b> = shares waiting to BUY at that price right now. <b>ASK</b> = shares waiting to SELL. That is only what they CHOOSE to show you.</p>
  <p><b>HIT</b> = shares that actually traded into the bid there (sellers dumping on buyers). <b>PAID</b> = shares that traded at the ask (buyers paying up). These are real trades, not promises.</p>
  <p><b>The one thing to learn:</b> compare what traded with what was showing. If 12,000 shares traded at 10.88 but the ask never showed more than 300, somebody is hiding a big order there and keeps putting 300 back. That is a <b class="sell">RELOAD SELLER</b>. Mirror image on the bid: a <b class="buy">RELOAD BUYER</b>.</p>
  <p>A reloader's row lights up. The HIT / PAID cell switches to the <b>money</b> that traded into him ($135K). <b>R3</b> = he refilled 3 times. Hover any cell for the full sentence.</p>
  <p><b>What it means for you:</b> a reload seller above you is a wall; price has trouble going higher until he is <b>CLEANED UP</b> (C: price trades through and he is gone). A reload buyer under you is a floor. <b>PULLED</b> (P) = the size left without trading: it was never real.</p>
  <p><b>CALLS</b> (left) and <b>PUTS</b> (right) = option money that hit while the stock was at that price. ⚡ = short-dated out-of-the-money contracts being hammered: somebody may know something.</p>
  <p>The rows stay still while price moves; the gold row is the last price. Click a BID size to buy there, an ASK size to sell there.</p>`;
  document.body.appendChild(m);
  const r = e.target.getBoundingClientRect();
  m.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 420)) + "px"; m.style.top = Math.max(8, Math.min(r.top - m.offsetHeight - 6, window.innerHeight - m.offsetHeight - 8)) + "px";
  m.addEventListener("click", ev => { if (ev.target.dataset.howclose) m.remove(); });
});

/* BIG MONEY 30D: every big option print on this symbol for 30 days, judged on facts: premium paid, breakeven,
   where the stock is now (or closed on expiry day). Green = the side that paid is winning, red = losing */
function renderBigMoney(d){
  const list = document.getElementById("bmList"), hd = document.getElementById("bmSym"); if (!list) return;
  if (hd && hd.textContent !== ((d && d.symbol) || "")) hd.textContent = (d && d.symbol) || "";
  const items = (d && d.bigmoney) || [];
  const ago_ = a => a < 1 ? "today" : Math.round(a) + "d ago";
  const html = items.length ? items.map(x => {
    const cls = x.status === "EXPIRED WORTHLESS" ? (x.who === "BUYERS" ? "bad" : "good") : x.good == null ? "" : x.good ? "good" : "bad";
    const t = `${x.size.toLocaleString("en-US")} contracts ${x.symbol} ${flowStrike(x.strike)}${x.cp} ${x.expiry} @ ${(+x.price).toFixed(2)} = ${usdK(x.premium)} ${x.side === "bid" ? "SOLD at the bid" : "BOUGHT at the ask"} ${ago_(x.age_days)}` +
      (x.spot_then ? `, stock was ${(+x.spot_then).toFixed(2)}` : "") + `. Breakeven ${x.breakeven}. ` + (x.value != null ? `Worth at least ${usdK(x.value)} on the stock now (intrinsic; time value not counted).` : "");
    return `<div class="bm ${cls}" title="${esc(t)}"><span class="amt">${usdK(x.premium)}</span><span class="ct ${x.cp === "C" ? "c" : "p"}">${flowStrike(x.strike)}${x.cp} ${esc((x.expiry || "").slice(5))}</span><span class="ag">${ago_(x.age_days)}</span><span class="st">${esc(x.status)}</span><span class="tx">${esc(x.text)}</span></div>`;
  }).join("") : `<div class="dim" style="padding:8px">No option print of ${usdK((state && state.flow_big_min) || 500000)} or more on this symbol in the last 30 days.</div>`;
  if (list.dataset.h !== html){ list.dataset.h = html; list.innerHTML = html; }
}

/* CONVICTION BOARD: Dan's option-flow timing (the source-of-truth spec). Two gates, eight lanes, 0-100, a traffic light.
   READY TO GO only when the chart gate AND the flow gate are green; one alone is ARMED — WAITING OTHER GATE. */
// the name under each dot, so the row reads without hovering (click it for the whole CONVICTION panel)
const LANE_SHORT = {L0_DAILY_MP: "MP", L1_PIVOT: "PIVOT", L2_CONFIRM: "CONFIRM", L3_SECOND_ENTRY: "2ND", L4_BUILD: "BUILD", L5_FLOW_SIDE: "FLOW", L6_FLOW_QUALITY: "QUALITY", L7_CORRELATION: "CORR"};
const LANE_NAMES = {L0_DAILY_MP: "DAILY MP", L1_PIVOT: "PIVOT", L2_CONFIRM: "CONFIRM", L3_SECOND_ENTRY: "2ND ENTRY", L4_BUILD: "BUILD", L5_FLOW_SIDE: "FLOW SIDE", L6_FLOW_QUALITY: "FLOW QUALITY", L7_CORRELATION: "CORRELATION"};
function renderScore(st){
  if (!P.score) return;
  const s = st && st.score;
  if (!s){ panelHTML("score", `<div class="dim" style="padding:8px">${st ? "THE DESK SCORE is off (SETTINGS > Desk score)." : NA}</div>`); return; }
  const tm = t => typeof nyHM12 === "function" ? nyHM12(t) : new Date(t * 1000).toLocaleTimeString();
  const pc = v => v == null ? "" : `${v}%`;
  const mv = v => v == null ? "" : `${v >= 0 ? "+" : ""}${(+v).toFixed(2)}`;
  const kinds = (s.kinds || []).map(k => `<div class="scrow"><span>${esc(k.kind)}</span><i>${k.n}</i>
      <b class="${k.hit_pct == null ? "" : k.hit_pct >= 60 ? "good" : k.hit_pct <= 35 ? "bad" : ""}">${pc(k.hit_pct)}</b>
      <em title="hits / misses / flat">${k.hit}·${k.miss}·${k.flat}</em><u title="average move at 5 and 15 min, in ATRs">${mv(k.avg5)} / ${mv(k.avg15)} ATR</u></div>`).join("");
  const recent = (s.recent || []).map(r => `<div class="screc ${r.outcome === "HIT" ? "good" : r.outcome === "MISS" ? "bad" : ""}" title="${esc(r.text || "")}">
      <span>${tm(r.t)}</span><b>${esc(r.symbol || "")}</b><i>${esc(r.kind)} ${r.dir > 0 ? "▲" : "▼"}</i><em>${r.outcome || ""}</em><u>${r.pct15 == null ? "" : (r.pct15 >= 0 ? "+" : "") + r.pct15 + "%"}</u></div>`).join("");
  const html = `<div class="sth">BY CALL · count · hit rate · hit·miss·flat · avg move 5 / 15 min (ATRs)</div>
    <div class="sctab">${kinds || `<div class="dim" style="padding:4px 8px">no call has had its 15 minutes yet${s.open ? ` · ${s.open} waiting` : ""}</div>`}</div>
    <div class="sth">THE LAST CALLS · judged 15 minutes after${s.open ? ` · ${s.open} still waiting` : ""}</div>
    <div class="sctab">${recent || `<div class="dim" style="padding:4px 8px">nothing judged yet</div>`}</div>`;
  panelHTML("score", html);
}
function renderConviction(d){
  const strip = document.getElementById("cvStrip"), panel = document.getElementById("cvPanel");
  const c = d && d.conviction;
  const tone = c ? c.board_state.toLowerCase() : "none";
  if (strip){
    const dot = l => `<i class="tl ${l.toLowerCase()}"></i>`;
    const h = !c ? "" : `<span class="cvv">${esc(c.label)}</span><span class="cvs">${c.score}</span><span class="gates"><b class="${c.chart_gate.ok ? "on" : ""}">CHART ${c.chart_gate.ok ? "✓" : "✗"}</b><b class="${c.flow_gate.ok ? "on" : ""}">FLOW ${c.flow_gate.ok ? "✓" : "✗"}</b></span><span class="lanes">${c.lanes.map(l => `<span class="lane" title="${esc(LANE_NAMES[l.id] + ": " + l.text)}">${dot(l.light)}<em>${LANE_SHORT[l.id] || ""}</em></span>`).join("")}</span><span class="cvmore">▸ DETAILS</span>${c.max_pain && c.max_pain.options ? `<span class="dim">5m stop ${px(c.max_pain.options)}</span>` : ""}`;
    if (strip.dataset.h !== h){ strip.dataset.h = h; strip.innerHTML = h; strip.className = "cvstrip " + tone; }
  }
  if (!panel) return;
  if (!c){ panelHTML("conviction", `<div class="dim" style="padding:8px">${NA}</div>`); return; }
  const rows = c.lanes.map(l => `<div class="cvr ${l.light.toLowerCase()}"><span class="n"><i class="tl ${l.light.toLowerCase()}"></i>${esc(LANE_NAMES[l.id])}</span><span class="t">${esc(l.text)}</span></div>`).join("");
  const html = `<div class="cvhead ${tone}"><div class="v">${esc(c.label)}</div>
    <div class="s">${c.score} <span class="dim">/ 100 · ${esc(c.side_bias.toLowerCase())}${c.reasons && c.reasons.length ? " · " + esc(c.reasons.join(", ")) : ""}</span></div>
    <div class="gates big"><b class="${c.chart_gate.ok ? "on" : ""}">CHART GATE ${c.chart_gate.ok ? "GREEN" : "not yet"}</b><b class="${c.flow_gate.ok ? "on" : ""}">FLOW GATE ${c.flow_gate.ok ? "GREEN" : "not yet"}</b></div>
    ${c.max_pain ? `<div class="dim" style="font-size:10.5px;margin-top:3px">Max pain: prior 5m ${c.side_bias === "LONG" ? "low" : "high"} ${px(c.max_pain.options)} (options) · process stop ${px(c.max_pain.equity)} (equity)</div>` : ""}</div>
    <div class="cvrows">${rows}</div>
    <div class="dim" style="padding:4px 8px;font-size:10.5px">Daily MP 20 · pivot + confirm 20 · 2nd entry 20 · premium ≥ $100K 10 · weeklies 10 · out of the money 10 · repeats 10 · sweeps +5. Flow supports the pivot; it never replaces the second entry.</div>`;
  panelHTML("conviction", html);
}

/* ---------- OPTION CHART: the contract itself (its mid, minute by minute) and you trade it right there.
   Pick a contract in the OPTION CHAIN (or 📈 on a row); right-click the chart = BUY / SELL that contract at that
   price; drag your working order line to move it; BUY / SELL now in the header fill at the touch. */
const OCH = {key: null, data: null, busy: false, n: 1};
const ochart = (() => { const p = P.ochart; if (!p) return null;
  const c = {id: "ochart", type: "chart", el: p.el, isFoot: false, data: null, canvas: p.el.querySelector("canvas"), opt: true,
             view: {cw: 8, offset: restOffset(), yLo: null, yHi: null, follow: true, cross: null}};
  p.el._pane = c; wireChart(c, c.canvas, c.view, () => {}, false);
  new ResizeObserver(() => drawChart(c)).observe(p.el); return c; })();
function ochVisible(){ return ["ochart", "obook", "otape", "obig"].some(id => P[id] && P[id].el.offsetParent !== null) || ((contractMode("book") && P.book.el.offsetParent !== null) || (contractMode("tape") && P.tape.el.offsetParent !== null)); }
/* take the loaded contract off the OPTION CHART (its Level II / T&S and ORDER ENTRY follow). Nothing is sold or
   cancelled: a contract you hold stays in POSITIONS, its stop and lines stay on */
/* the contract that belongs on the option chart for a stock when you come back to it (or open the desk): one you are IN.
   Several: the one the stock chart's lines trade, else the one traded last. Not in one = blank */
function contractFor(sym, s){
  if (!sym || !s) return null;
  const d = dataFor(s, sym), pl = d && d.play;
  const held = ((s.account || {}).opt_positions || []).filter(p => p.symbol === sym && p.qty);
  if (!held.length) return null;                            // only a contract you are IN comes back: a saved chart link alone does not (it outlives a restart)
  const linked = pl && pl.trade_as === "option" && pl.opt_key && held.find(p => p.key === pl.opt_key); if (linked) return linked;
  const lastFill = k => Math.max(0, ...((s.account || {}).fills || []).filter(f => f.symbol === k).map(f => f.t || 0));
  return held.slice().sort((a, b) => lastFill(b.key) - lastFill(a.key))[0];
}
function loadContract(p){
  let exp = p.expiry, strike = p.strike, right = p.right;
  if (exp == null){ const m = String(p.key).split(" "); exp = m[1]; strike = parseFloat(m[2]); right = (m[2] || "").slice(-1); }
  OC.link = {sym: String(p.key).split(" ")[0], expiry: exp, strike, right, key: p.key, bid: p.bid, ask: p.ask, n: (OC.link && OC.link.n) || 1};
  P.ticket.last = null; chartOption(p.key, false); renderContractL2(); renderContractTape();
  const bd = P.options && P.options.pc.querySelector(".oc-body"); if (bd) bd.dataset.h = "";
}
function unloadContract(quiet){
  const name = OC.link ? contractName(OC.link) : "contract";
  if (!quiet && OCH.key) OCH.dismissed = OCH.key;          // taken off by hand: it stays off until you come back to the stock
  OC.link = null; OC.sel = null; OCH.key = null; OCH.data = null;
  if (ochart){ ochart.data = null; blankOchart(); }
  renderOchHead(); if (typeof renderOptPanels === "function") renderOptPanels(); renderContractL2(); renderContractTape();
  P.ticket.last = null; poll(true);
  const bd = P.options && P.options.pc.querySelector(".oc-body"); if (bd) bd.dataset.h = ""; renderChain();
  if (!quiet) toast(`${name} taken off the option chart`, true);
}
/* no contract: wipe the picture, not just the data, and say how to load one */
function blankOchart(){ const cv = ochart && ochart.canvas; if (!cv) return; const W = cv.clientWidth, H = cv.clientHeight, dpr = window.devicePixelRatio || 1;
  if (W && H){ cv.width = W * dpr; cv.height = H * dpr; }
  ochart.dataBar = null; const dw = cv.parentElement && cv.parentElement.querySelector(".datawin"); if (dw) dw.style.display = "none";
  const g = cv.getContext("2d"); g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, cv.width, cv.height);
  if (W && H){ g.setTransform(dpr, 0, 0, dpr, 0, 0); g.fillStyle = "#6b7685"; g.font = "13px system-ui, sans-serif"; g.textAlign = "center"; g.fillText("No contract — pick one from the OPTION CHAIN", W / 2, H / 2); } }
/* the stock chart's lines stay on the contract you linked them to: looking at another contract on the OPTION CHART
   never moves them (LINK CHART LINES on the option chart, or OPTION on the order bar, moves them on purpose) */
function chartOption(key, show){ if (!key) return; if (OCH.key !== key){ OCH.key = key; OCH.data = null; if (ochart){ ochart.data = null; blankOchart(); ochart.view.offset = restOffset(); ochart.view.follow = true; ochart.view.yLo = ochart.view.yHi = null; } }
  if (show) showPanel("ochart"); pollOch(); }
async function pollOch(){
  if (OCH.busy || !ochart) return;
  if (!OCH.key && OC.link) OCH.key = OC.link.key;
  if (!OCH.key || !ochVisible()){ renderOchHead(); return; }
  OCH.busy = true;
  try { const r = await fetch(`/api/options/bars?key=${encodeURIComponent(OCH.key)}`); const d = await r.json(); if (d.key !== OCH.key) return;
    OCH.data = d;
    const pos = d.position;
    ochart.data = {symbol: d.label || d.key, bars: d.bars || [], last: d.last, bid: d.bid, ask: d.ask, play: null, user_levels: optUserLevels(d.key), levels: [],
      orders: (d.orders || []).map(o => ({id: o.order_id, price: o.lmt, action: o.action, qty: o.remaining ?? o.qty, role: "entry"})),
      position: pos ? {qty: pos.qty, avg_cost: pos.per_contract} : null, showEntry: true, mult: (pos && pos.mult) || 100, unit: "ct",
      trap: null, daytrap: null, reloaders: null, bigmoney: null, marks: [], events: [], lines: [], daily: [], flow: null, footprint: null};
    drawChart(ochart);
  } catch (e) {} finally { OCH.busy = false; renderOchHead(); renderOptPanels(); }
}
setInterval(pollOch, 1000);
function renderOchHead(){
  const h = document.getElementById("ochHead"); if (!h) return;
  const d = OCH.data, f = v => v == null ? "—" : (+v).toFixed(2), tf = store.get("tf.ochart", 1);
  let html;
  if (!OCH.key) html = `<span class="dim">No contract yet — open OPTIONS, click a strike (or 📈 on its row) and it charts here.</span><button data-och="chain">OPTIONS</button>`;
  else { const pos = d && d.position, q = pos ? Math.abs(pos.qty) : 0, long = pos && pos.qty > 0;
    const rs = d ? optRiskSize(d) : null;
    html = `<b class="${d && d.right === "P" ? "s" : "b"}">${esc(d ? d.label : OCH.key)}</b>${d && d.expires_today ? `<span class="exptoday" title="expires at 4:00 today: a long one in the money is exercised into shares; the desk calls it out at 3:30 and closes it at 3:50 (SETTINGS, Trading)">EXPIRES TODAY</span>` : d && d.dte != null && d.dte < 7 ? `<span class="dim">${d.dte.toFixed(1)}d left</span>` : ""}<span class="dim">bid ${f(d && d.bid)} / ask ${f(d && d.ask)}${d && d.delta != null ? ` · Δ ${(+d.delta).toFixed(2)}` : ""}${d && d.source === "PRACTICE" ? " · practice model" : ""}</span>${d && d.sim ? `<span class="simtag" title="options market closed: this contract's price is SIMULATED from the stock (paper only); option orders wait for the 9:30 open">SIM · market closed</span>` : ""}
      ${rs ? `<button class="risksz" data-ochn="${rs.n}" title="${esc(rs.why)}">RISK $${riskDollars()} → ${rs.n} ct</button>` : d ? `<span class="dim" title="draw a STOP on the stock chart (or set this contract's stop) and the desk sizes contracts from your RISK $">no stop to size from</span>` : ""}
      ${q ? `<span class="${long ? "b" : "s"}">YOU HAVE ${q}${pos.pnl != null ? ` · ${pos.pnl >= 0 ? "+" : "−"}$${sz(Math.abs(Math.round(pos.pnl)))}` : ""}</span>` : ""}
      <span class="tfs">${[1, 5, 15].map(m => `<button data-ochtf="${m}" class="${tf === m ? "on" : ""}">${m}m</button>`).join("")}<button data-ochind="mas" class="${store.get("och.mas", false) ? "on" : ""}" title="moving averages on the OPTION CHART (the stock chart keeps its own)">MAS</button><button data-ochind="bb" class="${store.get("och.bb", false) ? "on" : ""}" title="Bollinger Bands on the OPTION CHART">BB</button></span>
      <span class="cn">${[1, 2, 5, 10].map(n => `<button data-ochn="${n}" class="${OCH.n === n ? "on" : ""}">${n}</button>`).join("")}</span>
      <button class="b big" data-ochnow="BUY">BUY ${OCH.n}</button><button class="s big" data-ochnow="SELL">SELL ${OCH.n}</button>${q ? `${q > 1 ? `<button class="out" data-ochnow="HALF" title="take half off now, at the touch (no confirm)">½ OUT</button>` : ""}<button class="out all" data-ochnow="ALL" title="out of all ${q} now, at the touch (no confirm)">ALL OUT ${q}</button>` : ""}
      ${!d ? "" : (() => { const ol = optLinkFor(d.underlying), on = ol && ol.key === d.key;     // the contract still loading: nothing to link yet
        return on ? `<button class="olink on" data-olink="stock" title="the ${esc(d.underlying)} chart's 2nd entry, STOP and TARGET trade ${ol.qty} of this contract — click to trade the STOCK with them again">◆ ${esc(d.underlying)} CHART LINES TRADE THIS ×${ol.qty}</button>`
          : `<button class="olink" data-olink="option" title="make the ${esc(d.underlying)} chart's 2nd entry, STOP and TARGET trade ${OCH.n} of this contract (instead of shares)">LINK ${esc(d.underlying)} CHART LINES</button>`; })()}
      <span class="dim hint">right-click the chart to trade at a price</span>
      ${q ? (() => { const os = (T().opt_stops || {})[d.key];
        const now = os ? `<span class="ostop ${os.source}">STOP ${os.on === "stock" ? esc(d.underlying) + " " + (pos.qty > 0 === (d.right === "C") ? "under " : "over ") : "contract at "}${(+os.price).toFixed(2)}${os.source === "chart" ? " · your chart STOP line" : ""}${os.fired ? " · FIRED" : ""}</span>` : `<span class="ostop none">NO STOP</span>`;
        return `<span class="ostopbox">${now}<select id="ochStopOn" title="what the stop watches"><option value="stock">on ${esc(d.underlying)}</option><option value="option">on the contract</option></select><input id="ochStopPx" type="number" step="0.01" placeholder="${os ? (+os.price).toFixed(2) : "price"}"><button data-ochstop="set" title="stop out of this contract when the price trades through">SET</button>${os && os.source === "set" ? `<button data-ochstop="off" title="take this stop off (the chart STOP line, if any, still protects)">✕</button>` : ""}</span>`; })() : ""}`; }
  if (h.contains(document.activeElement) && /INPUT|SELECT/.test(document.activeElement.tagName)) return;   // typing a stop
  if (h.dataset.h !== html){ h.dataset.h = html; h.innerHTML = html; }
}
async function ochOrder(action, price, n, now){
  const d = OCH.data; if (!d) return;
  const pos = d.position, q = pos ? Math.abs(pos.qty) : 0, long = pos && pos.qty > 0;
  const closing = q && ((long && action === "SELL") || (!long && action === "BUY"));
  if (!closing && !canTrade()){ toast(whyNot() + (/ARM/i.test(whyNot()) ? "" : " — click ARM"), false); return; }
  const k = closing ? Math.min(n, q) : n;
  const send = async () => {
    const out = closing ? await post("/api/trade/opt_adjust", {key: d.key, contracts: k, mode: "close", price})
      : await post("/api/trade/opt_open", {symbol: d.underlying, expiry: d.expiry, strike: d.strike, right: d.right, action, contracts: k, price});
    toast(out.ok ? "Sent: " + out.sent : "Blocked: " + (out.reason || ""), out.ok); poll(true); pollOch(); };
  { const so = closing ? 0 : shortOpening(d.key, action, k); if (so) return shortOpenConfirm(`${k} ${d.label}${price != null ? " @ " + price.toFixed(2) : " now"}`, so, send); }
  if (T().one_click || (now && closing)) return send();      // getting out never waits on a confirm
  const ref = price != null ? price : (action === "BUY" ? d.ask : d.bid);
  confirmBox(`${action} ${k} ${d.label}${price != null ? " @ " + price.toFixed(2) : " now"}`, `${price != null ? "limit " + price.toFixed(2) + " — rests until price gets there" : (action === "BUY" ? "at the ask" : "at the bid") + ", fills now"} · about $${sz(Math.round((ref || 0) * 100 * k))}${closing ? " · takes your contracts down" : ""}`, action === "BUY" ? "b" : "s", send);
}
/* the lines you drew on the OPTION CHART (2ND, STOP, TARGET at the contract's own price): drawn and dragged like
   the stock chart's lines */
function optUserLevels(key){
  const lv = (T().opt_levels || {})[key] || {}, os = (T().opt_stops || {})[key], out = [];
  if (lv.second_entry) out.push({role: "second_entry", price: lv.second_entry, label: `2ND ${lv.n || 1} ct`});
  const stop = os && os.on === "option" ? +os.price : lv.stop; if (stop) out.push({role: "stop", price: stop, label: "STOP"});
  if (lv.target) out.push({role: "target", price: lv.target, label: "TARGET"});
  return out;
}
function optLevel(role, price, n){
  const d = OCH.data; if (!d) return Promise.resolve({ok: false});
  const names = {second_entry: "2ND", stop: "STOP", target: "TARGET"};
  return post("/api/trade/opt_level", {key: d.key, role, price, n}).then(out => {
    toast(out.ok ? (price == null ? `${d.label}: ${names[role]} off` : `${d.label}: ${names[role]} ${(+price).toFixed(2)}` + (role === "second_entry" ? ` — buys ${n} when it trades there` : role === "target" ? " — out of every contract there" : " — out of every contract there"))
                 : "Not set: " + (out.reason || ""), out.ok);
    poll(true); setTimeout(pollOch, 300); return out; });
}
function optChartMenu(p, x, y, price){
  const old = document.getElementById("cmenu"); if (old) old.remove();
  const d = OCH.data; if (!d) return;
  price = Math.max(0.01, Math.round(price * 100) / 100);
  const pos = d.position, q = pos ? Math.abs(pos.qty) : 0, long = pos && pos.qty > 0, n = OCH.n;
  const m = document.createElement("div"); m.id = "cmenu"; m.className = "pop cmenu";
  m.innerHTML = `<div class="dim" style="font-size:11px;margin-bottom:4px">${esc(d.label)} @ <b style="color:var(--gold)">${price.toFixed(2)}</b><span class="x" title="close">✕</span></div>
    <button class="bbuy" data-do="buy">BUY ${n} limit @ ${price.toFixed(2)}</button>
    <button class="bsell" data-do="sell">SELL ${n} limit @ ${price.toFixed(2)}</button>
    ${q ? `<button class="bflat" data-do="all">${long ? "SELL" : "BUY"} ALL ${q} @ ${price.toFixed(2)}</button>` : ""}
    ${(d.orders || []).length ? `<button data-do="cxl">Cancel my orders on it (${d.orders.length})</button>` : ""}
    <div class="lvl2" title="the same trade lines as the stock chart, on the CONTRACT's price. 2ND buys ${n} when it trades there (more, if you hold it); STOP and TARGET take every contract out there">
      <div><b class="${long || !q ? "b" : "s"}">THIS CONTRACT</b>${[["second_entry", "2ND"], ["stop", "STOP"], ["target", "TARGET"]].map(([r, l]) => `<button data-do="olvl" data-role="${r}" class="blvl ${r === "second_entry" ? "se" : ""}">${l}</button>`).join("")}</div>
      <div class="dim">at ${price.toFixed(2)}${q ? "" : " · STOP and TARGET go live once you hold it"}</div></div>
    ${(() => { const v = p.view, per = v && v.chartY ? (v.chartY[1] - v.chartY[0]) / ((v.chartH || 1) - 8) : 0.02;
      const lv = optUserLevels(d.key).find(l => Math.abs(l.price - price) <= Math.max(per * 6, 0.02));
      return lv ? `<button data-do="olvloff" data-role="${lv.role}">✕ Remove ${esc(lv.label)} ${lv.price.toFixed(2)}</button>` : ""; })()}
    <div class="dim" style="font-size:10.5px;margin-top:4px">contracts: pick 1 / 2 / 5 / 10 on the chart's header</div>`;
  m.style.left = Math.min(x, window.innerWidth - 230) + "px"; m.style.top = Math.min(y, window.innerHeight - 160) + "px";
  document.body.appendChild(m);
  m.addEventListener("click", async e => {
    if (e.target.classList.contains("x")){ m.remove(); return; }
    const b = e.target.closest("button[data-do]"); if (!b) return; m.remove();
    if (b.dataset.do === "buy") ochOrder("BUY", price, n);
    else if (b.dataset.do === "sell") ochOrder("SELL", price, n);
    else if (b.dataset.do === "all") ochOrder(long ? "SELL" : "BUY", price, q);
    else if (b.dataset.do === "cxl") for (const o of d.orders) await cancelMine(o.order_id);
    else if (b.dataset.do === "olvl") optLevel(b.dataset.role, price, n);
    else if (b.dataset.do === "olvloff") optLevel(b.dataset.role, null, n);
  });
  const away = ev => { if (!m.isConnected){ document.removeEventListener("mousedown", away, true); return; } if (!m.contains(ev.target)) m.remove(); };
  setTimeout(() => document.addEventListener("mousedown", away, true), 0);
}
document.addEventListener("click", async e => {
  const sp = e.target.closest("#chartsPop button[data-showp]"); if (sp){ openChartWindow(sp.dataset.showp); document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); if (sp.dataset.showp === "ochart") pollOch(); return; }
  const och = e.target.closest("button[data-ochart]"); if (och){ e.stopPropagation(); chartOption(och.dataset.ochart, true); return; }
  const olb = e.target.closest("button[data-olink]"); if (olb && OCH.data){ e.stopPropagation(); const d = OCH.data;
    const out = await post("/api/trade/trade_as", {symbol: d.underlying, mode: olb.dataset.olink, opt_key: d.key, opt_qty: OCH.n});
    toast(out.ok ? (out.trade_as === "option" ? `${d.underlying} chart lines now trade ${out.opt_qty} ${d.label}` : `${d.underlying} chart lines trade the STOCK`) : "Not linked: " + (out.reason || ""), out.ok);
    OCH.data && renderOchHead(); return; }
  const h = e.target.closest("#ochHead button"); if (!h) return;
  if (h.dataset.och === "chain"){ showPanel("options"); return; }
  if (h.dataset.ochtf){ store.set("tf.ochart", +h.dataset.ochtf); ochart.view.offset = restOffset(); ochart.view.follow = true; ochart.view.yLo = ochart.view.yHi = null; drawChart(ochart); renderOchHead(); return; }
  if (h.dataset.ochn){ OCH.n = +h.dataset.ochn; renderOchHead(); return; }
  if (h.dataset.ochind){ const k = "och." + h.dataset.ochind; store.set(k, !store.get(k, false)); drawChart(ochart); renderOchHead(); return; }
  if (h.dataset.ochstop){ const d = OCH.data; if (!d) return;
    const price = h.dataset.ochstop === "off" ? null : (document.getElementById("ochStopPx") || {}).value, on = (document.getElementById("ochStopOn") || {}).value || "stock";
    if (h.dataset.ochstop === "set" && !price){ toast("Type the stop price first", false); return; }
    post("/api/trade/opt_stop", {key: d.key, price, on}).then(out => { toast(out.ok ? (price ? `Stop set: ${d.label} ${on === "stock" ? "when " + d.underlying + " trades " + price : "at " + price}` : "Stop off") : "Not set: " + (out.reason || ""), out.ok); poll(true); });
    return; }
  if (h.dataset.ochnow){ const d = OCH.data; if (!d) return; const pos = d.position, q = pos ? Math.abs(pos.qty) : 0, long = pos && pos.qty > 0;
    if (h.dataset.ochnow === "ALL") ochOrder(long ? "SELL" : "BUY", null, q, true);
    else if (h.dataset.ochnow === "HALF") ochOrder(long ? "SELL" : "BUY", null, Math.max(1, Math.floor(q / 2)), true);
    else ochOrder(h.dataset.ochnow, null, OCH.n); }
}, true);
document.getElementById("chartsMenu").querySelector("button").addEventListener("click", e => { e.stopPropagation(); const m = document.getElementById("chartsMenu"), open = !m.classList.contains("open"); document.querySelectorAll(".menu.open").forEach(x => x.classList.remove("open")); m.classList.toggle("open", open); });

/* CHARTS menu: a chart that is not up opens as a floating window (staggered so several can be up at once);
   one already docked or floating is brought to the front */
function openChartWindow(id){
  if (["obook", "otape", "obig"].includes(id)) setTimeout(pollOch, 50);
  if (id === "optall"){ ["ochart", "obook", "otape", "obig"].forEach(x => openChartWindow(x)); if (!OCH.key) toast("Pick a contract: OPTIONS, then click a strike — these four follow it", true); return; }
  const small = ["obook", "otape", "obig"].includes(id);
  if (LAY.hidden.includes(id)){
    if (small){   // the contract's windows sit side by side (never on top of each other), from the left
      const k = Object.keys(LAY.floats || {}).filter(x => ["obook", "otape", "obig"].includes(x)).length, W = document.getElementById("work").clientWidth || 1600;
      movePanel(id, "float", {l: Math.min(W - 340, 210 + k * 340), t: 80, w: 330, h: 470});
    } else { const n = Object.keys(LAY.floats || {}).length; movePanel(id, "float", {l: 90 + n * 34, t: 70 + n * 30, w: 620, h: 400}); }
  }
  else showPanel(id);
  const c = charts[id] || (id === "ochart" ? ochart : null); if (c) setTimeout(() => drawChart(c), 50);
}

/* ---------- the OPTION side, for the contract on the OPTION CHART: LEVEL II, T&S, BIG TAPE */
function obookRows(t){
  const mx = Math.max(1, ...t.book.map(r => Math.max(r.bid, r.ask))), mt = Math.max(1, ...t.book.map(r => Math.max(r.bought, r.sold)));
  return t.book.map(r => `<tr class="${r.best_bid ? "bb" : ""} ${r.best_ask ? "ba" : ""}" data-oprice="${r.price}">
      <td class="tr s">${r.sold ? `<i style="width:${Math.round(r.sold / mt * 100)}%"></i><span>${sz(r.sold)}</span>` : ""}</td>
      <td class="sz b">${r.bid ? `<i style="width:${Math.round(r.bid / mx * 100)}%"></i><span>${sz(r.bid)}</span>` : ""}</td>
      <td class="px">${r.price.toFixed(2)}</td>
      <td class="sz s">${r.ask ? `<i style="width:${Math.round(r.ask / mx * 100)}%"></i><span>${sz(r.ask)}</span>` : ""}</td>
      <td class="tr b">${r.bought ? `<i style="width:${Math.round(r.bought / mt * 100)}%"></i><span>${sz(r.bought)}</span>` : ""}</td></tr>`).join("");
}
/* The contract's LEVEL II and T&S drawn by the very same code as the stock's (same columns, colours, bars,
   highlights): its book and prints are turned into the stock ladder / tape shapes. Clicks are renamed (data-oact) so
   a click in them can only ever trade the CONTRACT, never the stock */
// THIS VISIT on the contract, from its own prints (oldest first): a visit to a price ends 3 steps away
function optVisits(d, t, step){
  const out = {}, open = new Set(), prints = (t.prints || []).slice().reverse(), now = state ? state.now : Date.now() / 1000;
  const ca = OPTCLR[d.key + "|above"] || 0, cb = OPTCLR[d.key + "|below"] || 0, bid = d.bid, ask = d.ask;
  for (const [tt, pp, n, sd] of prints){
    const p = +(+pp).toFixed(2), k = Math.round(p / step);
    if ((ca && tt <= ca && ask != null && p > ask) || (cb && tt <= cb && bid != null && p < bid)) continue;
    for (const j of [...open]) if (Math.abs(j - k) >= 3) open.delete(j);
    let v = out[p];
    if (!open.has(k)){ if (!v) v = out[p] = {s: 0, b: 0, ts: []}; else { v.s = 0; v.b = 0; } v.ts.push(tt); open.add(k); }
    if (!v) v = out[p] = {s: 0, b: 0, ts: [tt]};      // another price on the same step is already open: this one starts its own row
    if (sd === "sell") v.s += n; else if (sd === "buy") v.b += n;
    v.open = true; v.k = k;
  }
  for (const v of Object.values(out)){ v.open = open.has(v.k); v.n = v.ts.filter(x => now - x <= 3600).length; }
  return out;
}
// your stock chart's lines, read on the contract: the contract's own stop exactly, and where the contract should be
// when the stock gets to your 2nd entry / target / stop / pivot (today's delta: ≈ mid + Δ × the stock's move)
function optMarks(d){
  const out = [], mid = d.bid != null && d.ask != null ? (d.bid + d.ask) / 2 : d.last, spot = d.spot, delta = d.delta;
  const add = (price, role, label, extra) => { if (price != null && price > 0) out.push(Object.assign({price: +price.toFixed(2), role, label, dist: mid != null ? +(price - mid).toFixed(2) : null}, extra || {})); };
  const os = (T().opt_stops || {})[d.key];
  if (os && os.on === "option") add(+os.price, "stop", "STOP", {exact: true});
  const pos = d.position; if (pos && pos.per_contract) add(+pos.per_contract, "entry", "YOUR ENTRY", {exact: true});
  var olv = (T().opt_levels || {})[d.key] || {};
  if (olv.second_entry) add(+olv.second_entry, "second_entry", "2ND", {exact: true});
  if (olv.target) add(+olv.target, "target", "TARGET", {exact: true});
  if (olv.stop && !(os && os.on === "option")) add(+olv.stop, "stop", "STOP", {exact: true});
  const pane = paneFor(d.underlying), pl = pane && pane.play;
  if (pl && mid != null && spot && delta != null){
    const ownLong = (pl.side || "long") === "long", lines = (d.right === "C") === ownLong ? pl : (pl.alt || {});
    for (const [r, lbl] of [["second_entry", "2ND ENTRY"], ["target", "TARGET"], ["stop", "STOP"], ["trigger", "PIVOT"]]){
      if (!lines[r] || (r === "stop" && ((os && os.on === "option") || olv.stop))) continue;
      add(mid + delta * (lines[r] - spot), r, lbl, {est: true, at: lines[r], sym: d.underlying});
    }
    for (const sp of (pl.sneaky_levels || [])) add(mid + delta * (sp - spot), "sneaky", "SNEAKY PIVOT", {est: true, at: sp, sym: d.underlying});
  }
  // the OPTION FLOW on this very contract: the price the big money paid (Quant Data sweeps / blocks, and 100+ lots)
  const fl = {};
  for (const b of ((d.tape || {}).big || [])){ if (b.price == null) continue; const k = (+b.price).toFixed(2), f = fl[k] = fl[k] || {prem: 0, n: 0, buy: 0};
    f.prem += +b.premium || 0; f.n += 1; if (b.side === "buy" || /ask/i.test(b.side || "")) f.buy += +b.premium || 0; }
  for (const [k, f] of Object.entries(fl)) if (f.prem >= 25000)
    add(+k, "flow", "FLOW", {prem: f.prem, n: f.n, cp: d.right, buyside: f.buy >= f.prem / 2});
  return out;
}
function optLadderData(d, t){
  const orders = (d.orders || []), lastTrade = t.prints && t.prints.length ? +t.prints[0][1] : d.last;
  const rows = t.book.map(r => ({price: r.price, gap: false, bid: r.bid, ask: r.ask, sold: r.sold, bought: r.bought, tags: [], flow: null,
    mine: orders.filter(o => Math.abs((+o.lmt || 0) - r.price) < 0.004).map(o => ({id: o.order_id, action: o.action, qty: o.remaining ?? o.qty, role: "entry", status: o.status})),
    best_bid: r.best_bid, best_ask: r.best_ask, last: lastTrade != null && Math.abs(lastTrade - r.price) < 0.004,
    bid_state: r.reload_bid ? "RELOAD" : null, bid_proven: !!r.reload_bid, bid_stage: r.reload_bid ? "RELOADING" : null,
    ask_state: r.reload_ask ? "RELOAD" : null, ask_proven: !!r.reload_ask, ask_stage: r.reload_ask ? "RELOADING" : null,
    ps_b: r.ps_b, ps_a: r.ps_a}));
  const step = t.book.length > 1 ? Math.abs(t.book[0].price - t.book[1].price) || 0.01 : 0.01;
  const vis = optVisits(d, t, step), marks = optMarks(d);
  for (const r of rows){
    const v = vis[+(+r.price).toFixed(2)]; if (v){ r.vs = v.s; r.vb = v.b; r.vn = v.n; r.vopen = v.open; }
    const lv = marks.filter(m => Math.abs(m.price - r.price) < step / 2); if (lv.length) r.lv = lv;
  }
  return {rows, max_size: Math.max(1, ...rows.map(r => Math.max(r.bid, r.ask))), max_traded: Math.max(1, ...rows.map(r => Math.max(r.sold, r.bought))),
          memory_minutes: 60, big_shares: 100, huge_shares: 300, big_default: true, marks, tick: step, stack_seconds: 60};
}
function optTapeData(t){
  const now = state ? state.now : Date.now() / 1000;
  const recent = t.prints.map(([tt, pp, n, sd]) => ({price: +pp, size: n, side: sd || "mid", large: n >= 100, at: null, age: now - tt, exchange: ""}));
  let b = 0, sl = 0; for (const [tt, pp, n, sd] of t.prints){ if (now - tt > 60) break; if (sd === "buy") b += pp * n * 100; else if (sd === "sell") sl += pp * n * 100; }
  return {recent, usd_60: {buy: Math.round(b), sell: Math.round(sl)}};
}
// the stock ladder's column choices (COLS menu) and widths apply to the contract's ladder too
function sameCols(tb){ if (!tb || tb.dataset.cols2) return; tb.dataset.cols2 = "1"; try { applyLadCols(tb); makeColsResizable(tb); } catch (e) {} }
function optLadderHTML(d, t){ return ladderHTML(optLadderData(d, t)).replace(/data-act=/g, "data-oact=").replace(/draggable="true"/g, ""); }
// the contract's tape runs like the stock's: SPEED meter, prints that hit the RELOAD buyer / seller glow
function optTapeHTML(t){ const tt = optTapeData(t), d = OCH.data;
  const lad = d && d.tape === t ? optLadderData(d, t) : null;
  return tapeSpeedHTML(optSpeed(t.prints || []), "CT/S") + tapeHTML(tt, lad); }   // (no bought / sold money bar: just the prints)
function optSpeed(prints, span = 90, bucket = 3, fast = 10){
  const now = state ? state.now : Date.now() / 1000, nb = span / bucket, series = Array.from({length: nb}, () => [0, 0, 0, 0]);
  let nFast = 0, cFast = 0, nBefore = 0;
  for (const [tt, pp, n, sd] of prints){ const age = Math.max(0, now - tt); if (age >= span) continue;
    const row = series[nb - 1 - Math.floor(age / bucket)]; row[sd === "buy" ? 0 : sd === "sell" ? 1 : 2] += n; row[3] += 1;
    if (age < fast){ nFast++; cFast += n; } else if (age < fast + 60) nBefore++; }
  const pps = nFast / fast, base = nBefore / 60;
  const trend = nFast + nBefore < 5 ? "QUIET" : (base === 0 || pps >= 1.5 * base) ? "SPEEDING UP" : pps <= 0.6 * base ? "SLOWING" : "STEADY";
  return {pps: Math.round(pps * 10) / 10, sps: Math.round(cFast / fast), base_pps: Math.round(base * 10) / 10, trend, bucket, series};
}
// a big print on the contract lifts off its row on the OPTION LEVEL II and lands on the OPTION T&S, like the stock's
function flyBigOpt(d, t){
  const bk = document.querySelector(".pnl[data-p=obook] .obook"), tp = document.querySelector(".pnl[data-p=otape] .tape2");
  if (!d || !t || !bk || !tp || !bk.offsetParent || !tp.offsetParent) return;
  const big = 25, nowMs = Date.now(), now = state ? state.now : nowMs / 1000; let n = 0;
  for (const [k, at] of FLOWN) if (nowMs - at > 30000) FLOWN.delete(k);
  for (const [tt, pp, sz_, sd] of (t.prints || [])){
    if (now - tt > 2 || sz_ < big || n >= 3) continue;
    const key = `opt|${d.key}|${pp}|${sz_}|${Math.round(tt * 2)}`; if (FLOWN.has(key)) continue; FLOWN.set(key, nowMs); n++;
    const row = bk.querySelector(`tr[data-price="${+(+pp).toFixed(2)}"]`) || [...bk.querySelectorAll("tr[data-price]")].find(r => Math.abs(+r.dataset.price - pp) < 0.004);
    if (!row) continue;
    const a = row.getBoundingClientRect(), b = tp.getBoundingClientRect(); if (!a.width || !b.width) continue;
    const chip = document.createElement("div"); chip.className = "flychip " + (sd === "buy" ? "b" : sd === "sell" ? "s" : "");
    chip.textContent = `${sd === "buy" ? "▲" : sd === "sell" ? "▼" : "•"} ${sz_} ct @ ${(+pp).toFixed(2)}`;
    chip.style.left = (a.left + a.width / 2 - 50) + "px"; chip.style.top = a.top + "px"; document.body.appendChild(chip);
    requestAnimationFrame(() => requestAnimationFrame(() => { chip.style.left = (b.left + 8) + "px"; chip.style.top = (b.top + 20) + "px"; chip.style.opacity = "0.15"; }));
    setTimeout(() => chip.remove(), 900);
  }
}
// clicks in the contract's ladder: BUY / SELL the contracts (OPTION CHART header count) at that price
document.addEventListener("click", e => { const c = e.target.closest(".obook td[data-oact], .cbook td[data-oact]"); if (!c || !OCH.data) return; e.stopPropagation();
  const chip = e.target.closest(".chip[data-id]"); if (chip){ if (confirm("Cancel this order?")) cancelMine(+chip.dataset.id); return; }
  ochOrder(c.dataset.oact, +c.dataset.px, OCH.n); }, true);
document.addEventListener("contextmenu", e => { const r = e.target.closest(".obook tr[data-price], .cbook tr[data-price]"); if (!r || !OCH.data) return; e.preventDefault(); optChartMenu(ochart, e.clientX, e.clientY, +r.dataset.price); });
function obookTable(rows){ return `<table class="olad"><tr><th>SOLD</th><th>BID</th><th>PRICE</th><th>ASK</th><th>BOUGHT</th></tr>${rows}</table><div class="dim ofoot">click a price: BUY / SELL ${OCH.n} there (right-click the OPTION CHART works too)</div>`; }
function otapeRows(t){
  const tm = x => new Date(x * 1000).toLocaleTimeString("en-US", {timeZone: "America/New_York", hour12: false});
  return t.prints.map(([tt, pp, n, sd]) => `<tr class="${sd === "buy" ? "b" : sd === "sell" ? "s" : ""} ${n >= 100 ? "big" : ""}"><td class="dim">${tm(tt)}</td><td>${(+pp).toFixed(2)}</td><td>${sz(n)}</td><td class="dim">${sd === "buy" ? "at ask" : sd === "sell" ? "at bid" : ""}</td></tr>`).join("");
}
function otapeTable(pr){ return pr ? `<table class="otp"><tr><th>TIME</th><th>PRICE</th><th>CT</th><th></th></tr>${pr}</table>` : `<div class="dim" style="padding:8px">No prints on this contract yet.</div>`; }
/* CONTRACT MODE: pick a contract and the main LEVEL II and TIME & SALES follow it, like ORDER ENTRY (unless the
   OPTION LEVEL II / OPTION T&S windows are up — then those carry the contract and these stay on the stock).
   ✕ BACK TO SHARES on top puts all three back on the stock */
// each window decides on its own: "stock" keeps it on the shares while ORDER ENTRY trades the contract
const CPIN = (() => { try { return Object.assign({book: "auto", tape: "auto"}, store.get("cpin", {})); } catch (e) { return {book: "auto", tape: "auto"}; } })();
function setPin(which, v){ CPIN[which] = v; store.set("cpin", CPIN); P.book.last = null; P.tape.last = null; renderContractL2(); renderContractTape(); renderSwitchStrips(); poll(true); }
function contractMode(which){
  if (!(OC.link && OC.link.sym === curSym)) return false;
  const sd = paneFor(curSym); if (sd && sd.position && sd.position.qty) return false;   // holding the shares: the stock's Level II / T&S stay the stock's
  if (CPIN[which] === "stock") return false;
  const own = P[which === "tape" ? "otape" : "obook"];
  return !(own && own.el.offsetParent !== null);
}
function contractBar(kind){
  const d = OCH.data, l = OC.link, f = v => v == null ? "—" : (+v).toFixed(2);
  const t = d && d.tape;
  return `<div class="cbar" title="right-click: where the contract windows go / back to the shares"><b class="${l.right === "C" ? "b" : "s"}">${esc(optWords(contractName(l)))}</b></div>`;
}
// a window kept on the shares while a contract is picked: a thin strip to bring the contract into it
/* BOTH BOOKS: with a contract picked, the stock's LEVEL II and T&S stay as they are and the contract's open under
   them in the same spot (split). ONE WINDOW flips the stock ones to the contract instead (the old way) */
const PAIRED = {};
let PAIR_FOR = null;    // the contract the windows were last opened for      // contract window -> {zone, wasSplit, wasSecond} we put it in
function pairMode(){ return store.get("pairmode", "left"); }
function autoPair(){
  const mode = pairMode();
  if ((mode !== "split" && mode !== "left") || !(OC.link && OC.link.sym === curSym) || !LAY) return;
  if (PAIR_FOR === OC.link.key) return;          // placed once per contract: after that, move or close them as you like
  PAIR_FOR = OC.link.key;
  if (P.obook.el.offsetParent !== null && P.otape.el.offsetParent !== null) return;   // already up
  LAY.split = LAY.split || {}; LAY.second = LAY.second || {};
  const place = (opt, z, top) => {
    if ((LAY.floats || {})[opt]) return false;
    if (!LAY.zones[z].includes(opt)){ for (const zz of ZONES) LAY.zones[zz] = LAY.zones[zz].filter(x => x !== opt); LAY.hidden = LAY.hidden.filter(x => x !== opt); LAY.zones[z].push(opt); }
    if (!PAIRED[opt]) PAIRED[opt] = {zone: z, wasSplit: !!LAY.split[z], wasSecond: LAY.second[z], wasActive: LAY.active[z]};
    return true;
  };
  // where YOU last put them wins: dragged to another spot, floated, docked — the next contract opens them there
  const pref = {obook: store.get("oplace.obook", null), otape: store.get("oplace.otape", null)};
  if (pref.obook || pref.otape){
    for (const opt of ["obook", "otape"]){
      const pr = pref[opt]; if (!pr) continue;
      if (!PAIRED[opt]) PAIRED[opt] = {zone: pr.zone || null, wasSplit: pr.zone ? !!LAY.split[pr.zone] : false, wasSecond: pr.zone ? LAY.second[pr.zone] : null, wasActive: pr.zone ? LAY.active[pr.zone] : null};
      for (const zz of ZONES) LAY.zones[zz] = LAY.zones[zz].filter(x => x !== opt); LAY.hidden = LAY.hidden.filter(x => x !== opt); delete (LAY.floats || {})[opt];
      if (pr.float){ LAY.floats[opt] = pr.float; } else if (pr.zone){ LAY.zones[pr.zone].push(opt); LAY.active[pr.zone] = opt; if (pr.split){ LAY.split[pr.zone] = true; if (pr.second && LAY.zones[pr.zone].includes(pr.second)) LAY.second[pr.zone] = pr.second; if (pr.top) LAY.active[pr.zone] = pr.top; } }
    }
    const zb = pref.obook && pref.obook.zone, zt = pref.otape && pref.otape.zone;
    if (zb && zb === zt){ LAY.split[zb] = true; LAY.active[zb] = "obook"; LAY.second[zb] = "otape"; }
    applyLayout(); pollOch(); return;
  }
  if (mode === "left"){
    // the left column's top spot (where the watchlist / option chain sit): contract LEVEL II on top, its T&S under it
    const z = zoneOf("options") && zoneOf("options")[1] === "L" ? zoneOf("options") : (LAY.zones.TL.length || !LAY.zones.BL.length ? "TL" : "BL");
    if (place("obook", z) & place("otape", z)){ LAY.split[z] = true; LAY.active[z] = "obook"; LAY.second[z] = "otape"; }
  } else {
    for (const [main, opt] of [["book", "obook"], ["tape", "otape"]]){
      const z = zoneOf(main); if (!z) continue;
      if (place(opt, z)){ LAY.split[z] = true; LAY.active[z] = main; LAY.second[z] = opt; }
    }
  }
  applyLayout(); pollOch();
}
function rememberPlace(){
  // where the contract windows are right now (only when they are up): the next contract opens them there
  for (const opt of ["obook", "otape"]){
    const z = zoneOf(opt), f = (LAY.floats || {})[opt];
    if (f) store.set("oplace." + opt, {float: Object.assign({}, f)});
    else if (z) store.set("oplace." + opt, {zone: z, split: !!(LAY.split || {})[z], top: LAY.active[z], second: (LAY.second || {})[z]});
  }
}
function unpair(){
  PAIR_FOR = null;
  if (OC.link || Object.keys(PAIRED).length) rememberPlace();
  let changed = false;
  for (const [opt, p] of Object.entries(PAIRED)){
    for (const zz of ZONES) LAY.zones[zz] = LAY.zones[zz].filter(x => x !== opt); delete (LAY.floats || {})[opt]; if (!LAY.hidden.includes(opt)) LAY.hidden.push(opt);
    if (p.zone){ LAY.split[p.zone] = p.wasSplit; if (p.wasSecond) LAY.second[p.zone] = p.wasSecond; if (p.wasActive && LAY.zones[p.zone].includes(p.wasActive)) LAY.active[p.zone] = p.wasActive; }
    delete PAIRED[opt]; changed = true;
  }
  if (changed) applyLayout();
}
document.addEventListener("click", e => { const b = e.target.closest("button[data-pairmode]"); if (!b) return; e.stopPropagation();
  store.set("pairmode", b.dataset.pairmode);
  unpair(); store.set("oplace.obook", null); store.set("oplace.otape", null);
  if (b.dataset.pairmode !== "switch") autoPair();
  P.book.last = null; P.tape.last = null; renderContractL2(); renderContractTape(); poll(true); }, true);
// the contract windows' header shows only the contract; where they go / back to the shares sits on a right-click
document.addEventListener("contextmenu", e => {
  const h = e.target.closest("#obookHd, #otapeHd, .cbar"); if (!h || !(OC.link && OC.link.sym === curSym)) return;
  e.preventDefault();
  const old = document.getElementById("cmenu"); if (old) old.remove();
  const m = document.createElement("div"); m.id = "cmenu"; m.className = "pop cmenu";
  const pm = pairMode(), which = h.closest(".pnl[data-p=tape], #otapeHd") || h.id === "otapeHd" ? "tape" : "book";
  m.innerHTML = `<div class="dim" style="font-size:11px;margin-bottom:4px">${esc(optWords(contractName(OC.link)))}<span class="x" title="close (Esc)">✕</span></div>`
    // (where they go only matters when TED placed them; windows you keep in your layout stay where you put them)
    + (Object.keys(PAIRED).length || h.classList.contains("cbar") ? (pm === "left" ? `<button data-pairmode="split">Contract windows UNDER the stock's</button>` : `<button data-pairmode="left">Contract windows in the LEFT column</button>`)
       + (h.classList.contains("cbar") ? "" : `<button data-pairmode="switch">ONE WINDOW: LEVEL II / T&S flip to the contract</button>`) : "")
    + (h.classList.contains("cbar") ? `<button data-pin="${which}" data-pinv="stock">Only this window back to ${esc(OC.link.sym)} shares</button>` : "")
    + `<button data-unlinkall="1">✕ Everything back to ${esc(OC.link.sym)} shares</button>`;
  m.style.left = Math.min(e.clientX, innerWidth - 280) + "px"; m.style.top = Math.min(e.clientY, innerHeight - 160) + "px";
  document.body.appendChild(m);
  m.addEventListener("pointerup", ev => { if (ev.target.closest("button, .x")) setTimeout(() => m.remove(), 0); });
  setTimeout(() => document.addEventListener("click", function off(ev){ if (!m.contains(ev.target)){ m.remove(); document.removeEventListener("click", off); } }), 0);
});
function renderSwitchStrips(){
  for (const [which, pid] of [["book", "book"], ["tape", "tape"]]){
    const pc = P[pid].pc; let el = pc.querySelector(":scope > .cswitch");
    const show = OC.link && OC.link.sym === curSym && CPIN[which] === "stock";
    if (!show){ if (el) el.remove(); continue; }
    if (!el){ el = document.createElement("div"); el.className = "cswitch"; pc.prepend(el); }
    const h = `<span>${which === "tape" ? "T&S" : "LEVEL II"} on ${esc(OC.link.sym)} shares · ORDER ENTRY trades ${esc(contractName(OC.link))}</span><button data-pin="${which}" data-pinv="auto">show the contract here</button>`;
    if (el.dataset.h !== h){ el.dataset.h = h; el.innerHTML = h; }
  }
}
document.addEventListener("click", e => { const b = e.target.closest("button[data-pin]"); if (!b) return; e.stopPropagation(); setPin(b.dataset.pin, b.dataset.pinv); }, true);
function renderContractL2(){
  const el = P.book.el, on = contractMode("book");
  el.classList.toggle("cmode", on);
  if (!on) return;
  let box = P.book.pc.querySelector(".cbook"); if (!box){ box = document.createElement("div"); box.className = "cbook"; P.book.pc.appendChild(box); }
  const d = OCH.data, t = d && d.tape && d.key === OC.link.key ? d.tape : null;
  const html = contractBar("LEVEL II") + `<div class="obook cb">${t ? `<div class="ladder-wrap olw">${optLadderHTML(d, t)}</div>` : `<div class="dim" style="padding:8px">Loading the contract's book…</div>`}</div>`;
  if (box.dataset.h !== html){ box.dataset.h = html; box.innerHTML = html; }
  sameCols(box.querySelector(".obook.cb table"));
  if (t){ const w = box.querySelector(".obook.cb .ladder-wrap"); if (w) eatMarks(w, {symbol: "opt|" + d.key, ladder: optLadderData(d, t), tape: {recent: []}}, box.querySelector(".obook.cb")); }
  centerSpread(box.querySelector(".obook.cb"));
}
function renderContractTape(){
  const el = P.tape.el, on = contractMode("tape");
  el.classList.toggle("cmode", on);
  if (!on) return;
  let box = P.tape.pc.querySelector(".ctape"); if (!box){ box = document.createElement("div"); box.className = "ctape"; P.tape.pc.appendChild(box); }
  const d = OCH.data, t = d && d.tape && d.key === OC.link.key ? d.tape : null;
  const html = contractBar("T&S") + `<div class="otape cb">${t ? `<div class="p-tape">${optTapeHTML(t)}</div>` : `<div class="dim" style="padding:8px">Loading the contract's prints…</div>`}</div>`;
  if (box.dataset.h !== html){ box.dataset.h = html; box.innerHTML = html; }
}
document.addEventListener("click", e => { if (!e.target.closest("button[data-unlinkall]")) return;
  OC.link = null; TMODE = "stock"; CPIN.book = CPIN.tape = "auto"; unpair(); store.set("cpin", CPIN); P.ticket.last = null; renderContractL2(); renderContractTape(); renderSwitchStrips(); poll(true); toast("Back on the shares", true); });
function renderOptPanels(){
  const d = OCH.data, t = d && d.tape, f = v => v == null ? "—" : (+v).toFixed(2), name = d ? esc(optWords(d.label)) : "";
  const none = `<div class="dim" style="padding:8px">Pick a contract: OPTIONS, then click a strike (or 📈). Its book, prints and big prints show here.</div>`;
  const pm = pairMode();
  const hd = (id, title, extra) => { const el = document.getElementById(id); if (!el) return; const h = d ? (id === "obigHd" ? `<b>${title}</b> <span class="${d.right === "P" ? "s" : "b"}">${name}</span>${extra || ""}` : `<b class="${d.right === "P" ? "s" : "b"}">${name}</b>`) : `<b>${title}</b>`; if (el.dataset.h !== h){ el.dataset.h = h; el.innerHTML = h; } };
  const put = (sel, html) => { const el = document.querySelector(sel); if (el && el.dataset.h !== html){ el.dataset.h = html; el.innerHTML = html; } };
  if (!d || !t){ put(".pnl[data-p=obook] .obook", none); put(".pnl[data-p=otape] .otape", none); put(".obig", none); hd("obookHd", "OPTION LEVEL II"); hd("otapeHd", "OPTION T&S"); hd("obigHd", "OPTION BIG TAPE"); return; }
  // LEVEL II for the contract
  const rows = obookRows(t);
  if (false) t.book.map(r => `<tr class="${r.best_bid ? "bb" : ""} ${r.best_ask ? "ba" : ""}" data-oprice="${r.price}">
      <td class="tr s">${r.sold ? `<i style="width:${Math.round(r.sold / mt * 100)}%"></i><span>${sz(r.sold)}</span>` : ""}</td>
      <td class="sz b">${r.bid ? `<i style="width:${Math.round(r.bid / mx * 100)}%"></i><span>${sz(r.bid)}</span>` : ""}</td>
      <td class="px">${r.price.toFixed(2)}</td>
      <td class="sz s">${r.ask ? `<i style="width:${Math.round(r.ask / mx * 100)}%"></i><span>${sz(r.ask)}</span>` : ""}</td>
      <td class="tr b">${r.bought ? `<i style="width:${Math.round(r.bought / mt * 100)}%"></i><span>${sz(r.bought)}</span>` : ""}</td></tr>`).join("");
  hd("obookHd", "OPTION LEVEL II");
  setTimeout(centerObook, 0);
  put(".pnl[data-p=obook] .obook", `<div class="ladder-wrap olw">${optLadderHTML(d, t)}</div>`);
  sameCols(document.querySelector(".pnl[data-p=obook] .obook table"));
  { const w = document.querySelector(".pnl[data-p=obook] .obook .ladder-wrap"); if (w) eatMarks(w, {symbol: "opt|" + d.key, ladder: optLadderData(d, t), tape: {recent: []}}, document.querySelector(".pnl[data-p=obook] .obook")); }
  // T&S for the contract
  const tm = x => new Date(x * 1000).toLocaleTimeString("en-US", {timeZone: "America/New_York", hour12: false});
  const pr = otapeRows(t);
  hd("otapeHd", "OPTION T&S");
  put(".pnl[data-p=otape] .otape", `<div class="p-tape">${optTapeHTML(t)}</div>`);
  flyBigOpt(d, t);
  renderContractL2(); renderContractTape();
  // BIG TAPE for the contract: big prints + Quant Data sweeps / blocks on it
  const bg = t.big.map(x => `<tr class="${x.side === "buy" || x.side === "ask" ? "b" : x.side === "sell" || x.side === "bid" ? "s" : ""}"><td class="dim">${tm(x.t)}</td><td>${x.price != null ? (+x.price).toFixed(2) : "—"}</td><td>${sz(x.size || 0)}</td><td>${usdK(x.premium || 0)}</td><td class="dim">${x.src === "flow" ? esc((x.kind || "FLOW").toUpperCase()) : ""}</td></tr>`).join("");
  hd("obigHd", "OPTION BIG TAPE", ` <span class="dim">100+ contracts or $50k+, and the option flow on this contract</span>`);
  put(".obig", bg ? `<table class="otp"><tr><th>TIME</th><th>PRICE</th><th>CT</th><th>$</th><th></th></tr>${bg}</table>` : `<div class="dim" style="padding:8px">No big prints on this contract yet.</div>`);
}
document.addEventListener("click", e => { const r = e.target.closest(".obook tr[data-oprice]"); if (!r || !OCH.data) return;
  const price = +r.dataset.oprice, d = OCH.data; optChartMenu(ochart, e.clientX, e.clientY, price); });

/* ---------- FAST: in and out of the stock from the chart, one click. Getting out never asks */
/* THE ORDER BAR on top of the stock chart: BUY · SELL · CLOSE POSITION · SELL 25 / 50 / 75 / 100 %. All limits.
   STOCK trades the shares; OPTION trades the contract on the OPTION CHART (in contracts). Getting out never asks. */
const QB = {mode: "stock"};     // every launch starts on STOCK: OPT only when you pick it (or hold / link a contract)
function qbTarget(d){
  const k = d && linkedContract(d.symbol);
  if (QB.mode === "option" && k){
    const p = (((state || {}).account || {}).opt_positions || []).find(x => x.key === k), oq = (OCH.data && OCH.data.key === k) ? OCH.data : null;
    return {opt: true, key: k, name: shortKey(k), n: OCH.n || 1, unit: "ct", held: p ? p.qty : 0, bid: oq ? oq.bid : p ? p.bid : null, ask: oq ? oq.ask : p ? p.ask : null};
  }
  const pos = d && d.position;
  return {opt: false, key: d.symbol, name: d.symbol, n: TK.qty || T().default_shares || 100, unit: "sh", held: pos && pos.qty ? pos.qty : 0, bid: d.bid, ask: d.ask};
}
function renderFast(d){
  const el = document.getElementById("fastStock"); if (!el) return;
  if (!d){ el.innerHTML = ""; return; }
  const k = linkedContract(d.symbol), pl = d.play || {};
  if (pl.trade_as_set) QB.mode = pl.trade_as === "option" && pl.opt_key ? "option" : "stock";     // what the chart's lines trade
  if (!k && QB.mode === "option") QB.mode = "stock";
  const x = qbTarget(d), q = Math.abs(x.held), long = x.held > 0, f = v => v == null ? "—" : x.opt ? (+v).toFixed(2) : px(v);
  const outw = x.held < 0 ? "COVER" : "SELL";
  const pct = [25, 50, 75, 100].map(p => `<button class="out ${p === 100 ? "all" : ""}" data-qb="P${p}" ${q ? "" : "disabled"} title="${q ? `${outw} ${p}% of your ${q} ${x.unit} now, a limit at the touch` : "nothing to sell"}">${p}%</button>`).join("");
  const tt = T(), canArm = tt.can_trade || (tt.locked && tt.mode !== "LIVE");
  const armBit = tt.armed ? "" : canArm ? `<button class="qbarm" data-qbarm="1" title="orders are off until you ARM (every launch starts disarmed)">${tt.locked ? "UNLOCK" : "ARM"}</button>`
    : `<span class="qbwhy" title="${esc(tt.why_not || "")}">can't trade: ${esc(String(tt.why_not || "no account").slice(0, 60))}</span>`;
  const h = (d.halted ? `<span class="haltbadge" title="IBKR says it is halted: nothing trades, orders sit">${esc(d.halted)}</span>` : "") + armBit +
    `<span class="qbmode"><button data-qbm="stock" class="${x.opt ? "" : "on"}">STOCK<i class="qsym"> ${esc(d.symbol)}</i></button><button data-qbm="option" class="${x.opt ? "on" : ""}" ${k ? "" : "disabled"} title="${k ? "trade " + esc(shortKey(k)) + " (the OPTION CHART's contract)" : "pick a contract in OPTIONS first"}">OPT<i class="qsym">ION</i>${k ? " " + esc(k.split(" ")[2]) : ""}</button></span>
    <input id="qbQty" type="number" min="1" step="1" value="${x.n}" title="${x.opt ? "contracts" : "shares"}"><span class="dim">${x.unit}</span>
    <button class="b big" data-qb="BUY" title="BUY ${x.n} ${x.unit} now: a limit at the ask (${f(x.ask)})">BUY</button><button class="s big" data-qb="SELL" title="SELL ${x.n} ${x.unit} now: a limit at the bid (${f(x.bid)})">SELL</button>
    <button class="out close" data-qb="CLOSE" ${q ? "" : "disabled"} title="close the whole position now, a limit at the touch">CLOSE<i class="qsym"> POSITION</i></button><span class="qbout">${outw}</span>${pct}
    <span class="qbpos ${q ? (long ? "b" : "s") : "dim"}">${q ? `${long ? "LONG" : "SHORT"} ${sz(q)} ${x.unit}` : "FLAT"}${x.opt ? " · " + esc(x.name) : ""}</span>`;
  renderOptPos(d);
  if (el.contains(document.activeElement) && document.activeElement.id === "qbQty") return;     // typing a size
  if (el.dataset.h !== h){ el.dataset.h = h; el.innerHTML = h; }
}
document.addEventListener("input", e => { if (e.target.id !== "qbQty") return; const v = Math.max(1, Math.round(+e.target.value || 1));
  if (QB.mode === "option") OCH.n = v; else TK.qty = v; });
document.addEventListener("click", async e => {
  if (e.target.closest("#fastStock button[data-qbarm]")){ document.getElementById("armBtn").click(); return; }
  const m = e.target.closest("#fastStock button[data-qbm]"); if (m){ const d0 = curData(); QB.mode = m.dataset.qbm; store.set("qb.mode", QB.mode);
    // the pick is what this ticker trades: the order bar AND the chart's 2nd entry / STOP / TARGET
    if (d0){ const out = await post("/api/trade/trade_as", {symbol: d0.symbol, mode: QB.mode, opt_key: linkedContract(d0.symbol), opt_qty: OCH.n || 1});
      toast(out.ok ? (QB.mode === "option" ? `TRADING ${shortKey(linkedContract(d0.symbol))} — the chart's lines buy / sell the contract` : `TRADING ${d0.symbol} STOCK`) : "Not switched: " + (out.reason || ""), out.ok); }
    renderFast(curData()); return; }
  const b = e.target.closest("#fastStock button[data-qb]"); if (!b) return;
  const d = curData(); if (!d) return;
  const x = qbTarget(d), q = Math.abs(x.held), long = x.held > 0, act = b.dataset.qb;
  const done = (out, what) => { toast(out.ok ? what + ": " + (out.sent || "done") : "Blocked: " + (out.reason || ""), out.ok); poll(true); if (x.opt) pollOch(); };
  if (act === "CLOSE" || act[0] === "P"){                                                  // out: never a confirm box
    if (!q) return toast("Nothing to close", false);
    const n = act === "CLOSE" ? q : Math.max(1, Math.floor(q * (+act.slice(1)) / 100));
    if (x.opt) return done(await post("/api/trade/opt_adjust", {key: x.key, contracts: n >= q ? 0 : n, mode: "close", price: null}), act === "CLOSE" ? "CLOSED" : `${act.slice(1)}% OUT`);
    return done(await post("/api/trade/adjust", {symbol: d.symbol, shares: n, mode: "close"}), act === "CLOSE" ? "CLOSED" : `${act.slice(1)}% OUT`);
  }
  const n = Math.max(1, Math.round(+(document.getElementById("qbQty") || {}).value || x.n));
  const against = q && ((long && act === "SELL") || (!long && act === "BUY"));
  // more than you hold the other way is not a close: it closes and opens the other side. Never silently cut down,
  // never sent without you saying so (even with ONE-CLICK on)
  const closing = against && n <= q;
  if (against && n > q && !confirm(`You hold ${q} ${long ? "long" : "short"}. ${act} ${n} closes the ${q} and opens ${n - q} ${long ? "SHORT" : "LONG"}. Send it?`)) return;
  if (!canTrade() && !closing){ toast(whyNot() + (/ARM/i.test(whyNot()) ? "" : " — click ARM"), false); return; }
  if (x.opt){
    const send = async () => done(closing ? await post("/api/trade/opt_adjust", {key: x.key, contracts: Math.min(n, q), mode: "close", price: null})
      : await post("/api/trade/opt_open", Object.assign(optParts(x.key), {action: act, contracts: n, price: null})), act);
    const so = closing ? 0 : shortOpening(x.key, act, n); if (so) return shortOpenConfirm(`${n} ${x.name} now`, so, send);
    if (T().one_click || closing) return send();
    return confirmBox(`${act} ${n} ${x.name}`, `a limit ${act === "BUY" ? "at the ask " + (x.ask != null ? (+x.ask).toFixed(2) : "") : "at the bid " + (x.bid != null ? (+x.bid).toFixed(2) : "")}, fills now · ONE-CLICK (top bar) skips this box`, act === "BUY" ? "b" : "s", send);
  }
  const touch = act === "BUY" ? d.ask : d.bid;
  if (!(touch > 0)){ toast("No quote yet", false); return; }
  const tk = tickOfPx(touch), price = snapPx(act === "BUY" ? touch + 3 * tk : touch - 3 * tk);
  const send = async () => done(await post("/api/trade/order", {symbol: d.symbol, action: act, price, qty: closing ? Math.min(n, q) : n, type: "LMT", bracket: closing ? false : !!T().bracket, tif: "DAY", nonce: "qb" + Date.now(), flip: against && n > q}), act);
  if (T().one_click || closing) return send();
  confirmBox(`${act} ${sz(n)} ${d.symbol} @ ${px(price)}`, `limit: ${act === "BUY" ? "ask" : "bid"} ${px(touch)}, never ${act === "BUY" ? "above" : "below"} ${px(price)}${T().bracket ? " · with your stop and target" : ""} · ONE-CLICK (top bar) skips this box`, act === "BUY" ? "b" : "s", send);
});
function optParts(key){ const [s, e, x] = key.split(" "); return {symbol: s, expiry: e, strike: parseFloat(x), right: x.slice(-1)}; }

// the option ladder keeps the spread in the middle of the window, unless you scrolled it in the last 4 seconds
let obookUserScroll = 0;
(function(){ const pc = P.obook && P.obook.pc; if (pc) pc.addEventListener("wheel", () => { obookUserScroll = Date.now(); }, {passive: true});
  document.addEventListener("wheel", e => { if (e.target.closest && e.target.closest(".cbook")) obookUserScroll = Date.now(); }, {passive: true}); })();
function centerSpread(sc){
  // keep the spread (best bid and best ask) in the middle of the scrolling box, by where they are on screen
  if (!sc || sc.offsetParent === null || Date.now() - obookUserScroll < 4000) return;
  const a = sc.querySelector("tr.ba, tr.best-ask"), b = sc.querySelector("tr.bb, tr.best-bid"); if (!a && !b) return;
  const ra = (a || b).getBoundingClientRect(), rb = (b || a).getBoundingClientRect(), box = sc.getBoundingClientRect();
  const mid = (Math.min(ra.top, rb.top) + Math.max(ra.bottom, rb.bottom)) / 2, y = mid - box.top, h = sc.clientHeight;
  // still: only when the spread drifts into the top or bottom fifth (or a new contract opens) does the view move
  const key = (typeof OCH !== "undefined" && OCH.key) || "";
  if (sc.dataset.ckey !== key || y < h * 0.2 || y > h * 0.8) sc.scrollTop += y - h / 2;
  sc.dataset.ckey = key;
}
function centerObook(){ centerSpread(P.obook && P.obook.pc); }

/* ---------- STOCK or OPTIONS: drawing a NEW 2nd entry on the stock chart asks which it trades. OPTIONS ties the
   chart's 2nd entry, STOP and TARGET to the contract on the OPTION CHART: the stock trades through the 2nd entry and
   the contract is bought (a limit), the stock hits the target and every contract is sold, the STOP line is its stop. */
function paneFor(sym){ return ((state && state.panes) || []).concat(Object.values((state && state.extra) || {})).find(d => d && d.symbol === sym); }
function optLinkFor(sym){ return ((state && state.trading && state.trading.opt_links) || {})[sym] || null; }
function linkedContract(sym){ const k = OCH.key || (OC.link && OC.link.key); if (k && k.split(" ")[0] === sym) return k;
  const d = paneFor(sym); return d && d.play && d.play.trade_as === "option" && d.play.opt_key ? d.play.opt_key : null; }
function shortKey(k){ const [s, e, x] = k.split(" "); return `${s} ${e.slice(4, 6)}/${e.slice(6, 8)} ${x}`; }
function tradeAsBox(sym, se, onPick, onCancel){
  const old = document.getElementById("modal"); if (old) old.remove();
  const k = linkedContract(sym), ol = optLinkFor(sym), n0 = (ol && ol.qty) || OCH.n || 1, t = (state && state.trading) || {};
  const m = document.createElement("div"); m.id = "modal"; m.className = "tradeas";
  m.innerHTML = `<div class="box"><h2>2ND ENTRY ${esc(sym)} ${px(se)} — TRADE IT WITH</h2>
    <div class="ta"><button class="pick stock ${ol ? "" : "on"}" data-ta="stock"><b>STOCK</b><span>${esc(sym)} shares · the entry order goes in now${t.armed ? "" : " (once ARMED)"}</span></button>
    <button class="pick opt ${ol ? "on" : ""}" data-ta="option" ${k ? "" : "disabled"}><b>OPTIONS</b><span>${k ? `BUY <input id="taN" type="number" min="1" step="1" value="${n0}"> × ${esc(shortKey(k))} when ${esc(sym)} trades through ${px(se)}` : "no " + esc(sym) + " contract on the OPTION CHART yet — pick one in OPTIONS first"}</span></button></div>
    <div class="legs">OPTIONS: the STOP line takes the contract out when ${esc(sym)} trades through it, the TARGET sells every contract. All limits.</div>
    <div class="btns"><button class="no">Cancel (Esc)</button></div></div>`;
  let picked = false;
  const close = () => { m.remove(); document.removeEventListener("keydown", key); if (!picked && onCancel) onCancel(); };
  const key = e => { if (e.key === "Escape") close(); };
  m.querySelector(".no").onclick = close;
  m.onclick = e => { if (e.target === m) return close(); const b = e.target.closest("button[data-ta]"); if (!b || e.target.tagName === "INPUT") return;
    const n = Math.max(1, Math.round(+(m.querySelector("#taN") || {}).value || 1)); picked = true; close();
    onPick(b.dataset.ta === "option" ? {trade_as: "option", opt_key: k, opt_qty: n} : {trade_as: "stock"}); };
  document.addEventListener("keydown", key); document.body.appendChild(m);
}
{ const rawPost = post;
  post = async function(path, body){
    if (path === "/api/level" && body && body.trade_as === undefined && body.price != null && body.on !== false &&
        (body.role === "second_entry" || body.role === "alt_second_entry")){
      const d = paneFor(String(body.symbol || "").toUpperCase()), pl = (d && d.play) || {};
      const alt = body.role === "alt_second_entry" || (body.side && body.side !== (pl.side || "long"));
      const had = alt ? (pl.alt || {}).second_entry : pl.second_entry;
      if (!had && d && !pl.trade_as_set){   // a NEW 2nd entry and STOCK / OPTION not picked yet on the ORDER BAR: ask
        return new Promise(res => tradeAsBox(d.symbol, +body.price, async pick => res(await rawPost(path, Object.assign({}, body, pick))),
                                             () => res({ok: false, reason: "not drawn (cancelled)"})));
      }
    }
    return rawPost(path, body);
  };
}

/* ---------- THE PRO LADDER (default). Jigsaw's Depth & Sales, made for PS60:
   LEVEL │ STACK │ SOLD │ BID │ PRICE │ ASK │ BOUGHT │ STACK
   · SOLD / BOUGHT = THIS VISIT: what hit the bid / lifted the ask since price came back to this price (a visit ends when
     price trades 3 ticks away — one cent of chop is not leaving). ×N on the price = visits in the last 15 minutes.
   · STACK = size ADDED (+, buyers / sellers stepping up) or PULLED (−, left without trading) at that price in the last
     minute. Lit = big: STEPPING UP / PULLING.
   · BID / ASK = resting size: drains as it gets hit, ↻N solid green / red = the RELOAD buyer / seller (your edge), with the
     $ he absorbed; ↩×2 = he came BACK.
   · LEVEL = your chart: PIVOT, 2ND ENTRY, TARGET, STOP (both sides), SNEAKY PIVOT (yours and TED's), the option STRIKES
     getting the money, high / low of day — a coloured band on the row, AT … when price is on it; off the rows they sit in
     the strips above / below with their distance. */
const LVROLE = {trigger: ["PIVOT", "pv"], second_entry: ["2ND ENTRY", "se"], target: ["TARGET", "tg"], stop: ["STOP", "sl"], extra: ["LEVEL", "ex"],
  sneaky: ["SNEAKY PIVOT", "sn"], sneaky_auto: ["SNEAKY", "sn"], hod: ["HIGH OF DAY", "hl"], lod: ["LOW OF DAY", "hl"], strike: ["STRIKE", "st"],
  reload_bid: ["RELOAD BUYER", "rb"], reload_ask: ["RELOAD SELLER", "ra"], entry: ["YOUR ENTRY", "hl"], flow: ["FLOW", "st"],
  vwap: ["VWAP", "vw"], sma50: ["50-DAY SMA", "d50"], key: ["KEY LEVEL", "key"]};
const LVRANK = {key: 5, entry: 0, stop: 0, second_entry: 1, target: 2, trigger: 3, sneaky: 4, reload_bid: 5, reload_ask: 5, flow: 6, strike: 6, sneaky_auto: 7, extra: 8, vwap: 6, sma50: 6, hod: 9, lod: 9};
const LVSHORT = {entry: "ENTRY", trigger: "PIV", second_entry: "2ND", target: "TGT", stop: "STOP", extra: "LVL", sneaky: "SNKY", sneaky_auto: "SNKY·T", hod: "HOD", lod: "LOD", sma50: "50D"};
function lvWords(m, short){
  const base = short && LVSHORT[m.role] ? LVSHORT[m.role] : (LVROLE[m.role] || [m.label])[0];
  if (m.role === "strike") return `${short ? "" : (m.cp === "P" ? "PUTS HIT " : "CALLS HIT ")}${m.label} ${usdK(m.prem)}${!short && m.n > 1 ? " ×" + m.n : ""}${!short && m.dte != null ? " " + Math.round(m.dte) + "d" : ""}${m.hot ? "⚡" : ""}`;
  if (m.role === "flow") return `${short ? "" : "OPTION FLOW "}${usdK(m.prem)}${m.n > 1 ? " ×" + m.n : ""}${short ? "" : m.buyside ? " (paid the ask)" : " (hit the bid)"}`;
  if (m.role === "reload_bid" || m.role === "reload_ask") return short ? `${m.role === "reload_bid" ? "BUYER" : "SELLER"} ↻${m.refills || ""}` : `${base} ↻${m.refills || ""}`;
  if (m.role === "vwap") return m.label === "PM VWAP" ? (short ? "PMVWAP" : "PREMARKET VWAP") : "VWAP";
  if (m.role === "key") return short ? m.short : m.label;
  if (m.est) return (short ? "≈" : "≈ ") + base + (short ? "" : ` (when ${m.sym} trades ${px(m.at)})`);
  return base + (m.alt && !short ? " (other side)" : "");
}
function lvCls(m){ const c = (LVROLE[m.role] || ["", "ex"])[1]; return m.role === "strike" || m.role === "flow" ? "st" + (m.cp === "P" ? "p" : "c") : c; }
function distTxt(d, tick){ if (d == null) return ""; const t = Math.round(Math.abs(d) / (tick || 0.01)); return (d >= 0 ? "+" : "−") + Math.abs(d).toFixed(Math.abs(d) < 1 && tick && tick < 0.01 ? 4 : 2) + (t <= 50 ? ` · ${t}t` : ""); }
/* PACE OF TAPE: speed against this stock's own normal (×1.0 = normal), who is pushing, the flow behind it, and the
   call at your level. One strip on the ladder and on the T&S, the last-price row glowing harder as the tape runs */
/* VWAP and the daily 50-day: on the LEVEL II only (not the T&S), always, with how far price is from each (live) */
// THE EDGE chip: how many of the seven reads agree with the move right now (click: the PS60 STORY panel)
function edgeChip(eg){
  if (!eg) return "";
  const cls = eg.label === "HIGH PROBABILITY" ? "hp" : eg.label === "BUILDING" ? "bd" : "lo";
  const tip = eg.checks.map(c => `${c.ok === true ? "✓" : c.ok === 0.5 ? "½" : c.ok === false ? "✗" : "·"} ${c.k}: ${c.why}`).join("\n");
  return `<b class="edge ${cls} ${eg.side === "LONG" ? "lg" : "sh"}" data-story="1" title="${esc("THE EDGE " + eg.side + ": " + eg.label + "\n" + tip)}">EDGE ${eg.score % 1 ? eg.score.toFixed(1) : eg.score}/${eg.of} ${eg.side}${eg.label === "HIGH PROBABILITY" ? " · HIGH PROBABILITY" : ""}</b>`;
}
function refsHTML(r, eg){
  if (!r || !(r.vwap || r.sma50)) return eg ? `<div class="refstrip">${edgeChip(eg)}</div>` : "";
  const one = (cls, name, v, dst, tip) => v ? `<span class="rf ${cls}" title="${esc(tip)}"><b>${name}</b> ${px(v)}${dst != null ? ` <i class="${dst >= 0 ? "up" : "dn"}">${dst >= 0 ? "▲ +" : "▼ −"}${Math.abs(dst).toFixed(2)}</i>` : ""}</span>` : "";
  return `<div class="refstrip">`
    + one("vw", r.vwap_label === "PM VWAP" ? "PM VWAP" : "VWAP", r.vwap, r.vwap_dist, r.vwap_label === "PM VWAP" ? "premarket VWAP: the real one starts at 9:30" : "VWAP from the 9:30 open (the desk VWAP): above it buyers own the day, below it sellers do. ▲/▼ = how far price is above / below it")
    + one("d50", "50-DAY", r.sma50, r.sma50_dist, "the daily 50-day simple moving average (today's bar included, like the daily chart). ▲/▼ = how far price is above / below it")
    + edgeChip(eg) + `</div>`;
}
/* PS60 STORY: one line over the LEVEL II (the story right now), and the whole story in its own window */
const FLOW_SHORT = {"NOT YET CONFIRMED": "FLOW: NOT YET", DEVELOPING: "FLOW: DEVELOPING", CONFIRMED: "FLOW: CONFIRMED", CONFLICTING: "FLOW: CONFLICTING"};
const FLOW_CLS = {"NOT YET CONFIRMED": "nyc", DEVELOPING: "dev", CONFIRMED: "conf", CONFLICTING: "cfl"};
function storyLineHTML(s){
  if (!s || !s.now) return "";
  const fl = s.flow && s.focus && s.focus.approach ? s.flow.state : "";
  return `<div class="storyln t-${esc(s.tone || "neutral")}${s.attention ? " att" : ""}" data-story="1" title="PS60 STORY: ${esc(s.now)} (click for the whole story)">`
    + (s.ctx && s.ctx.bias ? `<b class="dbias ${s.ctx.bias}" title="${esc(s.ctx.text || "")}">${s.ctx.bias === "bull" ? "▲ DAILY" : "▼ DAILY"}</b>` : "")
    + (s.attention ? `<b class="hat">HIGH ATTENTION</b>` : "") + (fl ? `<b class="fst ${FLOW_CLS[fl]}">${FLOW_SHORT[fl]}</b>` : "")
    + (s.play && s.attention ? `<b class="pbp">LIVE</b><span class="stx">${esc(s.play)}</span></div>` : `<span class="stx">${esc(s.now)}</span></div>`);
}
document.addEventListener("click", e => { if (e.target.closest(".storyln[data-story], .edge[data-story]") && typeof showPanel === "function") showPanel("story"); });
function renderStory(d){
  if (!P.story) return;
  const s = d && d.story;
  if (!s){ panelHTML("story", `<div class="dim" style="padding:8px">${d ? "The PS60 story starts with the first price." : NA}</div>`); return; }
  const c = s.ctx || {}, f = s.focus, fl = s.flow && f && f.approach ? s.flow.state : null;
  const tm = t => typeof nyHM12 === "function" ? nyHM12(t) : new Date(t * 1000).toLocaleTimeString();
  const chips = Object.keys(FLOW_CLS).map(k => `<b class="fst ${FLOW_CLS[k]}${k === fl ? " on" : ""}" title="${esc({"NOT YET CONFIRMED": "the PS60 setup is there, the option flow has not shown up yet", DEVELOPING: "option flow on the move's side is starting to show up", CONFIRMED: "option flow is materially behind the move", CONFLICTING: "option flow is against what the tape and price show"}[k])}">${k}</b>`).join("");
  const where = !f ? "nothing close" : f.on ? `at ${esc(f.name)}` : f.approach ? `approaching ${esc(f.name)} ($${(+f.d).toFixed(2)} away)` : `nearest: ${esc(f.name)}, $${(+f.d).toFixed(2)} away`;
  const list = (title, rows) => rows.length ? `<div class="sth">${title}</div>` + rows.join("") : "";
  const html = `<div class="sthead">
      <div class="sctx ${c.bias === "bull" ? "bull" : c.bias === "bear" ? "bear" : ""}"><b>${c.bias === "bull" ? "DAILY ▲ BULLISH PS60" : c.bias === "bear" ? "DAILY ▼ BEARISH PS60" : "DAILY"}</b> <span>${esc(c.text || "")}</span></div>
      <div class="satt">${s.attention ? `<b class="hat">HIGH ATTENTION</b>` : `<b class="watch">WATCHING</b>`} <span>${where}</span></div>
      <div class="snow t-${esc(s.tone || "neutral")}">${esc(s.now || "")}</div>
      ${s.play ? `<div class="splay"><b>PLAY-BY-PLAY</b> ${esc(s.play)}</div>` : ""}
      ${s.framework && s.framework.text ? `<div class="sfw"><b>THE AVERAGES</b> ${esc(s.framework.text)}</div>` : ""}
      ${s.framework && s.framework.text ? `<div class="sfw"><b>THE AVERAGES</b> ${esc(s.framework.text)}</div>` : ""}
      <div class="sflow">${chips}</div>
      ${s.response ? `<div class="sresp t-${esc(s.response.tone)}">PRICE RESPONSE · ${esc(s.response.text)}</div>` : ""}
      ${s.edge ? `<div class="sedge">${edgeChip(s.edge)}<div class="echecks">${s.edge.checks.map(c => `<span class="ec ${c.ok === true ? "y" : c.ok === 0.5 ? "h" : c.ok === false ? "n" : "u"}" title="${esc(c.why)}"><i></i>${esc(c.k)}<em>${esc(c.why)}</em></span>`).join("")}</div></div>` : ""}
    </div>
    <div class="sbody">
      ${s.layout ? `<div class="sth">THE MAP · supply above, demand below, the room between each</div><div class="smap">`
        + (s.layout.above || []).slice(0, 5).reverse().map(m => `<div class="srow s"><span>${esc(m.name)}</span><i>${px(m.near)}${m.far !== m.near ? "–" + px(m.far) : ""}</i><em>$${(+m.dollars).toFixed(2)} away · room $${(+m.room).toFixed(2)}</em></div>`).join("")
        + `<div class="srow now"><span>PRICE</span><i>${px(s.layout.last || 0) || ""}</i><em></em></div>`
        + (s.layout.below || []).slice(0, 5).map(m => `<div class="srow b"><span>${esc(m.name)}</span><i>${px(m.near)}${m.far !== m.near ? "–" + px(m.far) : ""}</i><em>$${(+m.dollars).toFixed(2)} away · room $${(+m.room).toFixed(2)}</em></div>`).join("")
        + `</div>` : ""}
      ${s.layout ? `<div class="sth">MEASURED POTENTIAL · supply above, demand below, the room between each</div><div class="smap">`
        + (s.layout.above || []).slice(0, 5).reverse().map(m => `<div class="srow s"><span>${esc(m.name)}</span><i>${px(m.near)}${m.far !== m.near ? "–" + px(m.far) : ""}</i><em>MP $${(+m.dollars).toFixed(2)} · room $${(+m.room).toFixed(2)}</em></div>`).join("")
        + `<div class="srow now"><span>PRICE</span><i>${s.layout.last != null ? px(s.layout.last) : ""}</i><em></em></div>`
        + (s.layout.below || []).slice(0, 5).map(m => `<div class="srow b"><span>${esc(m.name)}</span><i>${px(m.near)}${m.far !== m.near ? "–" + px(m.far) : ""}</i><em>MP $${(+m.dollars).toFixed(2)} · room $${(+m.room).toFixed(2)}</em></div>`).join("")
        + `</div>` : ""}
      ${list("CONFLUENCE", (s.confluence || []).map(x => `<div class="srow ${x.major ? "major" : ""}">${esc(x.text)}</div>`))}
      ${list("ZONES", (s.zones || []).map(z => `<div class="srow z-${z.user ? "user" : esc(z.kind)}">${esc(z.name)}</div>`))}
      ${list("RELOADS (★ = whole / half dollar)", (s.reloads || []).map(r => `<div class="srow ${r.side === "ask" ? "s" : "b"}">${r.side === "ask" ? "Seller" : "Buyer"} reloading ${Math.abs(r.price * 2 - Math.round(r.price * 2)) < 1e-6 ? "★ " : ""}${px(r.price)} · ${esc(r.stage || "")} · ${r.side === "ask" ? "buyers absorbed" : "sellers hit him for"} ${sz(r.absorbed)}</div>`))}
      <div class="sth">THE STORY</div>
      ${(s.feed || []).map(x => `<div class="sfeed t-${esc(x[2])}"><i>${tm(x[0])}</i>${esc(x[1])}</div>`).join("") || `<div class="dim" style="padding:4px 8px">Nothing yet.</div>`}
    </div>`;
  panelHTML("story", html);
}
function paceHTML(pc){
  if (!pc) return "";
  // SOMEBODY KNOWS SOMETHING stays up even on a quiet tape: the flow tag never disappears because the stock is slow
  const kn0 = pc.knows ? `<span class="pkn ${pc.knows.cp === "C" ? "c" : "p"}" title="SOMEBODY KNOWS SOMETHING: short-dated, out-of-the-money ${pc.knows.cp === "C" ? "calls" : "puts"} bought at the ask, again and again">⚡ ${esc(pc.knows.text)}</span>` : "";
  if (pc.state === "QUIET") return kn0 ? `<div class="pacebar s-warm">${kn0}</div>` : "";
  if (pc.state === "WARMING UP") return `<div class="pacebar s-warm" title="the pace reads this stock against its own last 20 minutes: a few minutes of tape first"><span class="pst">PACE · warming up</span>${kn0}</div>`;
  const st = pc.state, cls = {SURGE: "surge", FAST: "fast", NORMAL: "norm", SLOW: "slow", "DRYING UP": "dry"}[st] || "norm";
  const b = pc.buy_pct, acc = pc.accel === "SPEEDING UP" ? "▲" : pc.accel === "SLOWING" ? "▼" : "";
  const tip = `PACE OF TAPE: ${sz(pc.sps)} shares/s now vs ${sz(pc.norm_sps || 0)} normal (the median 15 s of the last 20 min) = ×${pc.ratio} · faster than ${pc.pct}% of the last 20 min${b != null ? ` · buyers ${b}% / sellers ${100 - b}% of the aggressive shares` : ""}${pc.accel ? " · " + pc.accel : ""}`;
  const kn = pc.knows ? `<span class="pkn ${pc.knows.cp === "C" ? "c" : "p"}" title="SOMEBODY KNOWS SOMETHING: short-dated, out-of-the-money ${pc.knows.cp === "C" ? "calls" : "puts"} bought at the ask, again and again">⚡ ${esc(pc.knows.text)}</span>` : "";
  let h = `<div class="pacebar s-${cls}" title="${esc(tip)}"><span class="pst">${st}</span><span class="pg"><i style="width:${Math.max(3, pc.pct || 0)}%"></i></span><span class="prt">×${pc.ratio}</span><span class="pacc">${acc}</span>${b != null ? `<span class="pbs" title="buyers ${b}% / sellers ${100 - b}%"><i class="b" style="width:${b}%"></i><i class="s" style="width:${100 - b}%"></i></span>` : ""}${kn}</div>`;
  if (pc.call && pc.level){
    const good = /WITH SPEED|PRESSING|SPEED \+ FLOW/.test(pc.call) && !/WITHOUT/.test(pc.call), warn = /STALLING|WITHOUT/.test(pc.call);
    const lvl = pc.call === "SPEED + FLOW" ? esc(pc.level[1]) : `${esc(pc.level[1])} ${px(pc.level[0])}`;
    h += `<div class="pcall ${good ? "good" : warn ? "warn" : ""}">${esc(pc.call)} · ${lvl}${pc.flow ? ` <b>${esc(pc.flow)}</b>` : ""}</div>`;
  }
  return h;
}
/* THE BASKET LADDER (LAYOUT: BASKET, an option next to CLEAN). DISPLAY ONLY: nothing here creates, stages or sends
   an order; the paper order entry is untouched.
     $ BID │ BID │ PRICE + BASKET │ ASK │ $ ASK
   money on the outside (size showing × price), shares next in, the price and its BASKET in the centre.
   BASKET: every row has one (no activity = an empty outline). FILL = shares absorbed at that price (the same number as
   the all-day "absorbed here" mark) against the price's normal volume today: full = heavy defense. A reload BUYER's
   basket opens upward, a reload SELLER's is mirrored (opens downward). Colour = the stoplight: AMBER size showing, not
   proven · GREEN RELOADING (real size) · RED flashing = FLIP · GRAY dashed = PULLED / CLEANED UP. GLOW = refill
   speed (refills in the last minute): it dims as the refills slow while the basket stays full. One quick PULSE per
   refill; a drop per print (buys from the ask side, sells from the bid side) — the numbers are the server's, counted
   first: an animation that is skipped never changes a number. FAST MODE (prints a second over the threshold): only
   the PS60 rows and your own level rows animate. SETTINGS > Level II (basket_*), or ⚙ on the ladder. */
function bkCfg(L){ return Object.assign({basket_drop_ms: 250, basket_merge_ms: 50, basket_max_drops: 12, basket_fast_pps: 25, basket_full_x: 3,
  basket_animate: true, basket_pulse: true, basket_glow: true, basket_flip_alerts: true, basket_touch_counter: true, basket_sequence: true,
  basket_manual_pop: true, norm: 0}, (L && L.basket) || {}); }
const BKROLE = {trigger: ["PIVOT", "trg"], second_entry: ["SECOND ENTRY", "se"], target: ["TAKE PROFIT", "tp"], stop: ["STOP", "sl"]};
function bkOwner(r){
  const tb = r.bid_state === "RELOAD" || r.bid_proven || r.bid_stage, ta = r.ask_state === "RELOAD" || r.ask_proven || r.ask_stage;
  if (tb && !ta) return "bid"; if (ta && !tb) return "ask";
  if (tb && ta) return (r.bid_abs || 0) >= (r.ask_abs || 0) ? "bid" : "ask";
  const b = r.bk; if (b && b[0]) return b[2] >= b[1] ? "bid" : "ask";           // sold into the bid = buyers absorbing
  return r.bid && !r.ask ? "bid" : r.ask && !r.bid ? "ask" : null;
}
function bkState(r, side, C){
  if (C.basket_flip_alerts && r.flip && ((r.flip === "seller") === (side === "ask"))) return "flip";
  const stg = r[side + "_stage"];
  if (stg === "PULLED" || stg === "CLEANED UP") return "gray";
  if (r[side + "_proven"] || stg === "RELOADING" || stg === "STILL THERE" || stg === "NOT RELOADING") return "green";
  return r.bk && r.bk[0] ? "amber" : "empty";                                    // no trades here yet: an empty outline
}
function ladderBasketHTML(L){
  const C = bkCfg(L), last = L.last != null ? +L.last : null, tk = +L.tick || 0.01;
  const big = +L.big_shares || 0, mx = Math.max(1, +L.max_size || 1, ...L.rows.map(r => Math.max(r.bid || 0, r.ask || 0)));
  const norm = Math.max(1, +C.norm || 0), full = Math.max(1, +C.basket_full_x || 3) * norm;
  const fast = C.basket_animate && L.pps != null && L.pps >= +C.basket_fast_pps;
  const seq = C.basket_sequence ? L.seq : null;
  const extreme = seq && seq.extreme != null && seq.step >= 2 ? +seq.extreme : null;
  const chips = (r, side) => (r.mine || []).filter(o => o.id != null && (o.action === "BUY") === (side === "b")).map(o =>
    `<span class="chip ${side} ${o.status === "PreSubmitted" ? "wait" : ""}" data-id="${o.id}" draggable="true" title="${esc(o.role)} order — click to cancel, drag to move">${sz(o.qty)}</span>`).join(" ");
  // the PS60 SEQUENCE: four steps, advancing on their own
  let h = "";
  if (seq){
    const names = ["WAITING AT PIVOT", "BROKE THROUGH", "PULLBACK TO PIVOT", "SECOND ENTRY"];
    const vcls = v => v === "RELOADING" ? "g" : v === "STILL THERE" ? "g2" : v === "NOT RELOADING" ? "a" : v ? "x" : "";
    h += `<div class="bkseq ${seq.side}" title="${esc(seq.note)}">${names.map((n, i) => { const k = i + 1, on = k === seq.step || (k === 4 && seq.lit4), done = k < seq.step;
      return `<span class="st ${on ? "on" : ""} ${done ? "done" : ""}"><b>${k}</b>${k === 2 ? (seq.side === "short" ? "BROKE · NEW LOW" : "BROKE · NEW HIGH") : n}${on && seq.verdict && (k === 1 || k === 3) ? ` <i class="vd ${vcls(seq.verdict)}">${esc(seq.verdict)}</i>` : ""}</span>`; }).join("")}<span class="sqn">${esc(seq.note)}</span></div>`;
  }
  // the FLIP banner
  const fl = C.basket_flip_alerts ? L.rows.filter(r => r.flip) : [];
  for (const r of fl) h += `<div class="bkflip">${px(r.price)} FLIP, ${r.flip === "seller" ? "seller losing, buyers taking over" : "buyer losing, sellers taking over"}</div>`;
  h += `<table class="lad clean basket2${fast ? " fast" : ""}" data-cols="ladb2"><tr>
    <th data-w="44" data-min="20" title="$ showing on the BID at this price (shares × price)">$ BID</th>
    <th class="szh" data-w="62" data-min="30" title="buyers waiting (shares). Gray = pulled. R = reload buyer. Click: BUY there">BID</th>
    <th class="pxh" data-w="160" data-min="110" title="PRICE and its BASKET: fill = shares absorbed here against this price's normal volume today · AMBER showing, not proven · GREEN RELOADING · RED flashing = FLIP · GRAY dashed = PULLED / CLEANED UP · a buyer's basket opens up, a seller's down">PRICE · BASKET${fast ? ` <i class="fastchip" title="FAST MODE: ${L.pps} prints a second. Only the PS60 rows and your levels animate; the numbers still update">FAST</i>` : ""}<button class="bkgear" data-bkgear="1" title="basket settings">⚙</button></th>
    <th class="szh" data-w="62" data-min="30" title="sellers waiting (shares). Gray = pulled. R = reload seller. Click: SELL there">ASK</th>
    <th data-w="44" data-min="20" title="$ showing on the ASK at this price (shares × price)">$ ASK</th></tr>`;
  for (const r of L.rows){
    const own = bkOwner(r), stt = own ? bkState(r, own, C) : (r.bk && r.bk[0] ? "amber" : "empty");
    const roles = (r.lv || []).map(m => m.role).filter(x => BKROLE[x]);
    const manual = C.basket_manual_pop && roles.some(x => x === "second_entry" || x === "target" || x === "stop");
    const ps60row = roles.includes("trigger") || roles.includes("second_entry");
    const isExt = extreme != null && Math.abs(r.price - extreme) < tk * 0.5;
    const flipSide = r.flip ? (r.flip === "seller" ? "ask" : "bid") : null;
    const pulled = side => { const ps = r["ps_" + (side === "bid" ? "b" : "a")]; return ps && ps[1] > ps[0] && ps[1] >= Math.max(1, big * 0.5) ? ps[1] : 0; };
    const pb = pulled("bid"), pa = pulled("ask");
    const rowGray = (r.bid_stage === "PULLED" || r.ask_stage === "PULLED") && !r.flip;
    const cls = ["bkrow", r.best_bid ? "best-bid" : "", r.best_ask ? "best-ask" : "", r.last ? "lastpx" : "", r.flip && C.basket_flip_alerts ? "flipr" : "", rowGray || pb || pa ? "pullr" : "",
      ...roles.map(x => "lvp-" + BKROLE[x][1]), manual ? "manual" : "", ps60row ? "ps60r" : "", isExt ? "newext" : "",
      (r.bid_state === "RELOAD" || r.bid_proven) ? "rl-bid" : "", (r.ask_state === "RELOAD" || r.ask_proven) ? "rl-ask" : ""].join(" ");
    const cash = side => { const n = r[side] || 0; return `<td class="mny ${side}">${n ? `<span>${usdK(n * r.price)}</span>` : ""}</td>`; };
    const size = side => {
      const n = r[side] || 0, stg = r[side + "_stage"], rl = r[side + "_state"] === "RELOAD" || r[side + "_proven"];
      const pg = side === "bid" ? pb : pa, w = n ? Math.max(6, Math.round(100 * n / mx)) : 0;
      const atLvl = (side === "bid" ? r.best_bid : r.best_ask) || (last != null && Math.abs(r.price - last) <= tk * 1.01);
      const live = rl && n > 0 && atLvl, hitting = live && ((side === "bid" ? r.u_s : r.u_b) || 0) > 0;
      const cl = ["sz", "click", side === "bid" ? "bsz" : "asz", pg ? "pulg" : "", flipSide === side ? "struck" : flipSide && flipSide !== side ? "bold" : "",
        rl ? "rl " + stageSlug(stg || "RELOADING") + (live ? " rl-live" : " rl-idle") + (hitting ? " rl-hit" : "") : ""].join(" ");
      const badge = rl ? `<span class="rlb" title="RELOAD ${side === "bid" ? "BUYER" : "SELLER"}: ${esc(stg || "RELOADING")}, refilled ${r[side + "_refills"] || 0} times">R${r[side + "_refills"] || ""}</span>` : "";
      const pgv = pg ? `<i class="pgv" title="${sz(pg)} shares PULLED from ${px(r.price)} without trading (last ${L.stack_seconds || 60}s)">−${kfmt(pg)}</i>` : "";
      const s_ = side === "bid" ? "b" : "s";
      return `<td class="${cl}" data-act="${side === "bid" ? "BUY" : "SELL"}" data-px="${r.price}"${szTitle(r, side)}>${w ? `<i class="pb" style="width:${w}%"></i>` : ""}${side === "bid" ? pgv + badge : ""}<span class="szn">${n ? kfmt(n) : ""}</span>${side === "ask" ? badge + pgv : ""}${chips(r, s_) ? `<span class="mine">${chips(r, s_)}</span>` : ""}</td>`; };
    // the basket
    const b = r.bk || [0, 0, 0, 0];
    const absorbed = own ? (r[own + "_abs"] != null ? r[own + "_abs"] : (own === "bid" ? b[2] : b[1])) : 0;
    const fill = absorbed ? Math.max(0.06, Math.min(1, absorbed / full)) : 0;
    const glow = C.basket_glow && stt === "green" ? Math.min(1, (r[own + "_rf"] || 0) / 4) : 0;
    const tip = `${own === "bid" ? "BUYER'S" : own === "ask" ? "SELLER'S" : ""} BASKET at ${px(r.price)}: ${sz(absorbed)} absorbed (full = ${sz(Math.round(full))}, ${(+C.basket_full_x || 3)}× this price's normal ${sz(norm)}) · ${sz(b[0])} traded here today (${sz(b[1])} bought, ${sz(b[2])} sold)` +
      (own && r[own + "_stage"] ? ` · ${r[own + "_stage"]}` : "") + (own && r[own + "_rf"] ? ` · ${r[own + "_rf"]} refills in the last minute` : "");
    const touch = C.basket_touch_counter && ps60row && ((r.vs || 0) + (r.vb || 0)) ? `<i class="tch" title="traded at this level since price last touched it (resets each touch)">·${kfmt((r.vs || 0) + (r.vb || 0))}</i>` : "";
    // the labels: PIVOT (with its verdict), NEW HIGH / NEW LOW, LAST, SECOND ENTRY, TAKE PROFIT, STOP, FLIP, PULLED
    const lab = [];
    if (roles.includes("trigger") && seq){ const v = seq.verdict; lab.push(`<b class="bl trg">PIVOT${v ? " · " + esc(v) : ""}</b>`); }
    else if (roles.includes("trigger")) lab.push(`<b class="bl trg">PIVOT</b>`);
    if (isExt) lab.push(`<b class="bl ext">${seq.side === "short" ? "NEW LOW" : "NEW HIGH"}</b>`);
    for (const x of ["second_entry", "target", "stop"]) if (roles.includes(x)) lab.push(`<b class="bl ${BKROLE[x][1]}">${BKROLE[x][0]}</b>`);
    if (r.flip && C.basket_flip_alerts) lab.push(`<b class="bl flp">FLIP</b>`);
    if (r.bid_stage === "PULLED" || r.ask_stage === "PULLED") lab.push(`<b class="bl pul">PULLED</b>`);
    if (r.last) lab.push(`<b class="bl lst">LAST</b>`);
    const basket = `<span class="bkt ${own === "ask" ? "dn" : "up"} bk-${stt}${glow ? " glw" : ""}" data-bk="${r.price}" style="--fill:${(fill * 100).toFixed(0)}%;--glow:${glow.toFixed(2)}" title="${esc(tip)}"><i class="bkfl"></i></span>`;
    const tot = b[0] ? `<i class="bkn">${kfmt(b[0])}</i>` : "";
    h += `<tr class="${cls}" data-price="${r.price}">${cash("bid")}${size("bid")}<td class="px bkpx"><span class="pxv">${px(r.price)}</span>${basket}${tot}${touch}${lab.length ? `<span class="bls">${lab.join("")}</span>` : ""}</td>${size("ask")}${cash("ask")}</tr>`;
  }
  h += `</table><div class="legend lgc"><span><b class="gold">AMBER</b> showing · <b class="buy">GREEN</b> RELOADING · <b class="sell">RED</b> FLIP · <b class="dim">GRAY</b> PULLED / CLEANED UP · basket opens up = buyer, down = seller</span><span class="dim">display only${fast ? " · FAST MODE" : ""}</span></div>`;
  return h;
}
/* THE BASKET's motion: after each draw, what is NEW since the last one. Counted first (the numbers on the rows are the
   server's), animated second: each price's new prints wait one merge window (basket_merge_ms) and drop in as ONE
   drop with ONE pulse (buys from the ask side, sells from the bid side); a new refill pulses the basket. Drops live
   in their own layer (CSS transforms, the Web Animations API), never more than basket_max_drops at once: anything
   beyond is counted, not animated, and the feed is never held up. FAST MODE: only the PS60 rows and your level rows
   animate; a PULLED change at a level row comes first. */
const BKSEEN = new Map(); let BKLIVE = 0; const BKQ = new Map(); let BKQT = null;
function basketFx(wrap, d){
  const L = d.ladder || {}, C = bkCfg(L), host = P.book.pc;
  if (store.get("ladMode", "clean") !== "basket") return;
  const sym = d.symbol, now = Date.now(), lastDraw = BKSEEN.get(sym + "|*"), fresh = !lastDraw || now - lastDraw > 3000;
  BKSEEN.set(sym + "|*", now);
  const fast = L.pps != null && L.pps >= +C.basket_fast_pps;
  for (const r of (L.rows || [])){
    const key = sym + "|" + r.price, b = r.bk || [0, 0, 0, 0];
    const roles = (r.lv || []).map(m => m.role);
    const lvRow = roles.some(x => x === "trigger" || x === "second_entry" || (C.basket_manual_pop && (x === "target" || x === "stop")));
    const cur = {tot: b[0], buy: b[1], sell: b[2], seq: b[3], rb: r.bid_rseq || 0, ra: r.ask_rseq || 0, pb: (r.ps_b || [0, 0])[1], pa: (r.ps_a || [0, 0])[1], t: now};
    const was = BKSEEN.get(key); BKSEEN.set(key, cur);
    if (fresh || !was || now - was.t > 3000) continue;                     // first sight, back on a ticker, scrolled in: no backlog
    if (fast && !lvRow) continue;                                          // FAST MODE: numbers only, except your levels and the PS60 rows
    const q = BKQ.get(key) || {sym, price: r.price, buy: 0, sell: 0, mid: 0, refill: 0, pulled: 0, lv: lvRow, t0: now};
    if (cur.seq > was.seq && cur.tot >= was.tot){
      const dB = Math.max(0, cur.buy - was.buy), dS = Math.max(0, cur.sell - was.sell);
      q.buy += dB; q.sell += dS; q.mid += Math.max(0, cur.tot - was.tot - dB - dS);
    }
    if (cur.rb > was.rb || cur.ra > was.ra) q.refill += 1;                    // one pulse per refill
    if (lvRow && (cur.pb > was.pb + 0 || cur.pa > was.pa + 0)) q.pulled += 1;   // a PULLED change at a level row comes first
    if (q.buy || q.sell || q.mid || q.refill || q.pulled) BKQ.set(key, q);
  }
  if (BKSEEN.size > 6000) for (const k of [...BKSEEN.keys()].slice(0, 3000)) if (!k.endsWith("|*")) BKSEEN.delete(k);
  if (BKQ.size && !BKQT) BKQT = setTimeout(() => { BKQT = null; requestAnimationFrame(() => bkFlush(wrap, d.symbol)); }, Math.max(0, +C.basket_merge_ms || 0));
}
function bkFlush(wrap, sym){
  const d = curData(); if (!d || d.symbol !== sym) { BKQ.clear(); return; }
  const L = d.ladder || {}, C = bkCfg(L), host = P.book.pc, items = [...BKQ.values()]; BKQ.clear();
  if (document.hidden || !wrap.isConnected || !wrap.offsetParent || !(C.basket_animate || C.basket_pulse)) return;
  let fx = host.querySelector(":scope > .bkfx"); if (!fx){ fx = document.createElement("div"); fx.className = "bkfx"; host.appendChild(fx); }
  const hr = host.getBoundingClientRect(), wr = wrap.getBoundingClientRect();
  const dur = Math.max(60, +C.basket_drop_ms || 250), pdur = Math.max(40, Math.round(dur * 0.6));
  // a PULLED change at a level row first, then your level rows, then the biggest
  items.sort((a, b) => (b.pulled ? 4 : 0) + (b.lv ? 2 : 0) - (a.pulled ? 4 : 0) - (a.lv ? 2 : 0) || (b.buy + b.sell + b.mid) - (a.buy + a.sell + a.mid));
  for (const q of items){
    const el0 = wrap.querySelector(`tr[data-price="${q.price}"] .bkt`); if (!el0) continue;
    const cr = el0.getBoundingClientRect(); if (cr.bottom < wr.top || cr.top > wr.bottom) continue;
    const x = cr.left - hr.left, y = cr.top - hr.top;
    const drops = [[q.sell, "s"], [q.buy, "b"], [q.mid, "m"]].filter(z => z[0] > 0);
    for (const [n, side] of drops){
      if (!C.basket_animate || BKLIVE >= Math.max(1, +C.basket_max_drops || 12)) break;     // beyond the cap: counted, not animated
      const el = document.createElement("i"); el.className = "bkdrop " + side; el.textContent = "+" + kfmt(n);
      el.style.left = (x - 6) + "px"; el.style.top = (y - 1) + "px"; fx.appendChild(el); BKLIVE++;
      const row = el0.closest("tr"), cell = row && row.querySelector(side === "s" ? "td.bsz" : side === "b" ? "td.asz" : "td.px");
      const cc = cell ? cell.getBoundingClientRect() : cr;
      const dx = side === "m" ? 0 : (cc.left + cc.width / 2) - (cr.left + cr.width / 2), dy = side === "m" ? -cr.height * 1.5 : -2;
      const a = el.animate([{transform: `translate(${dx}px,${dy}px)`, opacity: 0.2}, {opacity: 1, offset: 0.25}, {transform: "translate(0,0)", opacity: 0.9}], {duration: dur, easing: "cubic-bezier(.3,.8,.4,1)"});
      let done = false; const end = () => { if (done) return; done = true; el.remove(); BKLIVE = Math.max(0, BKLIVE - 1); };
      a.onfinish = a.oncancel = end; setTimeout(end, dur + 250);
    }
    if (C.basket_pulse){
      const kind = q.pulled ? "g" : el0.classList.contains("bk-flip") ? "r" : q.refill ? "rf" : drops.length ? (q.buy >= q.sell ? "b" : "s") : null;
      if (!kind) continue;
      const ring = document.createElement("i"); ring.className = "bkpulse " + kind;
      ring.style.left = (x - 2) + "px"; ring.style.top = (y - 2) + "px"; ring.style.width = (cr.width + 4) + "px"; ring.style.height = (cr.height + 4) + "px";
      fx.appendChild(ring);
      const a2 = ring.animate([{opacity: 0.95, transform: "scale(1)"}, {opacity: 0, transform: "scale(1.5)"}], {duration: pdur, delay: drops.length && C.basket_animate ? dur * 0.8 : 0, easing: "ease-out"});
      a2.onfinish = a2.oncancel = () => ring.remove(); setTimeout(() => ring.remove(), dur + pdur + 300);
    }
  }
}
/* ⚙ on the BASKET ladder: the same settings as SETTINGS > Level II, saved for every session */
function bkGearHTML(C){
  const tg = (k, t) => `<label><input type="checkbox" data-bkset="${k}" ${C[k] ? "checked" : ""}> ${t}</label>`;
  return `<div class="bkgpop"><div class="bkgt">BASKET LADDER <span class="x" data-bkgx="1">✕</span></div>
    <label class="rng">Animation <input type="range" min="80" max="1000" step="10" data-bkset="basket_drop_ms" value="${C.basket_drop_ms}"><i>${C.basket_drop_ms} ms</i></label>
    <label class="rng">Burst merge <input type="range" min="0" max="500" step="10" data-bkset="basket_merge_ms" value="${C.basket_merge_ms}"><i>${C.basket_merge_ms} ms</i></label>
    <label class="rng">Max drops <input type="range" min="1" max="40" step="1" data-bkset="basket_max_drops" value="${C.basket_max_drops}"><i>${C.basket_max_drops}</i></label>
    <label class="rng">Fast mode at <input type="range" min="2" max="200" step="1" data-bkset="basket_fast_pps" value="${C.basket_fast_pps}"><i>${C.basket_fast_pps} prints/s</i></label>
    ${tg("basket_animate", "Animations")}${tg("basket_pulse", "Pulse")}${tg("basket_glow", "Glow")}${tg("basket_flip_alerts", "Flip alerts")}${tg("basket_touch_counter", "Level-touch counter")}${tg("basket_sequence", "Sequence tracker")}${tg("basket_manual_pop", "Your level rows pop")}
    <div class="dim">display only · saved for every session</div></div>`;
}
document.addEventListener("click", e => {
  const g = e.target.closest("[data-bkgear]"), x = e.target.closest("[data-bkgx]");
  if (x){ const p = document.getElementById("bkgear"); if (p) p.remove(); return; }
  if (!g) return; e.stopPropagation();
  let p = document.getElementById("bkgear"); if (p){ p.remove(); return; }
  const d = curData(); if (!d) return;
  p = document.createElement("div"); p.id = "bkgear"; p.innerHTML = bkGearHTML(bkCfg(d.ladder));
  const r = g.getBoundingClientRect(); p.style.left = Math.max(8, Math.min(innerWidth - 270, r.left - 120)) + "px"; p.style.top = (r.bottom + 4) + "px";
  document.body.appendChild(p);
});
document.addEventListener("input", e => { const i = e.target.closest("#bkgear input[type=range]"); if (i) i.nextElementSibling.textContent = i.value + (i.dataset.bkset.endsWith("_ms") ? " ms" : i.dataset.bkset === "basket_fast_pps" ? " prints/s" : ""); });
document.addEventListener("change", async e => {
  const i = e.target.closest("#bkgear [data-bkset]"); if (!i) return;
  const k = i.dataset.bkset, v = i.type === "checkbox" ? i.checked : +i.value;
  const out = await post("/api/settings", {changes: {["ladder." + k]: v}});
  if (out && out.ok === false) toast("Not saved: " + (out.reason || ""), false);
  P.book.last = null; poll(true);
});
function ladderProHTML(L){
  const rows = L.rows; if (!rows.length) return `<div class="empty">Waiting for the book…</div>`;
  const ms = Math.max(L.max_traded, 1), big = L.big_shares || 5000;
  const vmax = Math.max(1, ...rows.map(r => Math.max(r.vs || 0, r.vb || 0)));
  const chips = (r, side) => (r.mine || []).filter(o => o.id != null && (o.action === "BUY") === (side === "b")).map(o =>
    `<span class="chip ${side} ${o.status === "PreSubmitted" ? "wait" : ""}" data-id="${o.id}" draggable="true" title="${esc(o.role)} order — click to cancel, drag to move">${sz(o.qty)}</span>`).join(" ");
  const mark = (r, cp) => { const f = r.flow; if (!f) return ""; const sum = cp === "C" ? f.c : f.p; if (!sum) return ""; const items = f.items.filter(m => m.cp === cp); const urg = f.urgent && items.some(m => m.urgent !== false);
    return `<i class="fmk ${cp === "C" ? "c" : "p"} ${urg ? "hot" : ""} ${sum >= 1e6 ? "big" : ""}" title="${esc(flowTitle(Object.assign({}, f, {items})))}"></i>`; };
  const stack = (r, side) => { const ps = r["ps_" + (side === "bid" ? "b" : "a")]; if (!ps) return `<td class="stk ${side}"></td>`;
    const [add, pull] = ps, net = add - pull, who = side === "bid" ? "BUYERS" : "SELLERS";
    const up = add >= big * 0.5 && add > pull * 1.5, dn = pull >= big * 0.5 && pull > add * 1.5;
    // clean: only size that matters shows (a fifth of BIG or more), the rest is noise until it adds up
    if (Math.max(add, pull) < big * 0.2) return `<td class="stk ${side}"></td>`;
    const txt = Math.abs(net) < big * 0.2 ? "" : (net > 0 ? "+" : "−") + kfmt(Math.abs(net));
    const tip = `last ${L.stack_seconds || 60}s at ${px(r.price)}: ${sz(add)} shares ADDED to the ${side} (${who.toLowerCase()} stepping up), ${sz(pull)} PULLED without trading` + (up ? ` — ${who} STEPPING UP` : dn ? ` — ${who} PULLING` : "");
    return `<td class="stk ${side} ${net > 0 ? "add" : "pull"} ${up ? "lit" : dn ? "litp" : ""}" title="${esc(tip)}">${txt}</td>`; };
  const visit = (r, side) => { const v = side === "bid" ? (r.vs || 0) : (r.vb || 0); if (!v) return `<td class="vis ${side}"></td>`;
    const w = Math.round(100 * v / vmax), word = side === "bid" ? "SOLD into the bid" : "BOUGHT from the ask";
    return `<td class="vis ${side} ${r.vopen ? "open" : "past"}" title="${esc(`${sz(v)} shares ${word} at ${px(r.price)} ${r.vopen ? "this visit (price is here now)" : "on the last visit"} = ${usdK(v * r.price)}${r.vn > 1 ? ` · price has been back here ${r.vn} times in ${L.memory_minutes} min` : ""}`)}"><span class="vb" style="width:${w}%"></span><b>${kfmt(v)}</b></td>`; };
  let h = "";
  // the strips: what sits above and below the rows (your lines, the strikes, the reloaders), nearest first
  const top = +rows[0].price, bot = +rows[rows.length - 1].price;
  const off = (L.marks || []).filter(m => m.price > top || m.price < bot);
  const up = off.filter(m => m.price > top).sort((a, b) => a.price - b.price).slice(0, 4);
  const dn = off.filter(m => m.price < bot).sort((a, b) => b.price - a.price).slice(0, 4);
  const pill = (m, arrow) => `<span class="lvp ${lvCls(m)}" title="${esc(lvWords(m) + " " + px(m.price) + " · " + distTxt(m.dist, L.tick) + " from the last price")}">${arrow} ${esc(lvWords(m, true))} ${px(m.price)} <i>${distTxt(m.dist, L.tick)}</i></span>`;
  if (store.get("storyline", true)) h += storyLineHTML(L.story);
  h += refsHTML(L.refs, L.story && L.story.edge);
  h += paceHTML(L.pace);
  h += `<div class="lvstrip top">${up.map(m => pill(m, "▲")).join("")}${dn.map(m => pill(m, "▼")).join("")}${up.length || dn.length ? "" : `<span class="dim">your lines off the ladder show here</span>`}<span class="sp"></span><button data-lclr="above" title="clear SOLD / BOUGHT / +/− above the ask (after a move down)">CLR ▲</button><button data-lclr="below" title="clear SOLD / BOUGHT / +/− below the bid (after a move up)">CLR ▼</button></div>`;
  h += `<table class="lad lad3 pro" data-cols="ladpro"><tr>
    <th class="lvh" data-w="64" data-min="26" title="your chart on the ladder: PIVOT, 2ND ENTRY, TARGET, STOP, SNEAKY PIVOT, option STRIKES getting the money, high / low of day, the RELOAD buyer / seller — and how far they are">LEVEL</th>
    <th class="stkh" data-w="40" data-min="16" title="+/− on the BID: + size ADDED (buyers stepping up), − size PULLED without trading, last ${L.stack_seconds || 60}s. Lit = big">+/−</th>
    <th class="vish" data-w="44" data-min="18" title="SOLD this visit: shares that hit the bid at this price since price came back here">SOLD</th>
    <th class="szh" data-w="54" data-min="20" title="BID: resting buy orders. Drains as it gets hit. Solid green ↻N = the RELOAD BUYER refilling. Click to BUY there">BID</th>
    <th class="pxh" data-w="58" data-min="26">PRICE</th>
    <th class="szh" data-w="54" data-min="20" title="ASK: resting sell orders. Drains as it gets lifted. Solid red ↻N = the RELOAD SELLER refilling. Click to SELL there">ASK</th>
    <th class="vish" data-w="44" data-min="18" title="BOUGHT this visit: shares that lifted the ask at this price since price came back here">BOUGHT</th>
    <th class="stkh" data-w="40" data-min="16" title="+/− on the ASK: + size ADDED (sellers stepping up), − size PULLED without trading, last ${L.stack_seconds || 60}s. Lit = big">+/−</th></tr>`;
  for (const r of rows){
    const pb = r.bid_state === "RELOAD" || r.bid_proven, pa = r.ask_state === "RELOAD" || r.ask_proven;
    const stg = pb ? (r.bid_stage || "RELOADING") : pa ? (r.ask_stage || "RELOADING") : "";
    const cv = pb ? (r.bid_conv == null ? 1 : r.bid_conv) : pa ? (r.ask_conv == null ? 1 : r.ask_conv) : 1;
    const lv = (r.lv || []).filter(m => !(m.role === "reload_bid" || m.role === "reload_ask")).sort((a, b) => (LVRANK[a.role] ?? 9) - (LVRANK[b.role] ?? 9));
    const rel = pb ? "BUYER ↻" + (r.bid_refills || "") : pa ? "SELLER ↻" + (r.ask_refills || "") : "";
    const at = r.last && lv.length;
    const cls = [r.gap ? "gap" : "", r.best_bid ? "best-bid" : "", r.best_ask ? "best-ask" : "", r.last ? "lastpx" : "", pb ? "rl-bid" : "", pa ? "rl-ask" : "",
      stg ? "cv-" + stageSlug(stg) : "", lv.length ? "lvrow lv-" + lvCls(lv[0]) : "", at ? "atlv" : "", lv.some(m => m.alt) ? "lvalt" : "",
      // the VWAP and the daily 50-day row GLOW, whatever else sits on it
      lv.some(m => m.role === "vwap") ? "g-vw" : "", lv.some(m => m.role === "sma50") ? "g-d50" : ""].join(" ");
    const rb = pb ? reloadMoney(r, "bid") : null, ra = pa ? reloadMoney(r, "ask") : null;
    const goneB = !pb && /CLEANED UP|PULLED/.test(r.bid_stage || "") ? `<span class="gone">${r.bid_stage === "PULLED" ? "PULLED" : "CLEANED"}</span>` : "";
    const goneA = !pa && /CLEANED UP|PULLED/.test(r.ask_stage || "") ? `<span class="gone">${r.ask_stage === "PULLED" ? "PULLED" : "CLEANED"}</span>` : "";
    const fakeB = r.bid_real && r.bid_real.label === "FAKE" ? " fake" : "", fakeA = r.ask_real && r.ask_real.label === "FAKE" ? " fake" : "";
    const bigB = r.bid_big ? (r.bid_big.huge ? " huge" : " big") : "", bigA = r.ask_big ? (r.ask_big.huge ? " huge" : " big") : "";
    const absB = r.sold && r.sold / ms >= 0.15 ? Math.round(100 * r.sold / ms) : 0, absA = r.bought && r.bought / ms >= 0.15 ? Math.round(100 * r.bought / ms) : 0;
    const tB = rb ? rb.text : [r.bid ? sz(r.bid) + " showing" : "", r.sold ? sz(r.sold) + " sold into this price in " + L.memory_minutes + " min = " + usdK(r.sold * r.price) : "", r.bid_real ? realWords(r.bid_real) : ""].filter(Boolean).join(" · ");
    const tA = ra ? ra.text : [r.ask ? sz(r.ask) + " showing" : "", r.bought ? sz(r.bought) + " bought from this price in " + L.memory_minutes + " min = " + usdK(r.bought * r.price) : "", r.ask_real ? realWords(r.ask_real) : ""].filter(Boolean).join(" · ");
    // the LEVEL cell: your line first, then the reloader sitting on it ("RELOAD SELLER AT YOUR 2ND ENTRY" is the whole read)
    const lvTxt = lv.length ? (at ? "AT " : "") + lvWords(lv[0], true) + (lv.length > 1 ? ` +${lv.length - 1}` : "") : "";
    const lvTip = lv.map(m => lvWords(m) + " " + px(m.price) + (m.role === "sneaky_auto" ? ` (TED found it: ${m.touches || "?"} touches, room $${(m.room || 0).toFixed(2)})` : "")).join(" · ") + (rel ? (lv.length ? " · " : "") + (pb ? rb.text : ra.text) : "");
    const lvCell = `<td class="lvc" title="${esc(lvTip)}">${lvTxt ? `<b>${esc(lvTxt)}</b>` : ""}${rel ? `<span class="rlv ${pb ? "b" : "s"}">${lv.length ? "◆ " : ""}${esc(rel)}</span>` : ""}</td>`;
    // the last-price row glows harder the faster the tape runs: green when buyers push, red when sellers do
    const glow = r.last && L.pace && L.pace.heat ? `;--heat:${L.pace.heat}` : "", gcls = glow ? (L.pace.buy_pct != null && L.pace.buy_pct < 50 ? " pglow s" : " pglow b") : "";
    h += `<tr class="${cls}${gcls}" data-price="${r.price}" style="--cv:${cv}${glow}">${lvCell}${stack(r, "bid")}${visit(r, "bid")}
      <td class="sz bsz click${fakeB}${bigB}" data-act="BUY" data-px="${r.price}" title="${esc(tB)}">${mark(r, "C")}${goneB}${absB ? `<span class="abs" style="width:${absB}%"></span>` : ""}${pb ? `<span class="rl${r.bid_back ? " back" : ""}">${r.bid_back ? "↩×" + r.bid_back.n + " " : ""}↻${r.bid_refills || ""}${rb && rb.usd ? `<i class="rlm"> ${usdK(rb.usd)}</i>` : ""}</span>` : ""}<span class="szn">${r.bid ? kfmt(r.bid) : ""}</span>${chips(r, "b") ? `<span class="mine">${chips(r, "b")}</span>` : ""}</td>
      <td class="px">${px(r.price)}${r.vn > 1 ? `<sup title="price has been back to ${px(r.price)} ${r.vn} times in ${L.memory_minutes} min">×${r.vn}</sup>` : ""}</td>
      <td class="sz asz click${fakeA}${bigA}" data-act="SELL" data-px="${r.price}" title="${esc(tA)}"><span class="szn">${r.ask ? kfmt(r.ask) : ""}</span>${chips(r, "s") ? `<span class="mine">${chips(r, "s")}</span>` : ""}${pa ? `<span class="rl${r.ask_back ? " back" : ""}">${ra && ra.usd ? `<i class="rlm">${usdK(ra.usd)} </i>` : ""}↻${r.ask_refills || ""}${r.ask_back ? " ↩×" + r.ask_back.n : ""}</span>` : ""}${goneA}${absA ? `<span class="abs" style="width:${absA}%"></span>` : ""}${mark(r, "P")}</td>
      ${visit(r, "ask")}${stack(r, "ask")}</tr>`;
  }
  h += `</table>`;
  return h;
}
document.addEventListener("click", async e => {
  const b = e.target.closest("button[data-lclr]"); if (!b) return;
  const host = b.closest(".pnl"), opt = host && /obook|otape/.test(host.dataset.p || "") || b.closest(".cbook");
  if (opt){ OPTCLR[OCH.key + "|" + b.dataset.lclr] = Date.now() / 1000; P.book.last = null; renderOptPanels && renderOptPanels(); return; }
  const out = await post("/api/ladder/clear", {symbol: curSym, where: b.dataset.lclr});
  toast(out.ok ? `Ladder cleared ${b.dataset.lclr === "above" ? "above the ask" : "below the bid"}` : "Nothing to clear", out.ok); P.book.last = null; poll(true);
});
const OPTCLR = {};

/* TRADING THE OPTION, READING THE STOCK: on the stock chart, every contract you hold on this ticker — how many, the P&L,
   and what it should be worth when the stock gets to your TARGET (your measured potential) and to your STOP (today's
   delta: ≈ mid + Δ × the stock's move) */
function renderOptPos(d){
  const el = document.getElementById("optPosStrip"); if (!el) return;
  const ps = (((state || {}).account || {}).opt_positions || []).filter(p => p.symbol === d.symbol && p.qty);
  const pl = d.play || {}, spot = d.last;
  const h = ps.map(p => {
    const long = p.qty > 0, q = Math.abs(p.qty), mult = p.mult || 100, mid = p.bid != null && p.ask != null ? (p.bid + p.ask) / 2 : (p.bid ?? p.ask);
    const lines = (p.right === "C") === ((pl.side || "long") === "long") ? pl : (pl.alt || {});
    const at = (lvl, word, cls) => { if (!lvl || mid == null || p.delta == null || !spot) return "";
      const est = Math.max(0.01, mid + p.delta * (lvl - spot)), pnl = (est - p.per_contract) * mult * p.qty;
      return `<span class="${cls}" title="when ${esc(d.symbol)} trades ${px(lvl)} the contract should be about ${est.toFixed(2)} (today's delta ${(+p.delta).toFixed(2)})">${word} ${px(lvl)} ≈ ${est.toFixed(2)} <b>${pnl >= 0 ? "+" : "−"}$${sz(Math.abs(Math.round(pnl)))}</b></span>`; };
    const os = (T().opt_stops || {})[p.key];
    return `<div class="op"><b class="${long ? "b" : "s"}">◆ ${long ? "LONG" : "SHORT"} ${q} ${esc(p.label)}</b><span>paid ${(+p.per_contract).toFixed(2)} · now ${mid != null ? mid.toFixed(2) : "—"}</span>${p.pnl != null ? `<b class="${p.pnl >= 0 ? "b" : "s"}">${p.pnl >= 0 ? "+" : "−"}$${sz(Math.abs(Math.round(p.pnl)))}</b>` : ""}
      ${at(lines.target, "TARGET", "tg")}${at(lines.stop, "STOP", "sl")}${!lines.stop && os ? `<span class="sl">STOP ${os.on === "stock" ? esc(d.symbol) + " " : "contract "}${(+os.price).toFixed(2)}</span>` : ""}</div>`; }).join("");
  if (el.dataset.h !== h){ el.dataset.h = h; el.innerHTML = h; }
}

/* the ladder fills its panel: as many rows as the window holds (8 to 40 a side), asked again when you resize. A row
   count you picked in COLS (Rows) wins: store "ladRowsAuto" off */
let ladFitT = 0;
function fitLadderRows(wrap){
  if (!store.get("ladRowsAuto", true) || !wrap || wrap.offsetParent === null || Date.now() - ladFitT < 3000) return;
  const tr = wrap.querySelector("table.lad tr[data-price]"); if (!tr) return;
  const rh = tr.getBoundingClientRect().height || 15, strip = wrap.querySelector(".lvstrip"), head = wrap.querySelector("table.lad tr:first-child");
  const avail = wrap.clientHeight - (strip ? strip.offsetHeight : 0) - (head ? head.offsetHeight : 0) - 6;
  const want = Math.max(8, Math.min(40, Math.floor(avail / rh / 2)));
  const have = (state && state.ladder_half_rows) || store.get("ladRows", 12);
  if (Math.abs(want - have) >= 1){ ladFitT = Date.now(); store.set("ladRows", want); post("/api/ladder", {half_rows: want}); P.book.last = null; }
}
window.addEventListener("resize", () => { ladFitT = 0; });
/* the dots row under the order bar: click it and the CONVICTION panel opens with every check spelled out
   (hover one dot for just that check) */
{ const cv = document.getElementById("cvStrip");
  if (cv){ cv.style.cursor = "pointer"; cv.title = "the 8 PS60 checks, left to right: DAILY MP · PIVOT · CONFIRM · 2ND ENTRY · BUILD · FLOW SIDE · FLOW QUALITY · CORRELATION. Green = met, yellow = getting there, red = not yet. Hover a dot for that check; click for the CONVICTION panel with all of them.";
    cv.addEventListener("click", () => { if (typeof showPanel === "function") showPanel("conviction"); }); } }
