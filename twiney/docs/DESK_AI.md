# DESK AI — a local model, taught PS60, reading the desk's own records

The DESK AI panel runs a language model on your own computer through **Ollama**. It is never in the live read: the
desk's rules make every call on the tape, and nothing the model writes becomes a call, a voice line or a trade.
It reads what the desk recorded and writes it up for you.

## What it does

| button | what it reads | what it writes |
|---|---|---|
| **RECAP + TOMORROW** | the story, the calls, THE DESK SCORE, the levels, the 60-minute candles, the option flow, your notes, fills and P&L for every stock on the desk | Part 1: today's recap. Part 2: tomorrow's plan per stock: the Daily bias, the levels in order, the long and short pivot with what confirms it, the second-entry structure to wait for, MP against ATR, max pain, what makes it a PASS |
| **EXPLAIN** | the ticker on screen: its levels, story and calls | why the desk said what it said, in plain words, and what it does not mean yet |
| **CLEAN NOTES** | your notes and mic markers today | a clean journal, every ticker and level kept |
| **STUDY DAYS** | the storyline and the score over the recorded days (SETTINGS › AI › days read) | the patterns that repeat, the bias to carry, what to tune |
| **ASK** | today's data, briefly | an answer to your question |

After the close (16:05 ET by default), on a day the desk was connected, the recap and tomorrow's plan are written on
their own and announced in MESSAGES. Every answer is saved under `recordings/ai/` with **everything the model was
given** underneath it, so the words can always be checked against the numbers. **WHAT IT WAS GIVEN** on the panel
shows the same.

## What it is taught

Before the model reads a single number it is given the PS60 knowledge file (`twiney/knowledge/ps60.md`): supply to
supply and demand to demand, the Daily first, six 60-minute candles, pivot → confirmation → second entry → build →
pay yourself → runner to measured potential, the sneaky pivot, bounce / remount / rejection, risk by trader stage,
option flow as support never the thesis, the 5-7 minute rule, the options translation, and the desk's own words
(reload buyer / seller, RELOADING, STILL THERE, NOT RELOADING, CLEANED UP, PULLED, large orders, the lean, the regime,
the attempts, THE DESK SCORE). The language lock is applied to its answers too: a word from outside PS60 is swapped for the PS60 word before you see it.

## Setting it up (once, five minutes)

1. Install Ollama from https://ollama.com (Windows installer). It runs in the background and answers at
   `http://127.0.0.1:11434`.
2. Pull a model. In a terminal (PowerShell):
   ```
   ollama pull llama3.1:8b
   ```
   On a laptop without a real GPU an 8B model writes the recap in one to three minutes. Quicker and still good
   enough for the recap and the notes:
   ```
   ollama pull llama3.2:3b
   ```
   then put `llama3.2:3b` in SETTINGS › AI › Model.
3. On the desk: SETTINGS › AI (Ollama) › Enabled on, SAVE. The panel's status line turns READY when Ollama answers
   and has the model. OLLAMA NOT ANSWERING = Ollama is not running or the address is wrong; MODEL MISSING = run the
   pull command it shows.
4. PANELS › DESK AI if the panel is not on your layout (it docks itself once, bottom left).

No key, no account, nothing leaves the computer.

## Settings (SETTINGS › AI)

- Enabled · Ollama address · Model · Wait for an answer up to (s) · Reading window (tokens; 8192 holds a full day for
  six stocks) · Temperature (0 = strict to the data) · Recap + tomorrow's plan on its own after the close · minutes
  after 16:00 · Cross-day study: days read.

## Limits, honestly

- A language model writes well and reads your records faithfully when the data is in front of it. It will still
  sometimes word a thing wrong or overreach. That is why every answer carries its data: read the numbers, not only
  the words.
- The next-day plan is a plan from PS60 and today's levels, never a prediction. The model is told to say what would
  CONFIRM each side and what makes it a PASS, and never that a level will hold or break.
- The cross-day study needs real recorded days (the storyline is written on connected days only). With fewer than
  ten days it will say the sample is thin.
- On the practice desk the numbers are synthetic; the recap of a practice day proves the plumbing, not the market.
