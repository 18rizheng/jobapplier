"""LLM-score a batch of heuristically-scored backlog jobs (highest first).

Usage:  .venv\\Scripts\\python score_backlog.py [N]
"""

import json
import sys

from pipeline import db, llm

N = int(sys.argv[1]) if len(sys.argv) > 1 else 15


def main():
    profile = json.loads(open("data/profile.json", encoding="utf-8-sig").read())
    conn = db.connect()
    rows = conn.execute(
        """SELECT * FROM jobs WHERE status='scored' AND llm_score IS NULL
           ORDER BY fit_score DESC LIMIT ?""", (N,)).fetchall()
    print(f"scoring {len(rows)} backlog jobs")
    for i, row in enumerate(rows, 1):
        try:
            a = llm.assess_job(dict(row), profile)
        except Exception as exc:
            print(f"  ! [{i}/{len(rows)}] {row['title'][:40]}: {exc}")
            continue
        status = "scored" if a.meets_salary_floor else "rejected"
        conn.execute(
            """UPDATE jobs SET llm_score=?, llm_reason=?, llm_salary_estimate=?,
                   knockout_risks=?, persona=?, status=? WHERE id=?""",
            (a.fit_score, a.reason, a.salary_estimate_usd,
             json.dumps(a.knockout_risks), a.persona, status, row["id"]))
        conn.commit()
        print(f"  [{i}/{len(rows)}] {a.fit_score:>4} {row['title'][:42]:<42} "
              f"{row['company'][:18]:<18} {a.persona}")


if __name__ == "__main__":
    main()
