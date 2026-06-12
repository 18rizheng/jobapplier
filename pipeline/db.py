"""SQLite store. Every job ever seen is recorded so reruns never re-surface
or re-apply to the same posting (dedup on normalized company + title)."""

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    dedup_hash TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    is_remote INTEGER,
    salary_min REAL,
    salary_max REAL,
    salary_yearly_min REAL,
    salary_source TEXT,          -- listed | estimated | unknown
    url TEXT,
    source TEXT,                 -- indeed | linkedin | greenhouse:<board> | lever:<org> | ...
    date_posted TEXT,
    description TEXT,
    persona TEXT,                -- technical | analyst_pm | general
    fit_score REAL,
    score_reason TEXT,
    status TEXT NOT NULL DEFAULT 'new',  -- new -> scored -> queued -> applied / rejected / skipped
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(fit_score);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\b(inc|llc|ltd|corp|co|the)\b", "", text)
    text = re.sub(r"\(.*?\)", "", text)          # strip parentheticals like (Remote)
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def dedup_hash(company: str, title: str) -> str:
    return hashlib.md5(f"{_normalize(company)}|{_normalize(title)}".encode()).hexdigest()


def upsert_job(conn: sqlite3.Connection, job: dict) -> bool:
    """Insert a discovered job. Returns True if new, False if already seen
    (in which case only last_seen is touched)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    h = dedup_hash(job["company"], job["title"])
    existing = conn.execute("SELECT id FROM jobs WHERE dedup_hash = ?", (h,)).fetchone()
    if existing:
        conn.execute("UPDATE jobs SET last_seen = ? WHERE id = ?", (now, existing["id"]))
        return False
    conn.execute(
        """INSERT INTO jobs (dedup_hash, title, company, location, is_remote,
               salary_min, salary_max, salary_yearly_min, salary_source,
               url, source, date_posted, description, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (h, job["title"], job["company"], job.get("location"), job.get("is_remote"),
         job.get("salary_min"), job.get("salary_max"), job.get("salary_yearly_min"),
         job.get("salary_source", "unknown"), job.get("url"), job.get("source"),
         job.get("date_posted"), job.get("description"), now, now),
    )
    return True
