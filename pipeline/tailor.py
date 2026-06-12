"""Constrained resume tailoring (design rule, agreed 2026-06-11).

For jobs scoring >= 7, render a per-job variant of the general docx template.
Tailoring may ONLY reorder existing bullets - the LLM returns a permutation of
bullet indices, validated strictly, and python-docx moves the XML elements.
No text is generated into the resume, so fabrication is structurally impossible.
"""

from pathlib import Path

from pydantic import BaseModel

from . import llm

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "data" / "resumes" / "general.docx"


class TailoringPlan(BaseModel):
    experience_order: list[int]   # permutation of all experience-bullet indices
    skills_order: list[int]       # permutation of all skills-bullet indices
    rationale: str                # 1-2 sentences, shown in the review diff


_SCHEMA_NOTE = """

Respond with ONLY a JSON object, no markdown fences, matching exactly:
{"experience_order": [<every experience index exactly once, best-leading-first>],
"skills_order": [<every skills index exactly once>], "rationale": "<1-2 sentences>"}"""


def _bullet_blocks(doc):
    """Contiguous runs of List Paragraph bullets. In the general template:
    block 0 = experience, block 1 = skills, block 2 = leadership (untouched)."""
    blocks, current = [], []
    for p in doc.paragraphs:
        if p.style is not None and p.style.name == "List Paragraph" and p.text.strip():
            current.append(p)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _reorder(paragraphs, order):
    elements = [p._p for p in paragraphs]
    anchor = elements[0].getprevious()
    parent = elements[0].getparent()
    for el in elements:
        parent.remove(el)
    prev = anchor
    for idx in order:
        if prev is None:
            parent.insert(0, elements[idx])
        else:
            prev.addnext(elements[idx])
        prev = elements[idx]


def _validate(order, n, label):
    if sorted(order) != list(range(n)):
        raise ValueError(f"{label} is not a permutation of 0..{n - 1}: {order}")


def tailor_resume(job: dict, out_path: Path, model: str = llm.DEFAULT_MODEL) -> TailoringPlan:
    """Write a tailored copy of the general template to out_path. Returns the plan."""
    from docx import Document

    doc = Document(TEMPLATE)
    blocks = _bullet_blocks(doc)
    experience, skills = blocks[0], blocks[1]

    exp_lines = "\n".join(f"{i}: {p.text[:200]}" for i, p in enumerate(experience))
    skill_lines = "\n".join(f"{i}: {p.text[:200]}" for i, p in enumerate(skills))
    prompt = f"""Reorder resume bullets to lead with what this job posting values most.
You may ONLY reorder - every index appears exactly once, nothing added or removed.

JOB POSTING:
Title: {job.get('title')}
Company: {job.get('company')}
Description:
{(job.get('description') or '')[:4000]}

EXPERIENCE BULLETS:
{exp_lines}

SKILLS BULLETS:
{skill_lines}"""

    plan = llm.complete_json(prompt, TailoringPlan, _SCHEMA_NOTE, model)
    _validate(plan.experience_order, len(experience), "experience_order")
    _validate(plan.skills_order, len(skills), "skills_order")

    _reorder(experience, plan.experience_order)
    _reorder(skills, plan.skills_order)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return plan
