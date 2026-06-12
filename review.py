"""Review queue: approve or reject scored jobs before anything is prepared.

Usage:  .venv\\Scripts\\python review.py [--min-score 5] [--list]
Keys:   a approve (queue for packaging)   r reject   s skip   o open URL   q quit
"""

import sys
import webbrowser

from pipeline import db


def fmt(row):
    score = row["llm_score"] if row["llm_score"] is not None else row["fit_score"]
    salary = (f"${row['salary_yearly_min']:,.0f}+ listed" if row["salary_yearly_min"]
              else f"~${row['llm_salary_estimate']:,.0f} est" if row["llm_salary_estimate"]
              else "salary unknown")
    lines = [
        f"[{score}] {row['title']} - {row['company']}",
        f"    {row['location'] or '?'} | {salary} | persona: {row['persona']} | {row['source']}",
        f"    {row['llm_reason'] or row['score_reason']}",
    ]
    if row["knockout_risks"] and row["knockout_risks"] not in ("[]", None):
        lines.append(f"    risks: {row['knockout_risks']}")
    lines.append(f"    {row['url']}")
    return "\n".join(lines)


def main():
    min_score = 5.0
    if "--min-score" in sys.argv:
        min_score = float(sys.argv[sys.argv.index("--min-score") + 1])

    conn = db.connect()
    rows = conn.execute(
        """SELECT * FROM jobs WHERE status = 'scored'
           AND COALESCE(llm_score, fit_score) >= ?
           ORDER BY llm_score IS NULL, COALESCE(llm_score, fit_score) DESC""",
        (min_score,)).fetchall()
    print(f"{len(rows)} jobs awaiting review (min score {min_score})\n")

    if "--list" in sys.argv:
        for row in rows:
            print(fmt(row) + "\n")
        return

    approved = rejected = 0
    for i, row in enumerate(rows, 1):
        print(f"--- {i}/{len(rows)} " + "-" * 50)
        print(fmt(row))
        while True:
            choice = input("[a]pprove [r]eject [s]kip [o]pen [q]uit > ").strip().lower()
            if choice == "o":
                webbrowser.open(row["url"])
                continue
            break
        if choice == "q":
            break
        if choice == "a":
            conn.execute("UPDATE jobs SET status='queued' WHERE id=?", (row["id"],))
            approved += 1
        elif choice == "r":
            conn.execute("UPDATE jobs SET status='rejected' WHERE id=?", (row["id"],))
            rejected += 1
        conn.commit()

    print(f"\napproved {approved}, rejected {rejected}. "
          f"Next: .venv\\Scripts\\python package.py")


if __name__ == "__main__":
    main()
