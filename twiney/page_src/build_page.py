"""Builds twiney/static/dashboard.html from the pieces in this folder. Edit the pieces, never the built page:
    python page_src/build_page.py
then hard-refresh the desk (Ctrl+F5)."""
import os
SP = os.path.dirname(os.path.abspath(__file__))
old = open(SP + "/dashboard_old.html").read().split("\n")
def L(a, b): return "\n".join(old[a - 1:b - 1])
def find(prefix, start=1):
    for i in range(start - 1, len(old)):
        if old[i].startswith(prefix): return i + 1
    raise KeyError(prefix)
css = L(find("<style>") + 1, find("</style>"))
helpers = L(find("<script>") + 1, find("/* ---------- windows:"))
wire = L(find("function wireChart("), find("// ---------- chart trading"))
trading = L(find("// ---------- chart trading"), find("function drawChart("))
drawone = L(find("function drawOne("), find("function render(s){"))
voice = L(find("// ---------- voice:"), find("function onScreenSymbols"))
desk = L(find("// ---------- the desk"), find('document.getElementById("rpPlay")'))
replay_btns = L(find('document.getElementById("rpPlay")'), find("// hotkeys"))
# volume from the slider; desk block must not re-bind the command-bar buttons we bind ourselves
voice = voice.replace("u.rate = 1.1; u.pitch = 1; u.volume = 1;", "u.rate = 1.05; u.pitch = 1; u.volume = store.get(\"voiceVol\", 1);")
for line in ['document.getElementById("recBtn").addEventListener("click", deskRec);', 'document.getElementById("markBtn").addEventListener("click", () => deskMark());', 'document.getElementById("shotBtn").addEventListener("click", deskShot);']:
    desk = desk.replace(line, "")
head = "\n".join(old[:find("<style>") - 1]).replace("<title>TWINEY</title>", "<title>TED · Twiney Execution Desk</title>\n<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link href=\"https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap\" rel=\"stylesheet\">")
html = (head + "\n<style>\n" + css + open(SP + "/desk.css").read() + open(SP + "/skin.css").read() + "\n</style>\n</head>\n<body>" + open(SP + "/desk_body.html").read()
        + "\n<script>\n" + "\n".join([helpers, open(SP + "/desk_pool.js").read(), wire, trading, drawone, voice, desk, replay_btns,
                                       open(SP + "/desk_core.js").read(), open(SP + "/desk_panels.js").read(), open(SP + "/desk_boot.js").read()])
        + "\n</script>\n</body>\n</html>\n")
# palette: retint every hard-coded colour (chart canvas, old css) to the graphite skin
PAL = {"#26d07c":"#3fb56f","#ff4d5e":"#d9534f","#ffc53d":"#e3a83a","#3fd0ff":"#5aa9d6","#b58cff":"#a48bd6","#0a0d12":"#0c0c0d","#7b889e":"#7d7f85",
  "#dbe3ee":"#d6d6d3","#1b2433":"#1f2023","#2a3548":"#2c2e33","#243044":"#26282c","#e8a0ff":"#b48ed6","#ff9f43":"#d58a3a","#7bed9f":"#6fcf97",
  "#9fffcf":"#9fe0bd","#ffb3bb":"#e8a3a3","#e8eef8":"#e6e6e3","#0f3d25":"#173b28","#4a161b":"#3d1c1c","#05070b":"#0a0a0b","#11161f":"#131416",
  "#161d29":"#1a1b1e","#0b0f15":"#0e0f11","#0d121a":"#101113","#0f141c":"#121315","#070a0f":"#09090a","#131923":"#1c1d20","#1a2230":"#1f2024",
  "#141b26":"#1a1b1e","#3b3410":"#4a3a18","#4a5566":"#5b5d63","#9aa7bb":"#8e9096","#0a0e15":"#0e0f11","#2a2410":"#3a2e12","#ffeeb0":"#f2d59a",
  "#dfffee":"#dff5e8","#ffe3e6":"#f5dede","#163a28":"#173b28","#3a1a1e":"#3d1c1c","#c4cddb":"#b8b8b4","#b9c3d3":"#b0b0ad","255,197,61":"227,168,58"}
import re
html = re.sub("|".join(re.escape(k) for k in PAL), lambda m: PAL[m.group(0).lower()] if m.group(0).lower() in PAL else PAL[m.group(0)], html, flags=re.I)
html = html.replace("Chart builds as trades come in…", "NO BARS YET").replace("`◀ ${off} bars back — double-click to go live`", "`${off} BARS BACK · DOUBLE-CLICK FOR LIVE`")
html = html.replace("● green = buyer absorbing   ● red = seller absorbing   R/C/P = reload / cleaned / pulled", "GREEN BUYER ABSORBING · RED SELLER ABSORBING · R/C/P RELOAD / CLEANED / PULLED")
for a, b in [('${g.ok ? "✅" : "❌"}', '<i class="gate ${g.ok ? "ok" : "no"}"></i>'), ('"● REC " + fmtDur', '"REC " + fmtDur'), (': "● REC";', ': "REC";'),
             ('title="open the screenshot">📷</a>', 'title="open the screenshot">SNAP</a>'), ('>▶ Replay</button>', '>REPLAY</button>'), ('>⬇ Export this session so far</a', '>EXPORT THIS SESSION</a'),
             ('"2ND ENTRY ✓ "', '"2ND ENTRY IN "'), ('px(p.dragOrder.price) + " ▸"', 'px(p.dragOrder.price) + " >"'), ('🗑', 'DELETE'), ('content:"▶"', 'content:">"'),
             ('` ⚠ PS60 says PASS: ${g.why}.`', '` · PS60 PASS: ${g.why}.`'), ('` · PS60: WATCH — ${g.why}.`', '` · PS60 WATCH: ${g.why}.`'),
             ('<span style="color:var(--gold)">◆</span>', '<span style="color:var(--gold);font-size:9px;letter-spacing:.1em">L2</span>')]:
    html = html.replace(a, b)
# THE SIGN-IN: any answer of 401 (signed out, the session ran out, the password changed) goes to the sign-in page
GUARD = ('<script>(function(){const f=window.fetch.bind(window);window.fetch=async function(){const r=await f.apply(null,arguments);'
         'if(r.status===401&&!window._tedOut){window._tedOut=1;location.replace("/login?next="+encodeURIComponent(location.pathname));}return r;};})();</script>\n')
html = html.replace("<style>", GUARD + "<style>", 1)
import subprocess, datetime
build = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M")
html = html.replace("<title>", f'<meta name="build" content="{build}">\n<title>', 1)
open(os.path.join(SP, "..", "twiney", "static", "dashboard.html"), "w", encoding="utf-8").write(html)
print("written", len(html))
# the MARKET ANALYSIS DETAILED REPORT page: its own page (the MARKET button), same build stamp
mk = open(os.path.join(SP, "market.html"), encoding="utf-8").read().replace("<title>", f'<meta name="build" content="{build}">\n<title>', 1)
mk = mk.replace("</head>", GUARD + "</head>", 1)
open(os.path.join(SP, "..", "twiney", "static", "market.html"), "w", encoding="utf-8").write(mk)
print("written market", len(mk), "build", build)
# THE SHOW page (the broadcast screen, /show): its own page, same build stamp
sh = open(os.path.join(SP, "show.html"), encoding="utf-8").read().replace("<title>", f'<meta name="build" content="{build}">\n<title>', 1)
# the SHOW chart draws your studies and moving averages with the DESK's own code, copied in here at build time, so the
# two can never look different
_core, _old = open(SP + "/desk_core.js", encoding="utf-8").read(), "\n".join(old)
def _fn(src, name):
    # the whole function, braces matched (strings and template literals in these never hold an unmatched brace)
    i = src.index(f"function {name}("); j = src.index("{", i); depth = 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise ValueError(name)
_desk = "\n".join(_fn(_core, n) for n in ("stX", "studyLineList", "stDash", "studyStyle", "studiesBack", "studiesFront", "studiesTags"))
_desk += "\n" + "\n".join(l for l in old if l.startswith(("const DAN_SMA", "const DAN_EMA", "const DAN_BB", "function smaSeries(", "function emaSeries(", "function bbSeries(")))
assert "/*@DESK_CHART@*/" in sh
sh = sh.replace("/*@DESK_CHART@*/", _desk)
open(os.path.join(SP, "..", "twiney", "static", "show.html"), "w", encoding="utf-8").write(sh)
print("written show", len(sh))
