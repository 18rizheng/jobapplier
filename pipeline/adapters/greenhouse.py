"""Greenhouse application-form adapter (auto-submit lane).

Fills standard fields, uploads the resume, pastes the cover letter, and answers
screening questions it can confidently map to locked answer-bank values - via
the label's `for` attribute, handling text inputs, native selects, and radio
groups. Anything required that it cannot confidently fill is listed in the fill
report and BLOCKS submission. Default is a dry run: fill, screenshot, walk away.
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
    (r"salary|total comp|comp expectation|pay expectation|desired compensation", "salary_expectation"),
    (r"clearance", "security_clearance"),
    (r"linkedin", "linkedin"),
    (r"how did you hear|hear about", "how_did_you_hear"),
    (r"^country", "country"),
    (r"location \(city\)|current location|city|location are you|where are you (located|based)", "location_city"),
    (r"years of (relevant |professional )?experience", "years_experience"),
    (r"preferred name", "preferred_name"),
]

# questions that look mappable but need a HUMAN choice - never auto-fill
NEVER_AUTOFILL = re.compile(
    r"best describes|citizenship|visa (status|type)|immigration|race|ethnic|gender|"
    r"veteran|disability|demographic", re.IGNORECASE)

# keys whose canonical answer reduces to yes/no for select/radio controls
YES_NO = {"requires_sponsorship": "no", "work_authorization": "yes",
          "willing_to_relocate": "yes", "security_clearance": "no"}

STD_WORDS = ("resume", "cover letter", "first name", "last name", "email", "phone", "full name")


def can_submit(report: dict, submit_requested: bool) -> bool:
    """The submission gate: requires explicit intent AND zero unmapped
    required questions. Tested directly - do not inline."""
    return bool(submit_requested) and not report.get("unmapped_required")


def _fill_first(page, selectors, value):
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count():
            loc.first.fill(value)
            return True
    return False


def _fill_control(page, label, key, bank):
    """Try to fill the control belonging to `label`.
    Returns the value actually set (for the audit trail), or None on failure."""
    answer = bank.get(key, "")
    if not answer:
        return None
    for_id = label.get_attribute("for")
    control = None
    if for_id:
        control = page.locator(f"[id='{for_id}']")
        if not control.count():
            control = None
    if control is None:
        control = label.locator(
            "xpath=following::*[self::input or self::select or self::textarea][1]")
        if not control.count():
            return None
    control = control.first
    tag = control.evaluate("el => el.tagName.toLowerCase()")
    ctype = (control.get_attribute("type") or "").lower()

    if tag == "select":
        want = YES_NO.get(key)
        options = control.locator("option").all_inner_texts()
        target = None
        if want:
            target = next((o for o in options if o.strip().lower().startswith(want)), None)
        else:
            target = next((o for o in options if answer.lower() in o.lower()
                           or o.strip().lower() in answer.lower()), None)
        if not target:
            return None
        control.select_option(label=target)
        return target.strip()

    if ctype in ("radio", "checkbox"):
        want = YES_NO.get(key)
        if not want:
            return None
        group = control.get_attribute("name")
        if not group:
            return None
        radios = page.locator(f"input[name='{group}']")
        for i in range(radios.count()):
            radio = radios.nth(i)
            rid = radio.get_attribute("id")
            rlabel = page.locator(f"label[for='{rid}']").first if rid else None
            text = (rlabel.inner_text().strip() if rlabel and rlabel.count() else "")
            if text.lower().startswith(want):
                radio.check()
                return text
        return None

    if tag in ("input", "textarea"):
        control.fill(answer)
        return answer
    return None


def apply_greenhouse(url, folder: Path, answers: dict, submit: bool = False,
                     headless: bool = True) -> dict:
    """Returns a fill report dict; writes form_filled.png + fill_report.json."""
    from playwright.sync_api import sync_playwright

    contact = answers["contact"]
    bank = dict(answers["answers"])
    bank.setdefault("preferred_name", contact.get("preferred_name", ""))
    bank.setdefault("linkedin", contact.get("linkedin", ""))
    resume = next((p for p in folder.iterdir()
                   if p.name.startswith("resume") and p.suffix in (".pdf", ".docx")), None)
    report = {"url": url, "filled": [], "mapped_questions": [],
              "unmapped_required": [], "submitted": False}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        for label_text in ("Apply for this job", "Apply Now", "Apply"):
            btn = page.get_by_role("button", name=label_text, exact=False)
            if btn.count() and not page.locator("input[type='file']").count():
                try:
                    btn.first.click(timeout=3000)
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
                break

        first, *rest = contact["full_name"].split()
        std = {
            "first_name": (["#first_name", "input[name='first_name']"], first),
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

        # screening questions: walk labels, resolve controls via for=, fill what maps
        labels = page.locator("label")
        seen = set()
        for i in range(min(labels.count(), 60)):
            label = labels.nth(i)
            try:
                text = label.inner_text(timeout=800).strip()
            except Exception:
                continue
            if not text or text in seen or len(text) > 300:
                continue
            seen.add(text)
            lowered = text.lower()
            if any(w in lowered for w in STD_WORDS):
                continue
            required = "*" in text
            if NEVER_AUTOFILL.search(text):
                if required:
                    report["unmapped_required"].append(text[:120] + " [human only]")
                continue
            matched = next((key for pattern, key in KNOWN_QUESTIONS
                            if re.search(pattern, lowered)), None)
            if matched:
                try:
                    value_set = _fill_control(page, label, matched, bank)
                except Exception:
                    value_set = None
                if value_set is not None:
                    report["mapped_questions"].append(
                        f"{text[:70]} -> {matched} = {value_set[:60]!r}")
                elif required:
                    report["unmapped_required"].append(text[:120])
            elif required:
                report["unmapped_required"].append(text[:120])

        page.screenshot(path=folder / "form_filled.png", full_page=True)

        if can_submit(report, submit):
            page.get_by_role("button", name=re.compile("submit", re.I)).first.click()
            page.wait_for_timeout(5000)
            page.screenshot(path=folder / "form_submitted.png", full_page=True)
            report["submitted"] = True
        browser.close()

    (folder / "fill_report.json").write_text(json.dumps(report, indent=2),
                                             encoding="utf-8-sig")
    return report
