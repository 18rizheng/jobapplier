"""Remediation loop: regenerate flagged resumes with the reviewer's findings
as hard constraints, then re-review. One retry per job - anything still
flagged stays flagged for human attention (no infinite polish loops).

Usage:  .venv\\Scripts\\python remediate.py
"""

import json
import re
from pathlib import Path

from pipeline import db, reviewer, tailor

ROOT = Path(__file__).resolve().parent
APPS = ROOT / "data" / "applications"


def issues_from_review(folder: Path) -> list[str]:
    review_file = folder / "review.md"
    if not review_file.exists():
        return []
    text = review_file.read_text(encoding="utf-8-sig")
    return re.findall(r"^- (.+)$", text.split("## Notes")[0], re.MULTILINE)


def main():
    profile = json.loads((ROOT / "data" / "profile.json").read_text(encoding="utf-8-sig"))
    conn = db.connect()
    rows = conn.execute("SELECT * FROM jobs WHERE status='flagged'").fetchall()
    print(f"remediating {len(rows)} flagged packages")

    for row in rows:
        folders = list(APPS.glob(f"{row['id']}-*"))
        if not folders:
            continue
        folder = folders[0]
        issues = issues_from_review(folder)
        print(f"  {folder.name}: regenerating with {len(issues)} constraint(s)")
        try:
            plan = tailor.tailor_resume(dict(row), folder / "resume_tailored.docx",
                                        avoid_issues=issues)
            bullets = "\n".join(f"- {b}" for b in plan.experience_bullets)
            (folder / "tailoring.md").write_text(
                f"# Tailoring plan (remediated)\n\n{plan.rationale}\n\n"
                f"## Generated bullets\n{bullets}\n\n"
                f"## Skills lines\n" + "\n".join(f"- {s}" for s in plan.skills_lines)
                + "\n\nRegenerated after reviewer flags; re-reviewed below.\n",
                encoding="utf-8-sig")
            verdict = reviewer.review_package(folder, row, profile)
        except Exception as exc:
            print(f"    ! {exc}")
            continue
        status = "reviewed" if verdict.verdict == "pass" else "flagged"
        conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, row["id"]))
        conn.commit()
        print(f"    -> {status.upper()}")
        for issue in verdict.issues:
            print(f"       - {issue}")


if __name__ == "__main__":
    main()
