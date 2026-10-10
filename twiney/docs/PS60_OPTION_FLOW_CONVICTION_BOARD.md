# PS60 Option Flow Conviction Board — Bot Source of Truth

**Audience:** Antoine platform / Claude Cole (bot-ready)  
**Authority:** Dan Shapiro / Access A Trader — YouTube option-flow timing videos (listed below) + locked local notes (handoff §11, V3/V4 notes, cheatsheets).  
**Rule:** Do not invent. Every timing/conviction rule cites a video id and/or a local note. Flow **supports** a PS60 pivot thesis; it never replaces Daily room → pivot → confirm → second entry → build → MP.

**Caption status (2026-10-01 ET):** `yt-dlp --write-auto-sub --write-sub --skip-download --sub-lang en` found English auto-captions for all 12 ids but **timedtext download returned HTTP 429** from this host. Fallback: android-client media download → 16 kHz mono wav → `faster-whisper small.en` ASR. Artifacts under `/workspace/ps60/docs/option-flow-vids/{id}.en.{txt,srt,json}` + `{id}.transcript.meta.json`.

---

## 0. Video inventory

| Video id | Title (from yt-dlp info.json) | Duration | Transcript |
|---|---|---|---|
| HvDqcAem4KM | Option Flow Has These Major Stock Names On Watch! \| PS60 Process | ~13:29 | OK (ASR) |
| ysshM1blOFA | Option Flow Understanding For Better Equity Trades \| PS60 Methodology | ~16:08 | OK (ASR) |
| URaAZxC23YU | Why I Use An Options Scanner For Equity Trading | ~17:12 | OK (ASR) |
| t67SFwBMcys | Improve Your Trading Edge By Using Institutional Options Flow \| Day Trading Strategies | ~18:41 | OK (ASR) |
| 8wLDi6jdgIw | Focus On The Whole Picture #trading #shorts #stockmarket | ~0:37 | OK (ASR; **no OF timing content**) |
| pho_podj1Ig | You Must Follow The Option Flow To Level Up Your Trading \| NVDA's Massive Move… | ~16:14 | OK (ASR) |
| Z02b30weOrU | Trading On Data For The Ultimate Edge! \| PS60 Process | ~12:52 | OK (ASR) |
| a1gwzGXdBmM | Big Options Bets \| TSLA Included - Technical Market Analysis | ~16:44 | OK (ASR) |
| EQk_vs-wXfw | Trading Preparation Vs. Emotions \| Easier Trades With A Plan! \| PS60 Methodology | ~18:57 | OK (ASR) |
| hqsK4z4T_iA | The Power of Options Flow | ~17:21 | OK (ASR) |
| B6fk54cMwlk | Why I Use Options Flow When Trading Equities | ~18:25 | OK (ASR) |
| v3niO_7Evsc | All Traders Should Know This Simply Rule! \| PS60 Process | ~13:51 | OK (ASR) |

**Local notes merged (not invented):**
- `/workspace/ps60/docs/PS60_HANDOFF_FOR_CLAUDE_COLE.md` §11 Option flow; §9.6 options stop; language lock
- `/workspace/ps60/v3-notes.md` V3 delta #8 + 180–220 process (option flow module)
- `/workspace/ps60/v4-notes.md` V4 delta #4 (OF as hard filter)
- `/workspace/ps60/cheatsheets.md` Options Flow term; Level 2; Reload buyer/seller via T&S + L2

---

## 1) What Dan watches on desk

**Supported by sources (encode these surfaces):**

| Surface | What he watches | Source |
|---|---|---|
| **Option-flow / order-flow scanner** | Real-time unusual / institutional option prints (he names **FlowAlgo**; also cites TradeAlert, Cheddar Flow, Black Box Stocks, OptionAlert / “options alerts” as comparable). Reads **symbol, premium paid, expiration, strike, call/put, spot, exchange vs multi, sweep vs block, day’s volume vs OI**. | V3 notes §8 / V3 180–200; `ysshM1blOFA`, `URaAZxC23YU`, `B6fk54cMwlk`, `pho_podj1Ig`, handoff §11 |
| **Charts (Daily first, then 60m)** | Daily confirmation / reclaim / channel; 60m for the trade path and pivots. “Daily chart + option flow = results.” | V4 notes §4; `URaAZxC23YU`, `B6fk54cMwlk`, `ysshM1blOFA`, handoff §3–§5 |
| **Level 2 + Time & Sales** | Equity **order flow** at the second entry: reload seller stuck on offer / reload buyer stuck on bid while thousands print — exit even or with slippage. | `cheatsheets.md` Reload Seller/Buyer + Level 2 |
| **“Squat box” (webinar tool)** | Spoken as something public Twitter does **not** have, alongside option flow, in the live room. | V3 notes 220–232; V3 transcript ~3:01–3:02 |
| **Alerts on chart platform** | eSignal-style alerts at range/pivot breaks so flow already watched → enter with conviction. | `ysshM1blOFA` |

**Not found in these 12 videos or the locked notes:** an explicit “flow pane on the **left**, chart on the **right**” desk layout. Do **not** hard-code left/right as Dan’s words. Bot UI may place flow + chart + L2/T&S side-by-side, but cite only the surfaces above.

**Process line he repeats:** find / watch order flow → confirm the daily channel → see next measured potential (`B6fk54cMwlk`). Prep line: “You watch the options flow and you have all those boxes checked and you're just ready for that technical level to confirm” (`EQk_vs-wXfw`).

---

## 2) Exact timing filters — short-dated OTM calls/puts

### 2.1 Read fields on every print (V3 taught; handoff)

Encode parser fields (V3 notes / handoff §11 / V3 180–200):

1. Symbol  
2. Premium paid ($)  
3. Expiration date  
4. Strike  
5. Call (C) / Put (P)  
6. Spot (underlying price when print hit)  
7. Single exchange vs multi / “S” multi-fill  
8. Sweep vs block  
9. Day volume vs open interest (spoken on V3)

### 2.2 Filters Dan actually uses (directional conviction)

| Filter | Dan’s rule (paraphrase / quote) | Cite |
|---|---|---|
| **Premium $ floor** | Wants meaningful size — spoken ballpark **≥ ~$100k** premium (“at least 100k”). Videos emphasize **hundreds of thousands → millions / six–seven figure** bets as institutional participation. | V3 notes §8; V3 180–200; handoff §11; `HvDqcAem4KM`, `hqsK4z4T_iA`, `a1gwzGXdBmM`, `B6fk54cMwlk` |
| **DTE / expiration window** | Preference = **as short-term as possible**; **weeklies** preferred. “Next week’s,” “tomorrow’s expiration,” near-term / short-term expiration. Longer-dated (months out) is **not the same trade** — buyer has months of time (V3 Tesla/June example). Videos: weeklies / next weeks / short-term expiration repeatedly. | V3 notes §8; V3 180–200; `ysshM1blOFA`, `URaAZxC23YU`, `t67SFwBMcys`, `pho_podj1Ig`, `v3niO_7Evsc` |
| **Strike vs spot (OTM)** | Wants **out-of-the-money / deep OTM** directional bets, not near-spot after the move already made. Spoken examples: ~5–10 pts OTM weeklies; ~7–9 pts OTM with short expiry; ~20 pts OTM with a week left; “higher and higher out of the money” as buyers chase. | V3 notes §8; `ysshM1blOFA`, `URaAZxC23YU`, `t67SFwBMcys`, `pho_podj1Ig`, `B6fk54cMwlk`, `a1gwzGXdBmM`, `v3niO_7Evsc` |
| **Sweeps vs blocks** | **Sweep** = urgency / “I don’t care what I pay — get me in” (often multi-exchange). **Block** ≈ predetermined contra transaction (Dan: not an options expert; less relevant to how the trade works out). Equity play after a sweep: note sweep spot, let 5m put in a high (long) / low (short), then trade structure off that. | V3 notes §8; V3 180–200 |
| **Aggression** | “Aggressive out of the money calls,” “aggressive option flow,” “aggressive call buyers,” “aggressive put buying.” Aggression = size + OTM + short DTE + urgency, not a separate numeric score he named. | `URaAZxC23YU`, `t67SFwBMcys`, `B6fk54cMwlk`, `Z02b30weOrU`, `hqsK4z4T_iA` |
| **Repeats / reloads (flow)** | **Formula:** “multiple repeat buyers with short-term expiration” (`ysshM1blOFA`). Same idea: buyers “over and over,” “one after another,” same name / rising strikes / same short expiry series. More flow → greater chance of measured potential. | `ysshM1blOFA`, `URaAZxC23YU`, `t67SFwBMcys`, `B6fk54cMwlk`, `pho_podj1Ig`, V3 notes §8, V4 notes §4 |
| **Hedge vs directional bet** | Uptrend / stock already made highs + near-spot puts ≈ **hedge**. Multi-day selling + **OTM puts** at breakdown ≈ **bet** (not a hedge). Near-spot defense after highs ≠ directional short. | V3 notes §8; V3 180–200; handoff §11 |

### 2.3 Bot encoding (numeric gates — mapped from spoken, not invented labels)

Use these as **implementation defaults** tagged `from_dan_spoken`:

```
premium_usd_min          >= 100000          # V3 “at least 100k”
dte_prefer_max           <= 7–10 calendar   # weeklies / next week (spoken preference)
dte_hard_max_for_HOT     <= ~21             # still “short-term”; months-out ≠ same trade (V3)
otm_pct_or_dollars       strike clearly OTM vs spot (examples 5–20+ pts on beta)
repeat_prints_min        >= 2–3 same side/expiry cluster in session/prior sessions
sweep_flag               boost conviction if sweep/multi (V3)
block_alone              do not treat as urgency edge (V3)
hedge_filter             if puts + spot near ATM + prior multi-day up → mark HEDGE not SHORT
```

---

## 3) Long vs short / call vs put symmetry (“taking off” vs “dying”)

**Symmetry Dan teaches (same process both sides):**

| Long / calls | Short / puts | Source |
|---|---|---|
| Repeat **call** buyers, short-dated, OTM, size | Repeat **put** buyers, short-dated, OTM, size | V3 notes; `t67SFwBMcys`, `Z02b30weOrU`, `URaAZxC23YU` |
| Flow + **daily confirm up** → equity/options long bias | Flow + **daily confirm down** / breakdown → short bias | `ysshM1blOFA`, V4 formula |
| More call flow while themes work = participation still bullish | Aggressive put buying into weakness = “not a great sign” / sell-side clue | `HvDqcAem4KM`, `B6fk54cMwlk`, `Z02b30weOrU` |
| Hedge caution: near-spot puts in uptrend ≠ short | Hedge caution inverted: near-spot calls after multi-day dump may be hedge | V3 180–200 |

**Language actually on these tapes (do not invent a formal “taking off / dying” module name):**

- **Taking off / ignition:** when short-dated OTM flow **already watched** and the **chart confirms**, names “took off,” “exploded,” “ignited,” “might take off” (`hqsK4z4T_iA`, `ysshM1blOFA`, `pho_podj1Ig`, `URaAZxC23YU`).
- **Dying / stalling:** failed names “died on a vine” after no play (`B6fk54cMwlk`); market/premiums can still go to zero even with prior bets (`HvDqcAem4KM`); flow without daily confirm = lottery ticket that may never pay (`URaAZxC23YU`).

**Bot states (symmetric):**

- `FLOW_ALIVE_LONG` — repeat short-dated OTM **call** cluster, premium ≥ floor, not flagged hedge  
- `FLOW_ALIVE_SHORT` — repeat short-dated OTM **put** cluster, premium ≥ floor, not flagged hedge  
- `FLOW_FADING` — prior cluster, no repeats, or opposing flow appearing  
- `FLOW_DEAD / LOTTERY` — prints exist but **no** daily/60m confirm correlation  

---

## 4) How flow MUST sit AFTER if/when in a PS60 play

**Hard law (handoff §11 + V4 + videos):**  
`option flow supports a pivot thesis — it does not replace pivot / confirm / second entry / Daily MP.`

### 4.1 Ordered gate (encode exactly)

```
Daily room / MP (CLEAR vs THIN + ATR)     ← required or PASS
        ↓
Pivot valid (macro or sneaky)            ← chart
        ↓
Confirmation (break with another candle) ← chart
        ↓
Second entry (new extreme → retrace → break) ← chart
        ↓
Build / aggression in direction          ← chart (+ L2/T&S reload check)
        ↓
Option flow correlation SAME direction   ← flow SUPPORT only
        ↓
READY TO GO (both chart gate + flow gate)
```

### 4.2 Spoken “if/when” marriage

- “When option flow confirms and there’s a macro **daily confirmation** that confirms with it, the stock is probably going to react in that direction.” (`ysshM1blOFA`)  
- “Daily chart + option flow = results.” / chart check + range check + **option flow check** (V4 notes).  
- Two types of option betters (`URaAZxC23YU`): (1) **lottery** — bet without macro confirmation; (2) bet **after** stock confirms. Concentrate on aggressive repeat OTM near-term flow **when stock is confirming macro**.  
- “Don’t anticipate… let the market tell you” / be prepared technically; flow is data, not a crystal ball (`pho_podj1Ig`, `URaAZxC23YU`).  
- Off-beta / non-beta: V4 elevates OF to **required** — he will not trade a stock without option flow (V4 notes §4; handoff §11).  
- Equity path after sweep still uses **5m structure** after the sweep price (V3) — same family as second entry, not chase the print.

### 4.3 Options stop curveball (when trading options / OF-correlated options)

Do **not** use breakeven as the stop on an options / option-flow trade unless it correlates with a real confirmation pivot — use previous **5-min** low (long) / high (short). (V3 notes §8; handoff §9.6)

---

## 5) Real-time CONVICTION BOARD schema (bot-ready)

### 5.1 Board object

```jsonc
{
  "symbol": "TSLA",
  "side_bias": "LONG" | "SHORT" | "NONE",
  "updated_at": "ISO-8601 America/New_York",
  "chart_gate": { ... },
  "flow_gate": { ... },
  "lanes": [ ... ],
  "board_state": "PASS" | "WATCH" | "ARMED" | "READY_TO_GO" | "INVALIDATED",
  "score": 0-100,
  "traffic_light": "RED" | "YELLOW" | "GREEN",
  "anti_early_entry": { "chart_ok": false, "flow_ok": false, "both_true": false },
  "alerts": []
}
```

### 5.2 Lanes / rows (one row per symbol under watch)

| Lane id | Row meaning | Inputs | Traffic |
|---|---|---|---|
| `L0_DAILY_MP` | Daily room to next supply/demand + ATR | chart | R/Y/G |
| `L1_PIVOT` | Valid pivot / sneaky marked | chart | R/Y/G |
| `L2_CONFIRM` | Confirm candle through pivot | chart | R/Y/G |
| `L3_SECOND_ENTRY` | New extreme → retrace → 2nd entry trigger | chart | R/Y/G |
| `L4_BUILD` | Price improving; no reload trap | chart + L2 + T&S | R/Y/G |
| `L5_FLOW_SIDE` | Call cluster (long) / put cluster (short) | option prints | R/Y/G |
| `L6_FLOW_QUALITY` | Premium ≥$100k, short DTE, OTM, repeats, sweep boost, hedge filter | option prints | R/Y/G |
| `L7_CORRELATION` | Flow side == chart side **and** after confirm | both | R/Y/G |

### 5.3 Score (example weights — tune; concepts from Dan)

| Component | Points | Notes |
|---|---|---|
| Daily MP CLEAR | 20 | handoff MP law |
| Pivot + confirm | 20 | |
| Second entry printed | 20 | |
| Flow premium ≥$100k | 10 | V3 |
| Short DTE (weeklies/near) | 10 | videos + V3 |
| OTM (not hedge) | 10 | |
| Repeat buyers ≥2–3 | 10 | formula videos |
| Sweep/multi urgency | +5 bonus | V3 (cap 100) |

**Traffic light:**  
- **RED** `PASS` — any of L0–L3 red, or hedge-only flow, or flow opposite chart  
- **YELLOW** `WATCH`/`ARMED` — chart building OR flow building, not both complete  
- **GREEN** `READY_TO_GO` — **L0–L4 green AND L5–L7 green** (see §7)

### 5.4 Alert copy templates

**LONG (calls / equity long):**
```
[PS60 OF] {SYMBOL} LONG WATCH — short-dated OTM CALL flow ({premium_usd}, {dte}DTE, strike {strike} vs spot {spot}, repeats={n}). Chart: pivot {pivot} {confirm_state}. NOT READY until second entry + flow correlation.
[PS60 OF] {SYMBOL} LONG ARMED — daily confirm + CALL flow quality GREEN. Waiting second entry through {trigger}.
[PS60 OF] {SYMBOL} LONG READY TO GO — chart gate GREEN (2nd entry {trigger}) AND flow gate GREEN (repeat short-dated OTM calls). MP {mp_usd} / ATR {atr}. Max pain: prior 5m low (options) / process stop (equity).
[PS60 OF] {SYMBOL} LONG INVALIDATED — lost confirm / reload seller / opposing put flow / MP gone.
```

**SHORT (puts / equity short):**
```
[PS60 OF] {SYMBOL} SHORT WATCH — short-dated OTM PUT flow ({premium_usd}, {dte}DTE, strike {strike} vs spot {spot}, repeats={n}). Hedge check={hedge_flag}. Chart: pivot {pivot} {confirm_state}. NOT READY until second entry + flow correlation.
[PS60 OF] {SYMBOL} SHORT ARMED — daily breakdown/confirm + PUT flow quality GREEN (not hedge). Waiting second entry through {trigger}.
[PS60 OF] {SYMBOL} SHORT READY TO GO — chart gate GREEN (2nd entry {trigger}) AND flow gate GREEN (repeat short-dated OTM puts, hedge=false). MP {mp_usd} / ATR {atr}. Max pain: prior 5m high (options).
[PS60 OF] {SYMBOL} SHORT INVALIDATED — reclaim / reload buyer / opposing call flow / MP gone.
```

**Never emit READY from flow alone** (handoff non-goals; `URaAZxC23YU` lottery warning).

---

## 6) Inputs the platform must wire

| Input | Required fields | Used by |
|---|---|---|
| **Option prints feed** | symbol, ts, premium_usd, expiry, dte, strike, cp, spot, exchange/multi, sweep/block, size, vol, oi | L5–L7, hedge filter |
| **Level 2** | aggregated bid/ask sizes at inside; stuck size on bid/offer | L4 reload buyer/seller |
| **Time & Sales** | print price, size, side aggression if available | L4 reload confirmation |
| **Chart state machine** | `pivot`, `confirm`, `second_entry`, `build`, `invalidated` | L1–L4 |
| **Daily gate** | `mp_usd`, `mp_side` (supply up / demand down), `atr`, `clear_thin` | L0 |
| **ATR** | daily (ops grading) | MP judgment; board display |
| **MP remaining** | dollars still open to next supply/demand far edge | runner / PASS |
| **Session clock** | RTH; premium-day vs muted (first 30–40m tell) | size / aggression context (V3) |

Optional but named by Dan: FlowAlgo-class scanner stream; eSignal/TOS alerts at pivot.

---

## 7) Anti-early-entry gate (Antoine enters too soon / paper drawdowns)

```
READY_TO_GO := chart_gate_true AND flow_gate_true

chart_gate_true :=
    Daily MP present
    AND pivot valid
    AND confirm true
    AND second_entry true   // new extreme → retrace → break of that extreme
    AND (build starting OR ≤~2 min grace per V3 second-entry clock)

flow_gate_true :=
    same_side as chart (calls↔long / puts↔short)
    AND premium_usd >= 100000   // or stacked repeats totaling institutional size
    AND short_dated (weeklies / near-term preference)
    AND OTM (hedge_filter == false)
    AND repeat_cluster (multiple buyers / over-and-over)
```

**Explicit forbids:**
- Do **not** fire READY because flow printed while price is still mid-channel / unconfirmed (`URaAZxC23YU` lottery vs confirm betters; `ysshM1blOFA` conviction vs buying mid-range).  
- Do **not** chase the first sweep print — wait structure after sweep spot (V3).  
- Do **not** treat near-spot protective puts in an uptrend as SHORT READY (V3 hedge).  
- Do **not** replace second entry with “flow is huge” (handoff §11, §18).  
- UI label when only one gate is true: **`ARMED — WAITING OTHER GATE`**, never READY.

**Prep mindset (encode as UX copy):** boxes checked on flow **before** the technical level confirms — then execute without emotion (`EQk_vs-wXfw`). That is preparation, not early entry.

---

## 8) Rule → citation index (bot comments / tests)

| # | Rule | Cite |
|---|---|---|
| R1 | Read symbol, premium, expiry, strike, C/P, spot, exchange/multi, sweep/block | V3 notes §8; handoff §11; V3 180–200 |
| R2 | Premium meaningful ≥ ~$100k | V3 notes §8; V3 180–200 |
| R3 | Prefer weeklies / shortest expiry; long-dated ≠ same trade | V3 180–200; `ysshM1blOFA`, `URaAZxC23YU`, `t67SFwBMcys` |
| R4 | Short-dated + OTM + size = directional premium bet | V3 notes §8; handoff §11; videos above |
| R5 | Repeat / multiple buyers short-term = formula | `ysshM1blOFA`; `URaAZxC23YU`; `B6fk54cMwlk` |
| R6 | More flow → greater chance of MP | V3 notes §8; V4 notes §4; `t67SFwBMcys` |
| R7 | Daily + OF = results; OF hard filter esp. off-beta | V4 notes §4; handoff §11; `ysshM1blOFA` |
| R8 | Flow supports pivot; never replaces confirm / 2nd entry / Daily MP | handoff §11; `URaAZxC23YU`; `pho_podj1Ig` |
| R9 | Hedge vs bet (puts) | V3 notes §8; V3 180–200 |
| R10 | After sweep: 5m high/low after sweep price then structure | V3 notes §8; V3 180–200 |
| R11 | Options/OF trade: no BE stop unless confirm pivot; use prior 5m | V3 notes §8; handoff §9.6 |
| R12 | L2 + T&S: reload buyer/seller → exit even/slippage | cheatsheets.md |
| R13 | Two betters: lottery without confirm vs bet after confirm — focus latter | `URaAZxC23YU` |
| R14 | Watch OF + boxes checked → ready for technical confirm (prep, not chase) | `EQk_vs-wXfw` |
| R15 | Aggressive put buying can flag downside risk (symmetric to call aggression) | `Z02b30weOrU` |
| R16 | Experienced big-picture: collecting OF data; 60m stops | cheatsheets Risk § Experienced |
| R17 | Cheat-sheet OF definition: indication **with pivot confirmation** | cheatsheets Options Flow term |

---

## 9) What these 12 videos do **not** add (leave empty — do not invent)

- Exact “flow left / chart right” monitor coordinates  
- Gamma / GEX / dealer positioning teaching (Dan: “not an options trader”)  
- Numeric OTM% table or fixed DTE enum beyond weeklies/near-term preference  
- Formal glossary term “taking off vs dying” as a named module (only natural language ignition vs stall)  
- `8wLDi6jdgIw` — whole-picture / QQQ level short; **no** option-flow timing filters  

---

## 10) Acceptance tests for Cole’s bot

1. READY requires `chart_gate && flow_gate` — unit test both false paths.  
2. Print with premium <$100k alone cannot turn L6 green unless stacked repeats meet size story (document threshold).  
3. ATM/near-spot puts after multi-day up → `hedge=true` → cannot SHORT READY.  
4. Months-out large premium → quality yellow vs weeklies green (V3 “not the same trade”).  
5. Second entry false → max state ARMED even if flow is monster.  
6. Language filter: UI uses only allowed PS60 terms (handoff §1); “Options Flow” allowed.  
7. Citations: each emitted alert reason code maps to a row in §8.

---

**End of SoT.**  
Path: `/workspace/ps60/docs/PS60_OPTION_FLOW_CONVICTION_BOARD_FOR_BOT.md`  
Transcripts: `/workspace/ps60/docs/option-flow-vids/`
