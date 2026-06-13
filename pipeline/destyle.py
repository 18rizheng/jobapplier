"""De-AI pass: strip the punctuation and tells that make text read as machine-written.

Deterministic, runs on every generated resume and cover letter so the output is
guaranteed em-dash-free regardless of what the model produced. Style/vocabulary is
handled in the generation prompts; this layer is the mechanical guarantee.
"""

import re

# straight quotes read plainer/more human than the model's curly ones
_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "′": "'"}


def de_ai(text: str, tidy: bool = True) -> str:
    """Strip em/en dashes and AI-tell punctuation.
    tidy=True (prose: cover letters): also collapse extra whitespace and strip ends.
    tidy=False (docx runs): leave all whitespace exactly as-is, so tab stops and
    leading/trailing spaces that drive resume layout survive."""
    if not text:
        return text
    for curly, straight in _QUOTES.items():
        text = text.replace(curly, straight)
    # en dash (–) is a compound/range connector -> hyphen, tightening any spaces:
    # "Wisconsin–Madison", "September 2022 – Present", "$115k–$135k"
    text = re.sub(r"(\w)\s*–\s*(\w)", r"\1-\2", text)
    text = text.replace("–", "-")
    # em dash (—) is a clause separator -> comma, unless it joins numbers (a range)
    text = re.sub(r"(\w)\s*—\s*(\w)",
                  lambda m: (f"{m.group(1)}-{m.group(2)}"
                             if (m.group(1).isdigit() or m.group(2).isdigit())
                             else f"{m.group(1)}, {m.group(2)}"), text)
    text = re.sub(r"\s*—\s*", ", ", text)   # leftover em dash at edges -> comma
    text = text.replace("…", "...")          # ellipsis char -> three dots
    if tidy:
        text = re.sub(r",\s*,", ",", text)        # collapse accidental double commas
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = text.strip()
    return text


def sanitize_docx(doc):
    """Apply de_ai to every run in the document, preserving run formatting AND
    whitespace (tabs/spaces that drive layout). Covers generated bullets and any
    static template text with stray dashes."""
    for para in doc.paragraphs:
        for run in para.runs:
            cleaned = de_ai(run.text, tidy=False)
            if cleaned != run.text:
                run.text = cleaned
