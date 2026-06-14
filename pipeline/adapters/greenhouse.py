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


def _option_matches(option_text, want):
    """True only when option_text is `want` or `want` followed by a word boundary -
    so 'No' / 'No, I do not' match want='no' but 'Not sure' / 'None' do NOT."""
    opt = option_text.strip().lower()
    want = want.lower()
    return opt == want or (opt.startswith(want) and not opt[len(want):len(want) + 1].isalpha())

STD_WORDS = ("resume", "cover letter", "first name", "last name", "email", "phone", "full name")


def can_submit(report: dict, submit_requested: bool) -> bool:
    """The submission gate: requires explicit intent AND zero unmapped
    required questions. Tested directly - do not inline."""
    return bool(submit_requested) and not report.get("unmapped_required")


SUCCESS_PHRASES = (
    "thank you for applying", "application submitted", "we have received",
    "successfully submitted", "thanks for applying", "application has been",
    "received your application", "your submission",
)


def submission_confirmed(body_text: str, url_changed: bool, form_gone: bool) -> bool:
    """A submission counts as confirmed ONLY with a positive signal: a success
    phrase on the page, or the URL changed AND the upload form is gone. Clicking
    alone is never enough (a false 'applied' is the worst outcome)."""
    body = (body_text or "").lower()
    return any(p in body for p in SUCCESS_PHRASES) or (url_changed and form_gone)


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
            target = next((o for o in options if _option_matches(o, want)), None)
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
            if _option_matches(text, want):
                radio.check()
                return text
        return None

    if tag in ("input", "textarea"):
        control.fill(answer)
        return answer
    return None


def _fill_freeform(page, label, value):
    """Fill a control with an arbitrary proposed value (text, or Yes/No select/radio)."""
    for_id = label.get_attribute("for")
    control = page.locator(f"[id='{for_id}']") if for_id else None
    if not (control and control.count()):
        control = label.locator(
            "xpath=following::*[self::input or self::select or self::textarea][1]")
    if not control.count():
        return None
    control = control.first
    tag = control.evaluate("el => el.tagName.toLowerCase()")
    ctype = (control.get_attribute("type") or "").lower()
    if tag == "select":
        options = control.locator("option").all_inner_texts()
        target = next((o for o in options if o.strip().lower() == value.lower()), None) \
            or next((o for o in options if _option_matches(o, value)), None) \
            or next((o for o in options if value.lower() in o.lower()), None)
        if not target:
            return None
        control.select_option(label=target)
        return target.strip()
    if ctype in ("radio", "checkbox"):
        group = control.get_attribute("name")
        if not group:
            return None
        radios = page.locator(f"input[name='{group}']")
        for i in range(radios.count()):
            rid = radios.nth(i).get_attribute("id")
            rlabel = page.locator(f"label[for='{rid}']").first if rid else None
            text = (rlabel.inner_text().strip() if rlabel and rlabel.count() else "")
            if _option_matches(text, value):
                radios.nth(i).check()
                return text
        return None
    control.fill(value)
    return value


def apply_greenhouse(url, folder: Path, answers: dict, submit: bool = False,
                     headless: bool = True, answer_screening: bool = True,
                     row: dict = None) -> dict:
    """Returns a fill report dict; writes form_filled.png + fill_report.json."""
    from playwright.sync_api import sync_playwright

    contact = answers["contact"]
    bank = dict(answers["answers"])
    bank.setdefault("preferred_name", contact.get("preferred_name", ""))
    bank.setdefault("linkedin", contact.get("linkedin", ""))
    resume = next((p for p in folder.iterdir()
                   if p.name.startswith("resume") and p.suffix in (".pdf", ".docx")), None)
    report = {"url": url, "filled": [], "mapped_questions": [], "proposed_answers": [],
              "unmapped_required": [], "submitted": False}
    # labels (text -> Locator index) kept so a second pass can fill proposed answers
    unmapped_labels = {}

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
                    unmapped_labels[text] = i
            elif required:
                report["unmapped_required"].append(text[:120])
                unmapped_labels[text] = i

        # second pass: LLM-propose grounded answers for the leftover required
        # questions (EEO/category ones were already excluded above)
        if answer_screening and unmapped_labels and row is not None:
            from pipeline import screening
            proposed = screening.answer_questions(list(unmapped_labels), row)
            # the LLM drops the required-marker '*' and trailing punctuation, so
            # match on a normalized key rather than the raw label text
            norm = lambda s: s.rstrip(" *:?").strip().lower()
            by_norm = {norm(k): v for k, v in proposed.items()}
            for text, idx in unmapped_labels.items():
                ans = proposed.get(text) or by_norm.get(norm(text))
                if not ans:
                    continue
                try:
                    set_val = _fill_freeform(page, labels.nth(idx), ans)
                except Exception:
                    set_val = None
                if set_val is not None:
                    report["proposed_answers"].append(f"{text[:70]} = {set_val[:50]!r} [proposed]")
                    trunc = text[:120]
                    if trunc in report["unmapped_required"]:
                        report["unmapped_required"].remove(trunc)

        page.screenshot(path=folder / "form_filled.png", full_page=True)

        if can_submit(report, submit):
            url_before = page.url
            try:
                page.get_by_role("button", name=re.compile("submit", re.I)).first.click()
                page.wait_for_timeout(6000)
            except Exception as exc:
                report["submit_note"] = f"submit click failed: {str(exc)[:120]}"
            page.screenshot(path=folder / "form_submitted.png", full_page=True)
            # NEVER mark submitted without a positive confirmation - a false 'applied'
            # is the worst outcome (job never retried, counter wrongly incremented)
            try:
                body = page.inner_text("body", timeout=3000)
            except Exception:
                body = ""
            confirmed = submission_confirmed(
                body, page.url != url_before,
                page.locator("input[type='file']").count() == 0)
            report["submitted"] = bool(confirmed)
            report["submit_verified"] = confirmed
            if not confirmed:
                report["submit_note"] = (report.get("submit_note", "")
                    + " clicked submit but could not confirm success; verify via "
                      "form_submitted.png").strip()
        browser.close()

    (folder / "fill_report.json").write_text(json.dumps(report, indent=2),
                                             encoding="utf-8-sig")
    return report
