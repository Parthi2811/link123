"""
tools/db.py
Async SQLite database for job tracking — stores status of every job seen/applied.
"""
import aiosqlite
from datetime import datetime
from typing import Optional, List
from loguru import logger
from config.settings import DB_PATH


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT UNIQUE,          -- LinkedIn job ID
    title         TEXT,
    company       TEXT,
    location      TEXT,
    posted_date   TEXT,
    job_url       TEXT,
    description   TEXT,
    easy_apply    INTEGER DEFAULT 0,    -- 1 = Easy Apply available
    status        TEXT DEFAULT 'PENDING',  -- PENDING | TAILORING | APPLIED | SKIPPED | FAILED
    resume_path   TEXT,                 -- Path to tailored resume PDF
    applied_at    TEXT,
    notes         TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    jobs_found  INTEGER,
    applied     INTEGER,
    skipped     INTEGER,
    failed      INTEGER
);
"""


async def init_db() -> None:
    """Create tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLE_SQL)
        await db.commit()
    logger.info(f"✅ Database initialized at {DB_PATH}")


async def job_exists(job_id: str) -> bool:
    """Check if a job has already been seen."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM jobs WHERE job_id = ?", (job_id,))
        return await cur.fetchone() is not None


async def insert_job(job: dict) -> None:
    """Insert a newly found job with PENDING status."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO jobs
            (job_id, title, company, location, posted_date, job_url, description, easy_apply)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["job_id"],
                job["title"],
                job["company"],
                job["location"],
                job.get("posted_date", ""),
                job["job_url"],
                job["description"],
                int(job.get("easy_apply", False)),
            ),
        )
        await db.commit()


async def update_job_status(
    job_id: str,
    status: str,
    resume_path: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    """Update job processing status."""
    async with aiosqlite.connect(DB_PATH) as db:
        applied_at = datetime.utcnow().isoformat() if status == "APPLIED" else None
        await db.execute(
            """
            UPDATE jobs SET status=?, resume_path=?, applied_at=?, notes=?
            WHERE job_id=?
            """,
            (status, resume_path, applied_at, notes, job_id),
        )
        await db.commit()


async def get_pending_jobs(limit: int = 50) -> List[dict]:
    """Fetch PENDING jobs for processing."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM jobs WHERE status='PENDING' ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_stats() -> dict:
    """Return summary counts for the dashboard."""
    async with aiosqlite.connect(DB_PATH) as db:
        counts = {}
        for status in ("PENDING", "APPLIED", "SKIPPED", "FAILED", "TAILORING"):
            cur = await db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status=?", (status,)
            )
            row = await cur.fetchone()
            counts[status] = row[0] if row else 0
        return counts
