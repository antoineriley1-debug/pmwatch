"""Database layer for PMWATCH.

Neon Postgres only. Connects via DATABASE_URL. Never SQLite (Render's
free disk is ephemeral). All access goes through short-lived connections
so a sleeping/restarting Render dyno never holds a dead handle.
"""
import os
import psycopg2
import psycopg2.extras


def get_conn():
    """Open a new Postgres connection from DATABASE_URL.

    Fails loudly if the env var is missing so we never silently run
    against nothing.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set in environment variables")
    # Neon requires SSL; if the URL didn't include it, enforce it.
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return psycopg2.connect(url, connect_timeout=15)


# Schema for closed preventative-maintenance work orders.
# Corrective tickets are excluded at scrape time and never reach here.
SCHEMA = """
CREATE TABLE IF NOT EXISTS closed_pms (
    id              BIGSERIAL PRIMARY KEY,
    wo_number       TEXT NOT NULL UNIQUE,      -- e.g. 52626-01234, dedup key
    hospital_code   TEXT,                      -- e.g. 52626
    hospital_name   TEXT,                      -- e.g. Medstar Washington Hospital Center
    closed_by       TEXT,                      -- who closed it (mechanic/contractor)
    close_date      DATE,                      -- completion date
    close_ts        TIMESTAMP,                 -- minute-level close time if MC exposes it
    asset_name      TEXT,
    asset_model     TEXT,
    asset_serial    TEXT,
    wo_type         TEXT,                      -- raw type/label from MC (audit)
    system          TEXT,                      -- PM system/category (HVAC, med gas, ...)
    procedure       TEXT,                      -- PM procedure name
    reason          TEXT,                      -- WO reason/title
    location        TEXT,                      -- location text
    target_date     DATE,                      -- scheduled/target date from list view
    enriched        BOOLEAN NOT NULL DEFAULT FALSE,  -- detail fetched yet?
    raw             JSONB,                     -- full scraped row for forensics
    scraped_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_closed_pms_hospital ON closed_pms (hospital_code);
CREATE INDEX IF NOT EXISTS idx_closed_pms_close_date ON closed_pms (close_date);
CREATE INDEX IF NOT EXISTS idx_closed_pms_closed_by ON closed_pms (closed_by);
CREATE INDEX IF NOT EXISTS idx_closed_pms_system ON closed_pms (system);
CREATE INDEX IF NOT EXISTS idx_closed_pms_enriched ON closed_pms (enriched);

-- Backfill columns for existing deployments (idempotent).
ALTER TABLE closed_pms ADD COLUMN IF NOT EXISTS system TEXT;
ALTER TABLE closed_pms ADD COLUMN IF NOT EXISTS procedure TEXT;
ALTER TABLE closed_pms ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE closed_pms ADD COLUMN IF NOT EXISTS location TEXT;
ALTER TABLE closed_pms ADD COLUMN IF NOT EXISTS target_date DATE;
ALTER TABLE closed_pms ADD COLUMN IF NOT EXISTS enriched BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE closed_pms ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

-- QC results: one row per QC review of a closed PM.
CREATE TABLE IF NOT EXISTS qc_reviews (
    id            BIGSERIAL PRIMARY KEY,
    wo_number     TEXT NOT NULL REFERENCES closed_pms(wo_number) ON DELETE CASCADE,
    result        TEXT NOT NULL,               -- pass | fail
    score         INT,                         -- optional 0-100
    notes         TEXT,
    reviewer      TEXT,
    photos        JSONB,                       -- list of photo refs (later R2)
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qc_wo ON qc_reviews (wo_number);

-- Asset-specific QC checklist support: which checklist template was used
-- and the per-item pass/fail results (list of {id,label,ok}).
ALTER TABLE qc_reviews ADD COLUMN IF NOT EXISTS asset_type TEXT;
ALTER TABLE qc_reviews ADD COLUMN IF NOT EXISTS checklist JSONB;

-- Vendor contracts.
CREATE TABLE IF NOT EXISTS contracts (
    id            BIGSERIAL PRIMARY KEY,
    vendor        TEXT NOT NULL,
    hospital_code TEXT,
    scope         TEXT,
    start_date    DATE,
    end_date      DATE,
    obligations   JSONB,                       -- [{asset/system, qty, frequency}]
    notes         TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_contracts_vendor ON contracts (vendor);

-- Mechanics roster: overlays the closed_by name with an active/inactive flag
-- and optional display name. closed_by remains the join key (name as it
-- appears in Maintenance Connection). A mechanic who leaves is marked
-- inactive (active=FALSE) but their history is preserved.
CREATE TABLE IF NOT EXISTS mechanics (
    id            BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,        -- matches closed_pms.closed_by
    display_name  TEXT,                        -- optional friendly name
    hospital_code TEXT,                        -- home site (optional)
    trade         TEXT,                        -- HVAC, plumber, electrician...
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    left_date     DATE,                        -- when marked inactive
    notes         TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mechanics_active ON mechanics (active);
"""


def _iter_statements(sql):
    """Split a SQL script into statements, ignoring semicolons that appear
    inside line comments. Naive split-on-';' can mis-split when a comment
    contains a ';'; this strips '--' comments per line first.
    """
    cleaned_lines = []
    for line in sql.splitlines():
        # drop trailing line comment (no string literals in our schema)
        idx = line.find("--")
        if idx != -1:
            line = line[:idx]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def init_db(verbose=False):
    """Create tables/indexes/columns if missing. Idempotent.

    Each statement runs on its OWN fresh connection so a failure can never
    leave a poisoned/aborted transaction that silently skips later
    statements (the previous single-connection approach could do that).
    Returns a per-statement report when verbose=True.
    """
    stmts = _iter_statements(SCHEMA)
    report = []
    for stmt in stmts:
        label = " ".join(stmt.split())[:70]
        conn = None
        try:
            conn = get_conn()
            conn.autocommit = True  # each DDL commits immediately, no shared txn
            with conn.cursor() as cur:
                cur.execute(stmt)
            report.append({"stmt": label, "ok": True})
        except Exception as e:
            report.append({"stmt": label, "ok": False, "error": str(e)})
        finally:
            if conn is not None:
                conn.close()
    if verbose:
        return report
    return None


def backfill_hospital_names(name_map):
    """Set hospital_name for every row by hospital_code from a code->name
    map. Fixes rows scraped before live-name capture worked. Returns the
    per-code updated counts."""
    conn = get_conn()
    out = {}
    try:
        with conn, conn.cursor() as cur:
            for code, name in name_map.items():
                cur.execute(
                    """UPDATE closed_pms SET hospital_name = %s, updated_at = NOW()
                       WHERE hospital_code = %s
                         AND (hospital_name IS NULL OR hospital_name <> %s)""",
                    (name, code, name),
                )
                out[code] = cur.rowcount
    finally:
        conn.close()
    return out


def table_columns(table):
    """Return the column names for a table (for migration diagnostics)."""
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_name = %s ORDER BY ordinal_position""",
                (table,),
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def upsert_pms(rows):
    """Insert new closed-PM rows or UPDATE enrichment fields on existing.

    Dedup key is wo_number. A WO first seen from the list (no closed_by yet)
    is inserted; when later enriched from the detail page, the same wo_number
    UPDATEs with closed_by/close_date/system/etc. instead of being skipped.
    Returns counts.
    """
    if not rows:
        return {"received": 0, "inserted": 0, "updated": 0}

    init_db()
    conn = get_conn()
    inserted = 0
    updated = 0
    try:
        with conn, conn.cursor() as cur:
            for r in rows:
                raw = r.get("raw") or {}
                system = r.get("system") or raw.get("pm_name") or raw.get("system")
                procedure = r.get("procedure") or raw.get("procedure")
                reason = r.get("reason") or raw.get("reason")
                location = r.get("location") or raw.get("location")
                target_date = r.get("target_date") or raw.get("target_date")
                is_enriched = bool(r.get("closed_by") or r.get("close_date")
                                   or (raw.get("detail")))
                cur.execute(
                    """
                    INSERT INTO closed_pms
                        (wo_number, hospital_code, hospital_name, closed_by,
                         close_date, close_ts, asset_name, asset_model,
                         asset_serial, wo_type, system, procedure, reason,
                         location, target_date, enriched, raw, updated_at)
                    VALUES
                        (%(wo_number)s, %(hospital_code)s, %(hospital_name)s,
                         %(closed_by)s, %(close_date)s, %(close_ts)s,
                         %(asset_name)s, %(asset_model)s, %(asset_serial)s,
                         %(wo_type)s, %(system)s, %(procedure)s, %(reason)s,
                         %(location)s, %(target_date)s, %(enriched)s, %(raw)s, NOW())
                    ON CONFLICT (wo_number) DO UPDATE SET
                        closed_by   = COALESCE(EXCLUDED.closed_by, closed_pms.closed_by),
                        close_date  = COALESCE(EXCLUDED.close_date, closed_pms.close_date),
                        asset_name  = COALESCE(EXCLUDED.asset_name, closed_pms.asset_name),
                        asset_model = COALESCE(EXCLUDED.asset_model, closed_pms.asset_model),
                        asset_serial= COALESCE(EXCLUDED.asset_serial, closed_pms.asset_serial),
                        system      = COALESCE(EXCLUDED.system, closed_pms.system),
                        procedure   = COALESCE(EXCLUDED.procedure, closed_pms.procedure),
                        reason      = COALESCE(EXCLUDED.reason, closed_pms.reason),
                        location    = COALESCE(EXCLUDED.location, closed_pms.location),
                        target_date = COALESCE(EXCLUDED.target_date, closed_pms.target_date),
                        enriched    = closed_pms.enriched OR EXCLUDED.enriched,
                        raw         = EXCLUDED.raw,
                        updated_at  = NOW()
                    WHERE closed_pms.enriched = FALSE OR EXCLUDED.enriched = TRUE
                    """,
                    {
                        "wo_number": r.get("wo_number"),
                        "hospital_code": r.get("hospital_code"),
                        "hospital_name": r.get("hospital_name"),
                        "closed_by": r.get("closed_by"),
                        "close_date": r.get("close_date"),
                        "close_ts": r.get("close_ts"),
                        "asset_name": r.get("asset_name"),
                        "asset_model": r.get("asset_model"),
                        "asset_serial": r.get("asset_serial"),
                        "wo_type": r.get("wo_type"),
                        "system": system,
                        "procedure": procedure,
                        "reason": reason,
                        "location": location,
                        "target_date": target_date,
                        "enriched": is_enriched,
                        "raw": psycopg2.extras.Json(raw or r),
                    },
                )
                if cur.rowcount:
                    # xmax=0 heuristic isn't available here; treat statement as
                    # insert-or-update. Distinguish via a follow-up is costly,
                    # so approximate: rely on caller-level newness if needed.
                    inserted += 1
    finally:
        conn.close()

    return {
        "received": len(rows),
        "written": inserted,
    }


def count_pms(hospital_code=None):
    """Return how many closed PMs are stored, optionally per hospital."""
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            if hospital_code:
                cur.execute(
                    "SELECT COUNT(*) FROM closed_pms WHERE hospital_code = %s",
                    (hospital_code,),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM closed_pms")
            return cur.fetchone()[0]
    finally:
        conn.close()


def hospital_stats():
    """Per-hospital rollup for the dashboard cards: total PMs, plus how
    many were scraped today and in the last 7 days."""
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT hospital_code,
                          MAX(hospital_name) AS hospital_name,
                          COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE scraped_at::date = NOW()::date) AS today,
                          COUNT(*) FILTER (WHERE scraped_at >= NOW() - INTERVAL '7 days') AS week,
                          MAX(scraped_at) AS last_scraped
                   FROM closed_pms
                   GROUP BY hospital_code
                   ORDER BY hospital_code"""
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def list_pms(hospital_code=None, limit=500, system=None, order="close_date"):
    """Full PM rows for the dashboard table with enriched fields."""
    order_sql = {
        "close_date": "close_date DESC NULLS LAST, scraped_at DESC",
        "system": "system NULLS LAST, close_date DESC",
        "site": "hospital_code, close_date DESC",
        "mechanic": "closed_by NULLS LAST, close_date DESC",
    }.get(order, "close_date DESC NULLS LAST, scraped_at DESC")
    where = []
    params = []
    if hospital_code:
        where.append("hospital_code = %s")
        params.append(hospital_code)
    if system:
        where.append("system = %s")
        params.append(system)
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""SELECT wo_number, hospital_code, hospital_name, closed_by,
                          close_date, target_date, asset_name, system, procedure,
                          reason, location, enriched
                   FROM closed_pms {wsql}
                   ORDER BY {order_sql} LIMIT %s""",
                params,
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def closed_today_by_site():
    """PMs closed TODAY per site + network total. Uses actual close_date."""
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT hospital_code, MAX(hospital_name) AS hospital_name,
                          COUNT(*) FILTER (WHERE close_date = CURRENT_DATE) AS today,
                          COUNT(*) FILTER (WHERE close_date >= date_trunc('week', CURRENT_DATE)) AS week,
                          COUNT(*) FILTER (WHERE close_date >= date_trunc('month', CURRENT_DATE)) AS month,
                          COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE enriched) AS enriched
                   FROM closed_pms
                   GROUP BY hospital_code
                   ORDER BY today DESC, total DESC"""
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def completion_trend(hospital_code=None, days=30):
    """Daily completion counts for trend charts (per-site or network)."""
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if hospital_code:
                cur.execute(
                    """SELECT close_date::text AS day, COUNT(*) AS n
                       FROM closed_pms
                       WHERE close_date IS NOT NULL AND hospital_code = %s
                         AND close_date >= CURRENT_DATE - %s::int
                       GROUP BY close_date ORDER BY close_date""",
                    (hospital_code, days),
                )
            else:
                cur.execute(
                    """SELECT close_date::text AS day, COUNT(*) AS n
                       FROM closed_pms
                       WHERE close_date IS NOT NULL
                         AND close_date >= CURRENT_DATE - %s::int
                       GROUP BY close_date ORDER BY close_date""",
                    (days,),
                )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def system_breakdown(hospital_code=None):
    """Counts grouped by system/PM type for sorting/grouping."""
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if hospital_code:
                cur.execute(
                    """SELECT COALESCE(system,'(unclassified)') AS system, COUNT(*) AS n
                       FROM closed_pms WHERE hospital_code = %s
                       GROUP BY system ORDER BY n DESC""",
                    (hospital_code,),
                )
            else:
                cur.execute(
                    """SELECT COALESCE(system,'(unclassified)') AS system, COUNT(*) AS n
                       FROM closed_pms GROUP BY system ORDER BY n DESC"""
                )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---- QC ----
def add_qc_review(wo_number, result, score=None, notes=None, reviewer=None,
                  photos=None, asset_type=None, checklist=None):
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO qc_reviews
                       (wo_number, result, score, notes, reviewer, photos,
                        asset_type, checklist)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (wo_number, result, score, notes, reviewer,
                 psycopg2.extras.Json(photos) if photos else None,
                 asset_type,
                 psycopg2.extras.Json(checklist) if checklist else None),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def qc_queue(hospital_code=None, limit=200):
    """Closed PMs and their latest QC status (pending if none)."""
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            wsql = "WHERE p.hospital_code = %s" if hospital_code else ""
            params = ([hospital_code, limit] if hospital_code else [limit])
            cur.execute(
                f"""SELECT p.wo_number, p.hospital_code, p.hospital_name, p.closed_by,
                          p.close_date, p.system, p.procedure, p.reason,
                          p.asset_name, p.location,
                          q.result AS qc_result, q.score AS qc_score, q.created_at AS qc_at
                   FROM closed_pms p
                   LEFT JOIN LATERAL (
                       SELECT result, score, created_at FROM qc_reviews
                       WHERE wo_number = p.wo_number ORDER BY created_at DESC LIMIT 1
                   ) q ON true
                   {wsql}
                   ORDER BY p.close_date DESC NULLS LAST LIMIT %s""",
                params,
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---- Contracts ----
def list_contracts():
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, vendor, hospital_code, scope, start_date, end_date,
                          obligations, notes,
                          (end_date - CURRENT_DATE) AS days_left
                   FROM contracts ORDER BY end_date NULLS LAST"""
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def add_contract(vendor, hospital_code=None, scope=None, start_date=None,
                 end_date=None, obligations=None, notes=None):
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO contracts (vendor, hospital_code, scope, start_date,
                       end_date, obligations, notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (vendor, hospital_code, scope, start_date, end_date,
                 psycopg2.extras.Json(obligations) if obligations else None, notes),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


# ---- Mechanics ----
def ensure_mechanics_from_pms():
    """Auto-seed the mechanics roster from any closed_by names that have
    closed at least one PM but aren't in the roster yet. Idempotent.
    New auto-discovered mechanics default to active=TRUE.
    """
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO mechanics (name)
                   SELECT DISTINCT TRIM(closed_by)
                   FROM closed_pms
                   WHERE closed_by IS NOT NULL AND TRIM(closed_by) <> ''
                   ON CONFLICT (name) DO NOTHING"""
            )
    finally:
        conn.close()


def list_mechanics(hospital_code=None, include_inactive=True):
    """Per-mechanic rollup: who they are, active/inactive, and what they've
    done (today / week / month / total completion counts + last activity).
    Left join so a mechanic with zero recent PMs still shows.
    """
    ensure_mechanics_from_pms()
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where = []
            params = []
            if not include_inactive:
                where.append("m.active = TRUE")
            if hospital_code:
                where.append("(m.hospital_code = %s OR p.hospital_code = %s)")
                params.extend([hospital_code, hospital_code])
            wsql = ("WHERE " + " AND ".join(where)) if where else ""
            pfilter = "AND p.hospital_code = %s" if hospital_code else ""
            if hospital_code:
                params.append(hospital_code)
            cur.execute(
                f"""SELECT m.id, m.name, m.display_name, m.trade,
                          m.hospital_code, m.active, m.left_date, m.notes,
                          COALESCE(x.today,0)  AS today,
                          COALESCE(x.week,0)   AS week,
                          COALESCE(x.month,0)  AS month,
                          COALESCE(x.total,0)  AS total,
                          x.last_close
                   FROM mechanics m
                   LEFT JOIN LATERAL (
                       SELECT
                         COUNT(*) FILTER (WHERE p.close_date = CURRENT_DATE) AS today,
                         COUNT(*) FILTER (WHERE p.close_date >= date_trunc('week', CURRENT_DATE)) AS week,
                         COUNT(*) FILTER (WHERE p.close_date >= date_trunc('month', CURRENT_DATE)) AS month,
                         COUNT(*) AS total,
                         MAX(p.close_date) AS last_close
                       FROM closed_pms p
                       WHERE TRIM(p.closed_by) = m.name {pfilter}
                   ) x ON TRUE
                   {wsql}
                   ORDER BY m.active DESC, x.today DESC NULLS LAST, x.total DESC NULLS LAST, m.name""",
                params,
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def mechanic_detail(name, limit=200):
    """What one mechanic did: their recent closed PMs."""
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT wo_number, hospital_code, hospital_name, close_date,
                          system, procedure, reason, asset_name, location
                   FROM closed_pms
                   WHERE TRIM(closed_by) = %s
                   ORDER BY close_date DESC NULLS LAST, scraped_at DESC
                   LIMIT %s""",
                (name.strip(), limit),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def upsert_mechanic(name, display_name=None, hospital_code=None, trade=None, notes=None):
    """Create or update a mechanic's roster fields (not the active flag)."""
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO mechanics (name, display_name, hospital_code, trade, notes)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (name) DO UPDATE SET
                       display_name  = COALESCE(EXCLUDED.display_name, mechanics.display_name),
                       hospital_code = COALESCE(EXCLUDED.hospital_code, mechanics.hospital_code),
                       trade         = COALESCE(EXCLUDED.trade, mechanics.trade),
                       notes         = COALESCE(EXCLUDED.notes, mechanics.notes),
                       updated_at    = NOW()
                   RETURNING id""",
                (name.strip(), display_name, hospital_code, trade, notes),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def set_mechanic_active(name, active):
    """Mark a mechanic active or inactive (left). Sets left_date when
    deactivating, clears it when reactivating. Auto-creates the roster row
    if the name only existed in closed_pms."""
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO mechanics (name, active, left_date)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (name) DO UPDATE SET
                       active     = EXCLUDED.active,
                       left_date  = CASE WHEN EXCLUDED.active THEN NULL ELSE CURRENT_DATE END,
                       updated_at = NOW()""",
                (name.strip(), bool(active),
                 None if active else __import__("datetime").date.today()),
            )
    finally:
        conn.close()


def recent_pms(limit=25, hospital_code=None):
    """Return the most recently scraped closed PMs for quick inspection."""
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if hospital_code:
                cur.execute(
                    """SELECT wo_number, hospital_code, hospital_name, closed_by,
                              close_date, close_ts, asset_name, asset_model, asset_serial
                       FROM closed_pms WHERE hospital_code = %s
                       ORDER BY scraped_at DESC LIMIT %s""",
                    (hospital_code, limit),
                )
            else:
                cur.execute(
                    """SELECT wo_number, hospital_code, hospital_name, closed_by,
                              close_date, close_ts, asset_name, asset_model, asset_serial
                       FROM closed_pms ORDER BY scraped_at DESC LIMIT %s""",
                    (limit,),
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
