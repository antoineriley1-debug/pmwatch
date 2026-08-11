"""Asset-specific QC checklists for PMWATCH.

A closed PM is classified into an asset type from its text (system /
procedure / reason / asset name), and each type maps to a concrete list of
inspection items the director checks off. The score is derived from the
fraction of items marked OK, so "pass/fail + score" is backed by real,
auditable checks instead of a guess.

Keep item `id`s stable — they are stored in qc_reviews.checklist and used
for reporting. Add new types by adding an entry to CHECKLISTS plus a
matcher in classify().
"""
import re

# Each checklist: ordered list of (id, label). id is stable + short.
CHECKLISTS = {
    "hvac_coil": {
        "label": "HVAC Coil / Chilled-Water",
        "items": [
            ("coil_clean", "Coil fins clean, straight, free of debris"),
            ("no_leaks", "No refrigerant/water leaks at coil or connections"),
            ("condensate", "Condensate drain/pan clear and draining"),
            ("valves", "Control valves operate + hold setpoint"),
            ("temp_split", "Supply/return temp split within spec"),
            ("insulation", "Piping insulation intact, no sweating"),
            ("filters", "Associated filters clean / replaced"),
            ("housekeeping", "Area clean, panels reinstalled"),
        ],
    },
    "hvac_unit": {
        "label": "HVAC Unit / Condenser / AHU",
        "items": [
            ("belts", "Belts/sheaves tension + wear OK"),
            ("bearings", "Bearings/motor no abnormal noise or heat"),
            ("amp_draw", "Motor amp draw within nameplate"),
            ("coil_clean", "Coils clean, fins straight"),
            ("filters", "Filters clean / replaced, correct size"),
            ("condensate", "Condensate drain clear"),
            ("refrigerant", "Refrigerant charge / pressures normal"),
            ("controls", "Controls + safeties respond correctly"),
            ("housekeeping", "Unit clean, panels + guards secured"),
        ],
    },
    "med_gas": {
        "label": "Medical Gas System",
        "items": [
            ("leaks", "No leaks at valves, fittings, outlets"),
            ("pressure", "Line pressure within spec for each gas"),
            ("labels", "Piping/outlets correctly labeled + color-coded"),
            ("outlets", "Outlets latch, seal, and flow correctly"),
            ("zone_valves", "Zone valves operate + labeled"),
            ("no_cross", "No cross-connection between gases"),
            ("source", "Source/manifold status normal"),
            ("housekeeping", "Cabinet/area clean and accessible"),
        ],
    },
    "med_gas_alarm": {
        "label": "Medical Gas Alarm Panel",
        "items": [
            ("power", "Panel powered, no fault lights"),
            ("test_alarm", "Alarm test triggers audible + visual"),
            ("sensors", "Each gas sensor reads correct pressure"),
            ("labels", "Zones/gases correctly labeled"),
            ("silence", "Silence/reset functions work"),
            ("battery", "Backup battery OK"),
            ("log", "Test logged with date/time"),
        ],
    },
    "auto_door": {
        "label": "Automatic Door System",
        "items": [
            ("open_close", "Opens/closes fully + smoothly"),
            ("sensors", "Motion + safety sensors detect properly"),
            ("speed", "Open/close speed + hold time within spec"),
            ("safety_stop", "Reverses on obstruction"),
            ("seals", "Weather seals / gaskets intact"),
            ("hardware", "Rollers, arms, hinges secure"),
            ("emergency", "Breakout / emergency egress works"),
            ("housekeeping", "Track clean, area clear"),
        ],
    },
    "neg_pressure": {
        "label": "Negative Pressure Room",
        "items": [
            ("direction", "Airflow direction correct (into room)"),
            ("magnehelic", "Pressure differential within spec"),
            ("monitor", "Room pressure monitor reads + alarms"),
            ("seals", "Door + wall penetrations sealed"),
            ("ach", "Air changes/hour meet requirement"),
            ("exhaust", "Exhaust operating, not recirculating"),
            ("log", "Reading documented"),
        ],
    },
    "plumbing_water": {
        "label": "Plumbing / Water Fixture",
        "items": [
            ("flow", "Adequate flow + pressure"),
            ("no_leaks", "No leaks at supply, drain, fittings"),
            ("temp", "Hot/cold + mixing valve temps correct"),
            ("drain", "Drains freely, no backup"),
            ("flush", "Flush/valve operates correctly"),
            ("aerator", "Aerator/strainer clean"),
            ("housekeeping", "Fixture + area clean"),
        ],
    },
    "booster_pump": {
        "label": "Pump / Booster Pump",
        "items": [
            ("no_leaks", "No seal or flange leaks"),
            ("noise", "No abnormal noise/vibration"),
            ("amp_draw", "Motor amp draw within nameplate"),
            ("pressure", "Discharge pressure within setpoint"),
            ("bearings", "Bearings lubricated / OK"),
            ("alignment", "Coupling/alignment OK"),
            ("controls", "Controls + lead-lag operate"),
            ("housekeeping", "Area clean, guards in place"),
        ],
    },
    "electrical": {
        "label": "Electrical / Panel / Code Cart Power",
        "items": [
            ("thermal", "No hot spots / discoloration on terminals"),
            ("torque", "Connections tight, no arcing signs"),
            ("labels", "Panel/circuits labeled correctly"),
            ("gfci", "GFCI/breakers test + reset"),
            ("clearance", "Working clearance maintained"),
            ("grounding", "Grounding/bonding intact"),
            ("housekeeping", "Panel closed, area clear"),
        ],
    },
    "fire_life_safety": {
        "label": "Fire / Life Safety",
        "items": [
            ("device_test", "Device activates on test"),
            ("panel", "Panel shows normal, no trouble"),
            ("visual", "No physical damage/obstruction"),
            ("clearance", "Clearance to sprinklers/devices OK"),
            ("signage", "Signage/exit path clear + lit"),
            ("log", "Test documented"),
        ],
    },
    "generic": {
        "label": "General PM Verification",
        "items": [
            ("scope", "All PM procedure steps completed"),
            ("operational", "Asset operates correctly after PM"),
            ("no_leaks", "No leaks / abnormal noise / vibration"),
            ("safety", "Safety devices + guards in place"),
            ("readings", "Readings/measurements within spec"),
            ("parts", "Correct parts/consumables used"),
            ("housekeeping", "Work area clean, restored to service"),
            ("documentation", "WO documented (readings, notes)"),
        ],
    },
}

# Ordered (type, regex) matchers. First match wins, so put specific before
# general (alarm panel before generic med gas, etc.).
_MATCHERS = [
    ("med_gas_alarm", r"med(ical)?\s*gas.*alarm|gas\s*alarm\s*panel|alarm\s*panel"),
    ("med_gas",       r"med(ical)?\s*gas|\bo2\b|oxygen|vacuum\s*outlet|\bmedgas\b"),
    ("neg_pressure",  r"negative\s*pressure|neg\s*press|isolation\s*room|ai{2}r+borne"),
    ("auto_door",     r"automatic\s*door|auto\s*door|door\s*operator|slid(e|ing)\s*door"),
    ("hvac_coil",     r"coil|chilled\s*h2o|chilled\s*water|\bchw\b|reheat"),
    ("booster_pump",  r"booster\s*pump|\bpump\b"),
    ("hvac_unit",     r"condenser|\bahu\b|air\s*handler|\brtu\b|\bfcu\b|compressor|"
                      r"cooling\s*tower|\bhvac\b|chiller|fan\s*coil"),
    ("plumbing_water", r"shower|drinking\s*water|fountain|faucet|\bsink\b|water\s*heater|"
                       r"backflow|mixing\s*valve|flush|domestic\s*water|plumb"),
    ("electrical",    r"electrical|panelboard|breaker|\bgfci\b|transformer|switchgear|"
                      r"receptacle|code\s*cart"),
    ("fire_life_safety", r"fire\s*(alarm|pump|extinguish|sprinkler)|smoke\s*detector|"
                         r"life\s*safety|emergency\s*light|exit\s*sign"),
]


def classify(*texts):
    """Return the asset_type key for a WO from any of its text fields.

    Pass system, procedure, reason, asset_name in any order; the first
    matcher that hits wins. Falls back to 'generic'.
    """
    blob = " ".join(t for t in texts if t).lower()
    for key, pat in _MATCHERS:
        if re.search(pat, blob):
            return key
    return "generic"


def get_checklist(asset_type):
    """Return the checklist dict {label, items:[(id,label)]} for a type."""
    return CHECKLISTS.get(asset_type, CHECKLISTS["generic"])


def score_from_checklist(item_results):
    """Compute a 0-100 score from a list of {id,label,ok} dicts.

    Score = round(100 * passed / total). Returns (score, passed, total).
    Empty list -> (None, 0, 0).
    """
    if not item_results:
        return None, 0, 0
    total = len(item_results)
    passed = sum(1 for it in item_results if it.get("ok"))
    return round(100 * passed / total), passed, total
