"""Fully autonomous pipeline pass (authorized by Richard, 2026-06-12):
auto-approve everything scoring >= threshold, package it, and submit whatever
the auto lane can reach. Assisted-lane jobs get checklists - login walls are
a hard constraint, not a policy choice.

Usage:  .venv\\Scripts\\python autopilot.py [--threshold 6]
"""

import sys

import apply as apply_mod
import package
from pipeline import db


def _arg(flag, default):
    return type(default)(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


THRESHOLD = _arg("--threshold", 6.0)
MAX_PER_RUN = _arg("--max", 15)  # cap packaging per run so a daily job can't run for hours


def main():
    conn = db.connect()
    # approve the best-scoring jobs first, capped, so a big discovery day doesn't
    # spawn hours of packaging that the scheduled task's time limit would kill mid-run
    ids = [r["id"] for r in conn.execute(
        """SELECT id FROM jobs WHERE status='scored' AND llm_score >= ?
           ORDER BY llm_score DESC LIMIT ?""", (THRESHOLD, MAX_PER_RUN)).fetchall()]
    for job_id in ids:
        conn.execute("UPDATE jobs SET status='queued' WHERE id=?", (job_id,))
    conn.commit()
    print(f"autopilot: auto-approved {len(ids)} jobs at >= {THRESHOLD} (cap {MAX_PER_RUN})")

    package.main()
    if db.autonomy_unlocked(conn):
        apply_mod.main(submit=True)          # past probation: send autonomously
    else:
        apply_mod.main(prepare=True)         # probation: prepare + hold for approval


if __name__ == "__main__":
    main()
