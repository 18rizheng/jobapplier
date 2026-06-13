"""Skill-gap report: what to learn to unlock the most jobs.

Every LLM-scored job stores knockout_risks - the specific gaps that held its
fit score down. This aggregates those across the scored backlog, surfaces the
most frequent gaps, and asks the LLM for a ranked learning plan tied to how
many jobs each skill would unlock. Output: data/upskill_report.md (shown on
the dashboard).

Usage:  .venv\\Scripts\\python upskill.py [--min-score 4]
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from pipeline import db, llm

ROOT = Path(__file__).resolve().parent

# normalize gap phrasings to a canonical skill/theme for counting
CANON = [
    (r"\bjava\b", "Java"),
    (r"\bselenium\b", "Selenium"),
    (r"\btypescript\b|\bjavascript\b|\bjs\b", "JavaScript/TypeScript"),
    (r"\bplaywright\b", "Playwright (named)"),
    (r"\bappium\b", "Appium / mobile testing"),
    (r"\bperformance|load test|jmeter|loadrunner", "Performance/load testing"),
    (r"\bpmp\b|\bcsm\b|scrum master cert|certification", "PM certification (PMP/CSM)"),
    (r"\b5\+ years|\b6\+ years|\b7\+ years|\b8\+ years|\byears of experience", "More years of experience"),
    (r"\bmaster|\bphd|\bms\b|advanced degree", "Advanced degree"),
    (r"\bsql|\bsas\b|tableau|power ?bi|data warehouse|etl", "SQL/BI/data-warehouse"),
    (r"\bsalesforce", "Salesforce"),
    (r"\bjira\b", "Jira"),
    (r"\bkubernetes|\bk8s\b|\bdocker\b|\bterraform\b|\baws\b|\bcloud\b", "Cloud/DevOps (AWS/K8s)"),
    (r"\bc#\b|\b\.net\b", "C#/.NET"),
    (r"medicaid|mmis| erp|oracle|workday", "Specific domain/ERP system"),
]


def canon(text):
    low = text.lower()
    hits = [label for pat, label in CANON if re.search(pat, low)]
    return hits or ["Other: " + text[:60]]


def main():
    min_score = float(sys.argv[sys.argv.index("--min-score") + 1]) if "--min-score" in sys.argv else 4.0
    conn = db.connect()
    rows = conn.execute(
        "SELECT title, knockout_risks, llm_score FROM jobs WHERE llm_score >= ? AND knockout_risks IS NOT NULL",
        (min_score,)).fetchall()

    gap_counts = Counter()
    gap_examples = {}
    for r in rows:
        try:
            risks = json.loads(r["knockout_risks"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        seen = set()
        for risk in risks:
            for label in canon(risk):
                if label in seen:
                    continue
                seen.add(label)
                gap_counts[label] += 1
                gap_examples.setdefault(label, risk[:100])

    ranked = [g for g in gap_counts.most_common(15) if not g[0].startswith("Other")]
    if not ranked:
        print("no scored jobs with knockout risks yet - run scoring first")
        return

    table = "\n".join(f"- {label}: appears as a gap in {n} of {len(rows)} jobs "
                      f"(e.g. \"{gap_examples[label]}\")" for label, n in ranked)
    prompt = f"""Based on this aggregated skill-gap data across {len(rows)} job postings a
candidate scored well on but didn't perfectly fit, write a concise upskilling plan.
The candidate is a QA Manager with Python/AI-automation and healthcare-integration
experience. For the top 3-4 gaps that would unlock the most jobs, give: the skill, why
it matters, a concrete fastest-path way to gain credible experience with it (specific
courses/projects), and a rough time estimate. Prioritize by jobs-unlocked-per-effort.
Plain markdown, no preamble.

GAP FREQUENCY DATA:
{table}"""
    try:
        plan = llm.complete_text(prompt).strip()
    except Exception as exc:
        plan = f"(LLM plan unavailable: {exc})"

    report = (f"# Upskill report\n\nAcross {len(rows)} well-scored jobs, ranked by how "
              f"often each gap appears:\n\n{table}\n\n## Learning plan\n\n{plan}\n")
    out = ROOT / "data" / "upskill_report.md"
    out.write_text(report, encoding="utf-8-sig")
    print(f"wrote {out}")
    print("\nTop gaps:")
    for label, n in ranked[:6]:
        print(f"  {n:>3} jobs  {label}")


if __name__ == "__main__":
    main()
