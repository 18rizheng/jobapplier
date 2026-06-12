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

THRESHOLD = (float(sys.argv[sys.argv.index("--threshold") + 1])
             if "--threshold" in sys.argv else 6.0)


def main():
    conn = db.connect()
    approved = conn.execute(
        "UPDATE jobs SET status='queued' WHERE status='scored' AND llm_score >= ?",
        (THRESHOLD,)).rowcount
    conn.commit()
    print(f"autopilot: auto-approved {approved} jobs at >= {THRESHOLD}")

    package.main()
    apply_mod.main(submit=True)


if __name__ == "__main__":
    main()
