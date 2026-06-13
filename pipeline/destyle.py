"""De-AI pass: strip the punctuation and tells that make text read as machine-written.

Deterministic, runs on every generated resume and cover letter so the output is
guaranteed em-dash-free regardless of what the model produced. Style/vocabulary is
handled in the generation prompts; this layer is the mechanical guarantee.
"""

import re

# straight quotes read plainer/more human than the model's curly ones
_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "′": "'"}


def de_ai(text: str) -> str:
    if not text:
        return text
    for curly, straight in _QUOTES.items():
        text = text.replace(curly, straight)
    # numeric ranges keep a hyphen: "40–50%" / "40—50%" / "2022–Present" -> "40-50%"
    text = re.sub(r"(\w)\s*[–—]\s*(\w)",
                  lambda m: m.group(1) + ("-" if (m.group(1).isdigit() or m.group(2).isdigit())
                                          else ", ") + m.group(2), text)
    # any remaining em/en dash (spaced separators, sentence breaks) -> comma
    text = re.sub(r"\s*[–—]\s*", ", ", text)
    text = text.replace("…", "...")          # ellipsis char -> three dots
    text = re.sub(r",\s*,", ",", text)            # collapse accidental double commas
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def sanitize_docx(doc):
    """Apply de_ai to every run in the document, preserving run formatting.
    Covers generated bullets AND any static template text with stray dashes."""
    for para in doc.paragraphs:
        for run in para.runs:
            cleaned = de_ai(run.text)
            if cleaned != run.text:
                run.text = cleaned
