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
    raw             JSONB,                     -- full scraped row for forensics
    scraped_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_closed_pms_hospital ON closed_pms (hospital_code);
CREATE INDEX IF NOT EXISTS idx_closed_pms_close_date ON closed_pms (close_date);
CREATE INDEX IF NOT EXISTS idx_closed_pms_closed_by ON closed_pms (closed_by);
"""


def init_db():
    """Create tables/indexes if they don't exist. Idempotent."""
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(SCHEMA)
    finally:
        conn.close()


def upsert_pms(rows):
    """Insert closed-PM rows, deduplicating on wo_number.

    Never double-inserts a PM already stored. Returns a dict with counts
    so the caller can report exactly what happened.

    rows: list of dicts with keys matching the columns below.
    """
    if not rows:
        return {"received": 0, "inserted": 0, "skipped_existing": 0}

    init_db()
    conn = get_conn()
    inserted = 0
    try:
        with conn, conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO closed_pms
                        (wo_number, hospital_code, hospital_name, closed_by,
                         close_date, close_ts, asset_name, asset_model,
                         asset_serial, wo_type, raw)
                    VALUES
                        (%(wo_number)s, %(hospital_code)s, %(hospital_name)s,
                         %(closed_by)s, %(close_date)s, %(close_ts)s,
                         %(asset_name)s, %(asset_model)s, %(asset_serial)s,
                         %(wo_type)s, %(raw)s)
                    ON CONFLICT (wo_number) DO NOTHING
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
                        "raw": psycopg2.extras.Json(r.get("raw") or r),
                    },
                )
                # rowcount is 1 when inserted, 0 when the ON CONFLICT skipped it.
                inserted += cur.rowcount
    finally:
        conn.close()

    return {
        "received": len(rows),
        "inserted": inserted,
        "skipped_existing": len(rows) - inserted,
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


def list_pms(hospital_code=None, limit=500):
    """Full PM rows for the dashboard table, newest target date first."""
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if hospital_code:
                cur.execute(
                    """SELECT wo_number, hospital_code, hospital_name, closed_by,
                              close_date, asset_name, raw
                       FROM closed_pms WHERE hospital_code = %s
                       ORDER BY scraped_at DESC LIMIT %s""",
                    (hospital_code, limit),
                )
            else:
                cur.execute(
                    """SELECT wo_number, hospital_code, hospital_name, closed_by,
                              close_date, asset_name, raw
                       FROM closed_pms ORDER BY scraped_at DESC LIMIT %s""",
                    (limit,),
                )
            return [dict(r) for r in cur.fetchall()]
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
