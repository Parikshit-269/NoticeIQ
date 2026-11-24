"""Rule-based extraction of deadlines, eligibility, fees and required documents.

Every fact carries the page number and the exact source line as evidence. Rules
are deliberately conservative: anything that cannot be tied to a line of text is
not reported, and ambiguous readings are flagged rather than silently resolved.
"""
import re
from datetime import date

from app.models import CORE_CATEGORIES, Fact, PageText, Task

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH_RE = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
            r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
DATE_PATTERNS = [
    ("dmy_text", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-]*(?:of\s+)?{MONTH_RE}\.?,?[\s\-]+(\d{{4}})\b", re.I)),
    ("mdy_text", re.compile(rf"\b{MONTH_RE}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)),
    ("iso", re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")),
    ("dmy_num", re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})\b")),
]
DEADLINE_RE = re.compile(
    r"last\s+date|deadline|due\s+date|due\s+on|on\s+or\s+before|\bbefore\b|not\s+later\s+than|closing\s+date"
    r"|\bcloses?\b|submi\w*\s+by|\bby\b|\btill\b|\buntil\b|\bupto\b|up\s+to|latest\s+by|extended", re.I)

AMOUNT_RE = re.compile(
    r"(?:₹|\brs\.?|\binr)\s*([\d,]+(?:\.\d{1,2})?)\s*(?:/-)?|\b(\d[\d,]*(?:\.\d{1,2})?)\s*(?:/-|rupees\b)", re.I)
FEE_KW = re.compile(r"\bfees?\b|charges?|payment|\bpay\b|payable|\bfine\b|penalty|deposit|\bcost\b|amount", re.I)
BENEFIT_KW = re.compile(r"scholarship\s+(?:amount|of|worth)|award|stipend|grant|prize|\bper\s+(?:month|annum)\b|will\s+receive", re.I)

LIMIT_KW = re.compile(r"income|not\s+exceed|limit|ceiling|less\s+than|below", re.I)
ELIG_STRONG = re.compile(r"eligib|criteria|\bcgpa\b|\bsgpa\b|\d+(?:\.\d+)?\s*%|percent|annual\s+(?:family\s+)?income"
                         r"|domicile|age\s+limit|not\s+exceed", re.I)
ELIG_WEAK = re.compile(r"\bminimum\b|at\s+least|not\s+less\s+than|must\s+(?:be|have)|should\s+(?:be|have)"
                       r"|only\s+for|open\s+to|applicable\s+to|students?\s+(?:of|from|in)\b", re.I)
DOC_KW = re.compile(r"certificate|mark\s?-?sheets?|aadha+r|photograph|passport\s+size|passbook|\bid\s+card|identity\s+card"
                    r"|\bproof\b|receipt|attested|copy\s+of|copies\s+of|transcript|bona\s?fide|pan\s+card|\bresume\b|\bcv\b", re.I)

HEADINGS = {
    "document": re.compile(r"documents?\s+(?:required|to\s+be|needed|checklist)|required\s+documents|enclos|attach(?:ments?|\s+the\s+following)", re.I),
    "eligibility": re.compile(r"eligibility|who\s+can\s+apply|criteria", re.I),
}
BULLET_RE = re.compile(r"^\s*(?:[\-•●▪◦*·➢✓]|\(?\d{1,2}[.)]|\(?[a-hivx]{1,4}[.)])\s+", re.I)
DATE_LIKE = re.compile(r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}")


def _clean(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _norm_text(text: str) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", text.lower()).strip()


def parse_dates(line: str) -> list[tuple[str, date, str | None, tuple[int, int]]]:
    """Return (matched_text, date, ambiguity_note, span) for every valid date in the line."""
    found, taken = [], []
    for kind, pattern in DATE_PATTERNS:
        for m in pattern.finditer(line):
            if any(m.start() < e and m.end() > s for s, e in taken):
                continue
            note = None
            try:
                if kind == "dmy_text":
                    d = date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
                elif kind == "mdy_text":
                    d = date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
                elif kind == "iso":
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                else:
                    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    y = y + 2000 if y < 100 else y
                    d = date(y, b, a)
                    if a <= 12 and b <= 12 and a != b:
                        note = "Read as DD/MM/YYYY (Indian format); could also be MM/DD."
            except (ValueError, KeyError):
                continue
            if not 1990 <= d.year <= 2100:
                continue
            taken.append((m.start(), m.end()))
            found.append((m.group(0), d, note, (m.start(), m.end())))
    found.sort(key=lambda x: x[3][0])
    return found


def parse_amounts(line: str) -> list[tuple[str, float]]:
    out = []
    for m in AMOUNT_RE.finditer(line):
        raw = m.group(1) or m.group(2)
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if value > 0:
            out.append((m.group(0).strip(), value))
    return out


def _deadline_label(line: str, span: tuple[int, int]) -> str:
    before = line[: span[0]]
    label = re.sub(r"[\s:\-–—,(]+$", "", before).strip()
    label = re.sub(r"\b(on or before|before|by|till|until|upto|up to|is|on|latest by)$", "", label, flags=re.I).strip(" :-–—,")
    if len(label) < 4:
        label = re.sub(r"\s+", " ", line[span[1]:]).strip(" :-–—,.()")
    return _clean(label, 90) or "Deadline"


def _heading_category(line: str) -> str | None:
    stripped = BULLET_RE.sub("", line).strip()
    if len(stripped) > 70 or DATE_LIKE.search(stripped):
        return None
    for cat, pattern in HEADINGS.items():
        if pattern.search(stripped):
            return cat
    return None


def _is_generic_heading(line: str) -> bool:
    s = line.strip()
    return 0 < len(s) <= 60 and (s.endswith(":") or (s.isupper() and len(s) > 3)) and not BULLET_RE.match(s)


def analyze_pages(pages: list[PageText]) -> list[Fact]:
    facts: list[Fact] = []
    seen: set[tuple] = set()

    def add(fact: Fact) -> None:
        key = (fact.category, fact.normalized or _norm_text(fact.value), fact.page)
        if key not in seen:
            seen.add(key)
            facts.append(fact)

    for page in pages:
        section, section_items, bulleted = None, 0, False
        for raw in page.text.splitlines():
            line = raw.strip()
            if not line:
                continue
            evidence = _clean(line)

            heading = _heading_category(line)
            if heading and (line.rstrip().endswith(":") or len(line) < 45 or HEADINGS[heading].match(line)):
                section, section_items, bulleted = heading, 0, False
                # A heading line can still carry content after the colon.
                tail = line.split(":", 1)[1].strip() if ":" in line else ""
                if not tail:
                    continue
            elif _is_generic_heading(line):
                section = None

            # Dates / deadlines
            for text, d, note, span in parse_dates(line):
                is_deadline = bool(DEADLINE_RE.search(line))
                conf = "high" if is_deadline and not note else ("medium" if is_deadline else "low")
                add(Fact(category="deadline" if is_deadline else "date", value=text, normalized=d.isoformat(),
                         label=_deadline_label(line, span) if is_deadline else _clean(line, 90),
                         page=page.page_no, evidence=evidence, confidence=conf, note=note))

            # Amounts
            for text, amount in parse_amounts(line):
                payment = bool(re.search(r"\bfees?\b|payable|\bpay\b|charges?|\bfine\b|deposit", line, re.I))
                benefit = bool(BENEFIT_KW.search(line)) and not payment
                limit = bool(LIMIT_KW.search(line)) and not payment
                has_kw = bool(FEE_KW.search(line)) or benefit or limit
                label = ("Eligibility limit (not a payment)" if limit else
                         "Benefit / award amount" if benefit else "Fee / payment")
                add(Fact(category="fee", value=text, normalized=f"{amount:.2f}", label=label,
                         page=page.page_no, evidence=evidence, confidence="high" if has_kw else "low",
                         note=None if has_kw else "Amount found without a fee keyword; check context."))

            item = BULLET_RE.sub("", line).strip()
            is_bullet = bool(BULLET_RE.match(line))
            if section and bulleted and not is_bullet:
                section = None  # a bulleted list ends at the first non-bullet line
            in_list = section is not None and section_items < 15 and (is_bullet or len(line) <= 120)
            if in_list and is_bullet:
                bulleted = True

            # Eligibility
            if section == "eligibility" and in_list:
                section_items += 1
                add(Fact(category="eligibility", value=_clean(item, 200), page=page.page_no,
                         evidence=evidence, confidence="high"))
            elif ELIG_STRONG.search(line) or (ELIG_WEAK.search(line) and BULLET_RE.match(line)):
                if not AMOUNT_RE.search(line) or re.search(r"income", line, re.I):
                    add(Fact(category="eligibility", value=_clean(item, 200), page=page.page_no, evidence=evidence,
                             confidence="high" if ELIG_STRONG.search(line) else "medium"))

            # Required documents
            if section == "document" and in_list:
                section_items += 1
                add(Fact(category="document", value=_clean(item, 200), page=page.page_no,
                         evidence=evidence, confidence="high"))
            elif DOC_KW.search(line) and len(line) <= 160 and not ELIG_STRONG.search(line):
                add(Fact(category="document", value=_clean(item, 200), page=page.page_no, evidence=evidence,
                         confidence="medium", note="Detected by keyword, outside a 'documents required' list."))
    return facts


def missing_categories(facts: list[Fact] | list[dict]) -> list[str]:
    present = {f["category"] if isinstance(f, dict) else f.category for f in facts}
    return [c for c in CORE_CATEGORIES if c not in present]


def build_tasks(facts: list[Fact]) -> list[Task]:
    tasks: list[Task] = []
    for f in sorted((f for f in facts if f.category == "deadline"), key=lambda f: f.normalized or ""):
        tasks.append(Task(title=f"Deadline: {f.label}", category="deadline", due_date=f.normalized, source_page=f.page))
    for f in facts:
        if f.category == "fee" and f.label.startswith("Fee"):
            tasks.append(Task(title=f"Pay {f.value} — {_clean(f.evidence, 80)}", category="fee", source_page=f.page))
    for f in facts:
        if f.category == "document":
            tasks.append(Task(title=f"Arrange document: {f.value}", category="document", source_page=f.page))
    for f in facts:
        if f.category == "eligibility":
            tasks.append(Task(title=f"Confirm eligibility: {f.value}", category="eligibility", source_page=f.page))
    return tasks
