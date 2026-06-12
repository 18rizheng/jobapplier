"""LLM job-fit assessment. Reads the full description against the profile,
estimates salary for unlisted postings, and flags knockout risks.

Backends, in order of preference:
1. Anthropic SDK - used when ANTHROPIC_API_KEY is set (in env or .env)
2. claude CLI    - falls back to the local Claude Code subscription
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-opus-4-8"


class JobAssessment(BaseModel):
    fit_score: float                     # 0-10, against the best-fitting persona
    persona: str                         # technical | analyst_pm | general | none
    salary_estimate_usd: Optional[int]   # estimated yearly base if not listed, else null
    meets_salary_floor: bool             # listed or estimated >= the floor
    knockout_risks: list[str]            # e.g. "requires 8+ years", "needs clearance"
    reason: str                          # 1-2 sentences


def _load_dotenv():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


def _build_prompt(job, profile):
    personas = {
        name: {"positioning": p["positioning"], "target_titles": p["target_titles"]}
        for name, p in profile["personas"].items()
    }
    constraints = {
        "min_salary_usd": profile["search_criteria"]["min_salary_usd"],
        "willing_to_relocate": True,
        "requires_sponsorship": False,
        "earliest_start": profile["answer_bank"]["earliest_start_date"]["value"],
    }
    experience_summary = (
        "Candidate: Quality Manager on Epic Systems' EDI team since Sept 2022 (~3.75 yrs). "
        "Owns QA for healthcare integration software (HL7v2, FHIR, EDI); built multi-agent "
        "AI code-review pipelines (Claude Code, Python); quarterly release ownership across "
        "two product teams; requirements gathering with international stakeholders (Denmark); "
        "mentors staff. BS Biochemistry (UCLA 2022); CS capstone certificate in progress (UW-Madison)."
    )
    desc = (job.get("description") or "")[:6000]
    return f"""You are scoring a job posting for fit against a candidate's profile.

CANDIDATE SUMMARY:
{experience_summary}

PERSONAS (pick the single best fit):
{json.dumps(personas, indent=2)}

HARD CONSTRAINTS:
{json.dumps(constraints, indent=2)}

JOB POSTING:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')} (remote: {job.get('is_remote')})
Listed yearly salary minimum: {job.get('salary_yearly_min') or 'NOT LISTED'}
Description:
{desc}

Score fit 0-10 honestly: 8+ means the candidate clearly meets the stated requirements
and the role advances their career; 5-7 is a stretch worth applying to; below 5 is a
poor use of an application. Penalize hard requirements the candidate lacks (years of
experience, specific stacks, degrees, clearances). Seniority both ways: principal/
director-level is out of reach; intern/junior is a step backward. If salary is not
listed, estimate the yearly base for this title/company/location; set
meets_salary_floor accordingly. List knockout risks: screening questions this posting
would likely fail the candidate on."""


_JSON_SCHEMA_NOTE = """

Respond with ONLY a JSON object, no markdown fences, matching exactly:
{"fit_score": <number 0-10>, "persona": "technical|analyst_pm|general|none",
"salary_estimate_usd": <int or null>, "meets_salary_floor": <bool>,
"knockout_risks": [<strings>], "reason": "<1-2 sentences>"}"""


def _run_cli(prompt, model):
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("no ANTHROPIC_API_KEY and no claude CLI on PATH")
    # prompt goes via stdin: Windows argv is capped at ~8K chars
    result = subprocess.run(
        [exe, "-p", "--model", model],
        input=prompt,
        capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr[:500]}")
    return result.stdout


def complete_json(prompt, schema_model, schema_note, model=DEFAULT_MODEL):
    """Run a prompt expecting a structured response validated by `schema_model`.
    `schema_note` is the JSON-shape instruction appended on the CLI path
    (the SDK path enforces the schema natively via structured outputs)."""
    _load_dotenv()
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=model,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
            output_format=schema_model,
        )
        return response.parsed_output
    out = _run_cli(prompt + schema_note, model)
    match = re.search(r"\{.*\}", out, re.DOTALL)
    if not match:
        raise RuntimeError(f"no JSON in CLI output: {out[:300]}")
    return schema_model.model_validate(json.loads(match.group(0)))


def complete_text(prompt, model=DEFAULT_MODEL):
    _load_dotenv()
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )
        return next(b.text for b in response.content if b.type == "text")
    return _run_cli(prompt, model)


def assess_job(job: dict, profile: dict, model: str = DEFAULT_MODEL) -> JobAssessment:
    return complete_json(_build_prompt(job, profile), JobAssessment, _JSON_SCHEMA_NOTE, model)
