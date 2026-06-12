"""Outcome tracker - records what happened so the scorer can learn what works.

Usage:
  track.py applied <id>                mark a job applied (assisted-lane submits)
  track.py outcome <id> <result>       result: response | interview | offer | rejected
  track.py stats                       response rates by persona and score band
"""

import sys
from datetime import datetime, timezone

from pipeline import db


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stats(conn):
    rows = conn.execute(
        """SELECT persona, COALESCE(llm_score, fit_score) AS score, outcome
           FROM jobs WHERE status='applied' OR applied_at IS NOT NULL""").fetchall()
    if not rows:
        print("no applications recorded yet")
        return
    buckets = {}
    for r in rows:
        band = "7+" if (r["score"] or 0) >= 7 else "5-7" if (r["score"] or 0) >= 5 else "<5"
        key = (r["persona"] or "?", band)
        applied, responded = buckets.get(key, (0, 0))
        got_response = r["outcome"] in ("response", "interview", "offer")
        buckets[key] = (applied + 1, responded + (1 if got_response else 0))
    print(f"{'persona':<12} {'score':<6} {'applied':<8} {'responses':<10} rate")
    for (persona, band), (applied, responded) in sorted(buckets.items()):
        rate = f"{responded / applied:.0%}" if applied else "-"
        print(f"{persona:<12} {band:<6} {applied:<8} {responded:<10} {rate}")


def main():
    conn = db.connect()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "applied":
        job_id = int(sys.argv[2])
        conn.execute("UPDATE jobs SET status='applied', applied_at=? WHERE id=?",
                     (now(), job_id))
        conn.commit()
        print(f"job {job_id} marked applied")
    elif cmd == "outcome":
        job_id, result = int(sys.argv[2]), sys.argv[3]
        assert result in ("response", "interview", "offer", "rejected")
        conn.execute("UPDATE jobs SET outcome=?, outcome_at=? WHERE id=?",
                     (result, now(), job_id))
        conn.commit()
        print(f"job {job_id} outcome: {result}")
    else:
        stats(conn)


if __name__ == "__main__":
    main()
