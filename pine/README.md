# PS60 Pine Script work

Staging area for the PS60 Desk+ upgrade and the companion second-entry backtester.

## Status

Waiting on the complete PS60 Desk+ source. The paste received so far was
truncated mid-line at:

    bool showSup   = input.bool(true, "Old supply (last finished month high)", group =

`_incoming_chunk01.pine` holds the verified first chunk (through the
after-hours session input), preserved byte-for-byte including the
Unicode arrows in the zone-fill colour labels.

Once the full source lands, the merge produces two deliverables:

1. `PS60_Desk_Plus.pine` — the existing desk with the 11 spec upgrades added
   in place. ATR engine, gas tank, "Traveled" label wording, the calendar-date
   day rollover and the RTH-only day high/low seeding all stay untouched.
2. `PS60_Second_Entry_Backtester.pine` — separate lower-pane script, does not
   touch the desk.
