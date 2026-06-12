"""Local dashboard for the job application pipeline.

Run:  .venv\\Scripts\\python app.py   ->  http://localhost:5713
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from pipeline import db

ROOT = Path(__file__).resolve().parent
APPS = ROOT / "data" / "applications"

app = Flask(__name__)


def _folder_for(job_id: int):
    matches = list(APPS.glob(f"{job_id}-*"))
    return matches[0] if matches else None


def _read(folder, name, limit=20000):
    f = folder / name
    if f and f.exists():
        return f.read_text(encoding="utf-8-sig")[:limit]
    return None


@app.route("/")
def dashboard():
    conn = db.connect()
    counts = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM jobs GROUP BY status")}
    total = sum(counts.values())

    queue = [dict(r) for r in conn.execute(
        """SELECT * FROM jobs WHERE status='scored'
           AND COALESCE(llm_score, fit_score) >= 5
           ORDER BY llm_score IS NULL, COALESCE(llm_score, fit_score) DESC
           LIMIT 60""")]
    from pipeline.scoring import posting_age_days
    for job in queue:
        try:
            job["risks"] = json.loads(job["knockout_risks"] or "[]")
        except (json.JSONDecodeError, TypeError):
            job["risks"] = []
        job["age_days"] = posting_age_days(job.get("date_posted"))

    packages = []
    for r in conn.execute(
            """SELECT * FROM jobs WHERE status IN ('reviewed','flagged','packaged','queued','applied')
               ORDER BY CASE status WHEN 'flagged' THEN 0 WHEN 'reviewed' THEN 1
                        WHEN 'packaged' THEN 2 WHEN 'queued' THEN 3 ELSE 4 END,
                        COALESCE(llm_score, fit_score) DESC"""):
        job = dict(r)
        folder = _folder_for(job["id"])
        job["files"] = []
        if folder:
            job["folder"] = folder.name
            job["files"] = sorted(p.name for p in folder.iterdir())
            review = _read(folder, "review.md", 4000) or ""
            job["review_pass"] = "PASS" in review[:40]
            job["review_body"] = review
            job["cover_letter"] = _read(folder, "cover_letter.md", 4000)
        packages.append(job)

    applied = [dict(r) for r in conn.execute(
        "SELECT * FROM jobs WHERE applied_at IS NOT NULL ORDER BY applied_at DESC LIMIT 30")]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    followups = [j for j in applied if j["outcome"] is None and (j["applied_at"] or "") < cutoff]
    for job in followups:
        job["linkedin_search"] = ("https://www.linkedin.com/search/results/people/?keywords="
                                  + quote(job["company"] or ""))

    return render_template(
        "dashboard.html",
        counts=counts, total=total, queue=queue, packages=packages,
        applied=applied, followups=followups,
        now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))


@app.route("/api/jobs/<int:job_id>/<action>", methods=["POST"])
def job_action(job_id, action):
    transitions = {"approve": "queued", "reject": "rejected",
                   "applied": "applied", "unflag": "reviewed"}
    if action not in transitions:
        abort(400)
    conn = db.connect()
    if action == "applied":
        conn.execute("UPDATE jobs SET status='applied', applied_at=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(timespec="seconds"), job_id))
    else:
        conn.execute("UPDATE jobs SET status=? WHERE id=?", (transitions[action], job_id))
    conn.commit()
    return jsonify({"ok": True, "status": transitions[action]})


@app.route("/api/jobs/<int:job_id>/outcome/<result>", methods=["POST"])
def job_outcome(job_id, result):
    if result not in ("response", "interview", "offer", "rejected"):
        abort(400)
    conn = db.connect()
    conn.execute("UPDATE jobs SET outcome=?, outcome_at=? WHERE id=?",
                 (result, datetime.now(timezone.utc).isoformat(timespec="seconds"), job_id))
    conn.commit()
    return jsonify({"ok": True, "outcome": result})


@app.route("/files/<int:job_id>/<path:name>")
def job_file(job_id, name):
    folder = _folder_for(job_id)
    if not folder or not re.fullmatch(r"[\w.\- ]+", name):
        abort(404)
    return send_from_directory(folder, name)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5713, debug=False)
