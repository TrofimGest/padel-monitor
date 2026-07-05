import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT, title TEXT, description TEXT,
    price_byn REAL, price_usd REAL, price_per_m2 REAL,
    area_m2 REAL, address TEXT, town TEXT, district TEXT, region TEXT,
    property_type TEXT, floor INTEGER, floors INTEGER,
    ceiling_height_m REAL, area_min_m2 REAL, heated INTEGER,
    lat REAL, lon REAL, metro TEXT,
    published_at TEXT, updated_at TEXT,
    images TEXT, attrs TEXT,
    first_seen_at TEXT, last_seen_at TEXT,
    content_hash TEXT, status TEXT DEFAULT 'active',
    UNIQUE(source, source_id)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    ts TEXT, kind TEXT, old_value TEXT, new_value TEXT
);
CREATE TABLE IF NOT EXISTS scores (
    listing_id INTEGER PRIMARY KEY REFERENCES listings(id),
    rule_pass INTEGER, rule_reject_reason TEXT, rule_flags TEXT,
    score INTEGER, llm_verdict TEXT, llm_notes TEXT,
    vision_notes TEXT, final_score INTEGER, judge_notes TEXT, scored_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT, finished_at TEXT, source TEXT,
    ok INTEGER, found INTEGER, new INTEGER, changed INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS reported (
    listing_id INTEGER REFERENCES listings(id),
    report_ts TEXT, kind TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


MIGRATIONS = [
    "ALTER TABLE listings ADD COLUMN area_min_m2 REAL",
    "ALTER TABLE listings ADD COLUMN heated INTEGER",
    "ALTER TABLE scores ADD COLUMN final_score INTEGER",
    "ALTER TABLE scores ADD COLUMN judge_notes TEXT",
    "ALTER TABLE listings ADD COLUMN lat REAL",
    "ALTER TABLE listings ADD COLUMN lon REAL",
]


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for mig in MIGRATIONS:
        try:
            con.execute(mig)
        except sqlite3.OperationalError:
            pass  # колонка уже есть
    return con


def upsert_listing(con, row: dict) -> tuple[int, str]:
    """Возвращает (listing_id, 'new'|'changed'|'seen')."""
    ts = now_iso()
    cur = con.execute(
        "SELECT id, content_hash, price_byn, price_per_m2, status FROM listings "
        "WHERE source=? AND source_id=?", (row["source"], row["source_id"]))
    existing = cur.fetchone()
    cols = [k for k in row if k not in ("source", "source_id")]
    if existing is None:
        con.execute(
            f"INSERT INTO listings (source, source_id, {','.join(cols)}, "
            f"first_seen_at, last_seen_at) VALUES (?,?,{','.join('?'*len(cols))},?,?)",
            [row["source"], row["source_id"]] + [row[c] for c in cols] + [ts, ts])
        lid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute("INSERT INTO events (listing_id, ts, kind) VALUES (?,?, 'new')",
                    (lid, ts))
        return lid, "new"

    lid = existing["id"]
    changed = existing["content_hash"] != row["content_hash"]
    if changed:
        for field_, kind in (("price_byn", "price_change"),
                             ("price_per_m2", "price_per_m2_change")):
            old, new = existing[field_], row.get(field_)
            if old != new and (old or new):
                con.execute(
                    "INSERT INTO events (listing_id, ts, kind, old_value, new_value) "
                    "VALUES (?,?,?,?,?)", (lid, ts, kind, str(old), str(new)))
    sets = ",".join(f"{c}=?" for c in cols)
    con.execute(
        f"UPDATE listings SET {sets}, last_seen_at=?, status='active' WHERE id=?",
        [row[c] for c in cols] + [ts, lid])
    if existing["status"] == "gone":
        con.execute("INSERT INTO events (listing_id, ts, kind) VALUES (?,?, 'returned')",
                    (lid, ts))
    return lid, ("changed" if changed else "seen")


def mark_gone(con, source: str, days_unseen: int = 7) -> int:
    """Активные объявления источника, не виденные N дней, помечаем исчезнувшими."""
    ts = now_iso()
    rows = con.execute(
        "SELECT id FROM listings WHERE source=? AND status='active' "
        "AND last_seen_at < datetime('now', ?)",
        (source, f"-{days_unseen} days")).fetchall()
    for r in rows:
        con.execute("UPDATE listings SET status='gone' WHERE id=?", (r["id"],))
        con.execute("INSERT INTO events (listing_id, ts, kind) VALUES (?,?, 'gone')",
                    (r["id"], ts))
    return len(rows)


def log_run(con, source: str, started: str, ok: bool, found: int, new: int,
            changed: int, error: str = ""):
    con.execute(
        "INSERT INTO runs (started_at, finished_at, source, ok, found, new, changed, error) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (started, now_iso(), source, int(ok), found, new, changed, error))
