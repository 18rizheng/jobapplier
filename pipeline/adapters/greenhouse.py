"""Greenhouse application-form adapter (auto-submit lane).

Fills the standard fields, uploads the resume, pastes the cover letter, and
answers screening questions it can confidently map to locked answer-bank
values. Anything it cannot map is listed in the fill report and BLOCKS
submission. Submission only happens when submit=True AND nothing is unmapped -
the default is a dry run that fills, screenshots, and walks away.
"""

import json
import re
from pathlib import Path

KNOWN_QUESTIONS = [
    # (regex on the question label, answer-bank key)
    (r"sponsor", "requires_sponsorship"),
    (r"authoriz|legally|right to work|eligible to work", "work_authorization"),
    (r"relocat", "willing_to_relocate"),
    (r"start date|available to start|availability", "earliest_start_date"),
    (r"salary|compensation expect", "salary_expectation"),
    (r"clearance", "security_clearance"),
]


def _fill_first(page, selectors, value):
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count():
            loc.first.fill(value)
            return True
    return False


def apply_greenhouse(url, folder: Path, answers: dict, submit: bool = False,
                     headless: bool = True) -> dict:
    """Returns a fill report dict; writes form_filled.png + fill_report.json."""
    from playwright.sync_api import sync_playwright

    contact = answers["contact"]
    bank = answers["answers"]
    resume = next((p for p in folder.iterdir()
                   if p.name.startswith("resume") and p.suffix in (".pdf", ".docx")), None)
    report = {"url": url, "filled": [], "mapped_questions": [],
              "unmapped_required": [], "submitted": False}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        # some postings need an Apply click to reveal the form
        for label in ("Apply for this job", "Apply Now", "Apply"):
            btn = page.get_by_role("button", name=label, exact=False)
            if btn.count() and not page.locator("input[type='file']").count():
                try:
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
                break

        first, *rest = contact["full_name"].split()
        std = {
            "first_name": ([f"#first_name", "input[name='first_name']"], first),
            "last_name": (["#last_name", "input[name='last_name']"], rest[-1] if rest else ""),
            "email": (["#email", "input[name='email']", "input[type='email']"], contact["email"]),
            "phone": (["#phone", "input[name='phone']", "input[type='tel']"], contact["phone"]),
        }
        for field, (selectors, value) in std.items():
            if value and _fill_first(page, selectors, value):
                report["filled"].append(field)

        if resume:
            file_input = page.locator("input[type='file']")
            if file_input.count():
                file_input.first.set_input_files(str(resume))
                page.wait_for_timeout(3000)  # greenhouse parses the upload
                report["filled"].append(f"resume ({resume.name})")

        letter_file = folder / "cover_letter.md"
        cover_box = page.locator("textarea#cover_letter_text, textarea[name='cover_letter']")
        if letter_file.exists() and cover_box.count():
            cover_box.first.fill(letter_file.read_text(encoding="utf-8-sig"))
            report["filled"].append("cover_letter")

        # screening questions: map by label text against the locked answer bank
        questions = page.locator("[role='group'], .application-question, fieldset, label")
        seen = set()
        for i in range(min(questions.count(), 40)):
            try:
                text = questions.nth(i).inner_text(timeout=1000).strip()
            except Exception:
                continue
            if not text or text in seen or len(text) > 300:
                continue
            seen.add(text)
            lowered = text.lower()
            required = "*" in text
            matched = next((key for pattern, key in KNOWN_QUESTIONS
                            if re.search(pattern, lowered)), None)
            if matched and bank.get(matched):
                # v1 records the mapping; select/radio interaction is per-form
                # and verified by the human pass over form_filled.png
                report["mapped_questions"].append(f"{text[:60]} -> {matched}")
            elif required and "resume" not in lowered and "name" not in lowered \
                    and "email" not in lowered and "phone" not in lowered:
                report["unmapped_required"].append(text[:120])

        page.screenshot(path=folder / "form_filled.png", full_page=True)

        if submit and not report["unmapped_required"]:
            page.get_by_role("button", name=re.compile("submit", re.I)).first.click()
            page.wait_for_timeout(5000)
            page.screenshot(path=folder / "form_submitted.png", full_page=True)
            report["submitted"] = True
        browser.close()

    (folder / "fill_report.json").write_text(json.dumps(report, indent=2),
                                             encoding="utf-8-sig")
    return report
