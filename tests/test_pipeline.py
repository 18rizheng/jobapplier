"""Unit tests for the non-LLM pipeline layers. Run: .venv\\Scripts\\python -m pytest tests -q"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from package import clean_letter, slugify
from pipeline import db
from pipeline.discovery import _annualize, _s
from pipeline.scoring import salary_gate, score_job, title_match


# ---- discovery normalization ----

def test_nan_coerced_to_empty():
    assert _s(float("nan")) == ""
    assert _s(None) == ""
    assert _s("Acme") == "Acme"


def test_annualize_intervals():
    assert _annualize(55, "hourly") == 55 * 2080
    assert _annualize(10000, "monthly") == 120000
    assert _annualize(120000, "yearly") == 120000
    assert _annualize(None, "yearly") is None
    assert _annualize(float("nan"), "hourly") is None
    assert _annualize(2000, "weekly") == 104000


def test_annualize_unknown_interval_defaults_yearly():
    assert _annualize(90000, "fortnightly") == 90000


# ---- dedup ----

def test_dedup_normalizes_company_suffixes_and_parens():
    a = db.dedup_hash("Acme Inc", "QA Engineer (Remote)")
    b = db.dedup_hash("Acme", "QA Engineer")
    assert a == b


def test_dedup_distinct_titles_differ():
    assert db.dedup_hash("Acme", "QA Engineer") != db.dedup_hash("Acme", "QA Manager")


def test_dedup_unicode_and_symbols():
    h = db.dedup_hash("Café & Co.", "Ingénieur QA — Sénior")
    assert isinstance(h, str) and len(h) == 32


# ---- scoring ----

PROFILE = {
    "search_criteria": {"min_salary_usd": 100000},
    "personas": {
        "technical": {"target_titles": ["QA Engineer", "SDET"]},
        "analyst_pm": {"target_titles": ["Business Analyst"]},
    },
}


def _job(**kw):
    base = {"title": "QA Engineer", "company": "X", "is_remote": False,
            "salary_yearly_min": None, "description": ""}
    base.update(kw)
    return base


def test_salary_gate_pass_fail_unknown():
    assert salary_gate(_job(salary_yearly_min=120000), 100000) == "pass"
    assert salary_gate(_job(salary_yearly_min=60000), 100000) == "fail"
    assert salary_gate(_job(), 100000) == "unknown"


def test_low_salary_rejected():
    persona, score, reason, gate = score_job(_job(salary_yearly_min=50000), PROFILE)
    assert gate == "fail" and score == 0.0


def test_title_match_full_containment():
    assert title_match("Senior QA Engineer (Remote)", ["QA Engineer"]) == 1.0


def test_empty_title_scores_zero():
    persona, score, reason, gate = score_job(_job(title=""), PROFILE)
    assert score >= 0  # must not raise


def test_seniority_penalty():
    _, hi, _, _ = score_job(_job(title="QA Engineer"), PROFILE)
    _, lo, _, _ = score_job(_job(title="Principal QA Engineer"), PROFILE)
    assert lo < hi


# ---- packaging helpers ----

def test_slugify_symbols_only():
    assert slugify("!!!***") == "unknown"
    assert slugify("Lower & Co, LLC.") == "lower-co-llc"


def test_clean_letter_strips_wrapper():
    raw = "Here's the cover letter body:\n\n---\n\nDear team, real content.\n\n---\n\nThat's 10 words."
    assert clean_letter(raw) == "Dear team, real content.\n"


def test_clean_letter_passthrough():
    raw = "Dear team, real content.\n"
    assert clean_letter(raw) == raw


def test_clean_letter_single_separator_unchanged():
    raw = "Intro line here that is long enough to keep.\n---\nMore content."
    assert "More content." in clean_letter(raw)
