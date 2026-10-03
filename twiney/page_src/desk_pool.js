/* ===================== TED — TWINEY EXECUTION DESK: panel pool ===================== */
const PANELS = {
  chart: "CHART", foot: "FOOTPRINT 5m", book: "LEVEL II", tape: "TIME & SALES", bigtape: "BIG TAPE", options: "OPTION CHAIN", setup: "PLAY SETUP", ps60: "PS60", conviction: "CONVICTION", reload: "RELOADS",
  ticket: "ORDER ENTRY", positions: "POSITIONS", orders: "ORDERS", watch: "WATCHLIST", calls: "CALLS",
  flow: "OPTION FLOW", eqflow: "EQUITY FLOW", urgency: "URGENT FLOW", bigmoney: "BIG MONEY 30D", myalerts: "ALERTS", desk: "DESK", journal: "JOURNAL", messages: "MESSAGES"};
const SYMBOL_LINKED = new Set(["chart", "foot", "book", "tape", "bigtape", "options", "ps60", "reload", "ticket", "calls", "setup", "bigmoney", "conviction"]);
const ZONES = ["TL", "TC", "TR", "TX", "BL", "BC", "BR", "BX"];   // four columns × two rows; a column with one zone runs full height
const PRESETS = {
  "PS60 Execution": {zones: {TL: ["watch", "myalerts"], TC: ["chart"], TR: ["book"], TX: ["tape"], BL: ["positions", "orders"], BC: ["conviction", "setup", "flow", "urgency", "bigmoney", "eqflow", "ps60", "reload", "calls"], BR: ["ticket"]},
    active: {BL: "positions", BC: "setup"}, sizes: {c1: 200, c3: 330, c4: 290, r2: {L: 250, C: 330, R: 430, X: 250}}},
  "Scalping": {zones: {TL: ["ticket", "setup"], TC: ["book"], TR: ["tape"], BL: ["positions"], BC: ["chart"], BR: ["orders", "reload"]},
    active: {BR: "reload"}, sizes: {c1: 300, c3: 320, r2: 300}},
  "Tape Focus": {zones: {TL: ["book"], TC: ["tape"], TR: ["reload", "ps60", "setup"], BL: ["ticket"], BC: ["chart"], BR: ["positions", "orders"]},
    active: {TR: "reload"}, sizes: {c1: 380, c3: 380, r2: 260}},
  "Chart Focus": {zones: {TL: [], TC: ["chart"], TR: ["book"], TX: ["tape"], BL: [], BC: ["foot"], BR: ["ticket"], BX: ["setup", "ps60", "reload", "flow", "positions", "orders"]},
    active: {BX: "setup"}, sizes: {c1: 0, c3: 330, c4: 300, r2: 220}},
  "Laptop": {zones: {TL: [], TC: ["chart", "foot", "ps60"], TR: ["book", "tape", "ticket", "reload"], BL: [], BC: ["positions", "orders", "calls", "watch", "desk", "journal", "messages"], BR: []},
    active: {}, sizes: {c1: 0, c3: 360, r2: 180}},
};
let LAY = null, layoutName = null, LAYOUTS = {}, PREFS = {};
const P = {};                       // panel id -> {id, el, pc, ...}
let curSym = null, focusedPane = null;
const TABS = {list: [], active: null};
const VIEWS = {};                   // symbol -> {chart: view, foot: view} so each tab keeps its zoom
/* ---------- panels: build once, keep in a hidden pool, move between zones */
const pool = document.createElement("div"); pool.style.display = "none"; document.body.appendChild(pool);
for (const el of document.getElementById("tplPanels").content.querySelectorAll(".pnl")){
  const id = el.dataset.p; const node = el.cloneNode(true); pool.appendChild(node);
  P[id] = {id, el: node, pc: node.querySelector(".pc"), title: PANELS[id], last: null};
}
