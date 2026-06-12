"""Apply orchestrator - the last mile, over jobs that passed the reviewer gate.

Lanes (per docs/DESIGN.md):
  auto     Greenhouse postings: Playwright fills the form from answers.json,
           uploads the resume, screenshots. DRY RUN by default - it never
           clicks submit unless --submit is passed AND no required question
           was left unmapped.
  assisted everything else (Indeed redirects, Workday, one-off portals):
           writes assist.md checklist into the folder; --open launches the
           posting in your browser alongside it.

Usage:  .venv\\Scripts\\python apply.py [--submit] [--open] [--id N]
"""

import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from pipeline import db
from pipeline.adapters import greenhouse

ROOT = Path(__file__).resolve().parent
APPS = ROOT / "data" / "applications"


def detect_lane(url):
    return "auto" if "greenhouse.io" in (url or "") else "assisted"


def write_assist(folder, row, answers):
    from urllib.parse import quote
    locked = "\n".join(f"- {k}: {v}" for k, v in answers["answers"].items())
    referral = ("https://www.linkedin.com/search/results/people/?keywords="
                + quote(row["company"] or ""))
    (folder / "assist.md").write_text(
        f"# Assisted application: {row['title']} - {row['company']}\n\n"
        f"0. BEFORE applying, check for connections (referrals beat every other channel):\n"
        f"   {referral}\n"
        f"1. Open: {row['url']}\n"
        f"2. Attach: {answers['resume_file']} (in this folder)\n"
        f"3. Cover letter: cover_letter.md (in this folder)\n"
        f"4. Screening answers (locked canonical values):\n{locked}\n\n"
        f"Contact: {answers['contact']['full_name']} | {answers['contact']['email']} | "
        f"{answers['contact']['phone']}\n\n"
        f"After submitting, record it:  .venv\\Scripts\\python track.py applied {row['id']}\n",
        encoding="utf-8-sig")


def main():
    submit = "--submit" in sys.argv
    open_browser = "--open" in sys.argv
    only_id = int(sys.argv[sys.argv.index("--id") + 1]) if "--id" in sys.argv else None

    conn = db.connect()
    rows = conn.execute("SELECT * FROM jobs WHERE status='reviewed'").fetchall()
    if only_id:
        rows = [r for r in rows if r["id"] == only_id]
    print(f"{len(rows)} reviewed jobs ready ({'SUBMIT' if submit else 'dry run'})")

    for row in rows:
        folders = list(APPS.glob(f"{row['id']}-*"))
        if not folders:
            print(f"  ! no folder for job {row['id']}")
            continue
        folder = folders[0]
        answers = json.loads((folder / "answers.json").read_text(encoding="utf-8-sig"))
        lane = detect_lane(row["url"])
        print(f"  [{lane}] {folder.name}")

        if lane == "auto":
            report = greenhouse.apply_greenhouse(
                row["url"], folder, answers, submit=submit, headless=True)
            if report["unmapped_required"]:
                print(f"    blocked - unmapped required questions: "
                      f"{report['unmapped_required']}")
            if report["submitted"]:
                conn.execute(
                    "UPDATE jobs SET status='applied', applied_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(timespec='seconds'), row["id"]))
                conn.commit()
                print("    SUBMITTED")
            else:
                print(f"    filled (dry): see {folder.name}\\form_filled.png")
        else:
            write_assist(folder, row, answers)
            if open_browser:
                webbrowser.open(row["url"])
            print(f"    checklist: {folder.name}\\assist.md")


if __name__ == "__main__":
    main()
