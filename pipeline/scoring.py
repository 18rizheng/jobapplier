"""Scoring v0: heuristic fit score (0-10) per persona, salary gate per design.
LLM scoring (Claude reads the full description against the profile) replaces
this once an ANTHROPIC_API_KEY is configured - see llm_score below.

Salary policy: listed >= floor passes, listed < floor fails, unlisted is
flagged 'unknown' and kept (most postings don't list salary)."""

import re

SENIORITY_PENALTY = ("principal", "staff", "director", "vp", "vice president", "head of")
JUNIOR_PENALTY = ("intern", "internship", "junior", "entry level", "entry-level")


def _tokens(text):
    return set(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


def title_match(title, target_titles):
    """Best token-overlap ratio between the job title and any persona target title."""
    job = _tokens(title)
    if not job:
        return 0.0
    best = 0.0
    for target in target_titles:
        t = _tokens(target)
        if t and t <= job:          # full target contained in job title
            return 1.0
        overlap = len(job & t) / len(t) if t else 0
        best = max(best, overlap)
    return best


def salary_gate(job, floor):
    y = job.get("salary_yearly_min")
    if y is None:
        return "unknown"
    return "pass" if y >= floor else "fail"


def score_job(job, profile):
    """Returns (persona, score 0-10, reason, gate). Heuristic only - v0."""
    floor = profile["search_criteria"]["min_salary_usd"]
    gate = salary_gate(job, floor)
    if gate == "fail":
        return None, 0.0, f"listed salary below ${floor:,}", gate

    best_persona, best_match = None, 0.0
    for name, persona in profile["personas"].items():
        m = title_match(job["title"], persona["target_titles"])
        if m > best_match:
            best_persona, best_match = name, m

    score = best_match * 6.0                          # title fit: 0-6
    reasons = [f"title match {best_match:.0%}"]
    if gate == "pass":
        score += 2.0
        reasons.append("salary listed >= floor")
    else:
        reasons.append("salary unknown")
    if job.get("is_remote"):
        score += 1.0
        reasons.append("remote")

    lowered = (job.get("title") or "").lower()
    if any(k in lowered for k in SENIORITY_PENALTY + JUNIOR_PENALTY):
        score -= 2.0
        reasons.append("seniority mismatch")

    return best_persona, round(max(score, 0.0), 1), "; ".join(reasons), gate


def llm_score(job, profile):
    """TODO: Claude API scoring - full description vs persona positioning,
    salary estimation for unlisted postings, knockout-risk detection.
    Requires ANTHROPIC_API_KEY in .env. Until then score_job() is used."""
    raise NotImplementedError
