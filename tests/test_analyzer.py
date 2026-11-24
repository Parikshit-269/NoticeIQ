from datetime import date

from app.models import PageText
from app.services.analyzer import analyze_pages, build_tasks, missing_categories, parse_amounts, parse_dates
from app.services.compare import compare_facts
from tests.conftest import NOTICE_V1, NOTICE_V2


def _facts(text):
    return analyze_pages([PageText(page_no=1, text=text)])


def test_parse_date_formats():
    cases = {
        "Last date: 30/11/2026": date(2026, 11, 30),
        "on or before 5th December, 2026": date(2026, 12, 5),
        "Deadline: Jan 10, 2027": date(2027, 1, 10),
        "submit by 2026-12-01": date(2026, 12, 1),
        "till 15.08.26": date(2026, 8, 15),
    }
    for line, expected in cases.items():
        assert parse_dates(line)[0][1] == expected, line


def test_invalid_and_ambiguous_dates():
    assert parse_dates("Due 31/02/2026") == []
    _, d, note, _ = parse_dates("Last date 05/06/2026")[0]
    assert d == date(2026, 6, 5) and note  # flagged DD/MM vs MM/DD


def test_parse_amounts():
    assert [a for _, a in parse_amounts("Fee Rs. 1,500/- and ₹ 200")] == [1500.0, 200.0]
    assert parse_amounts("Call 9876543210") == []


def test_full_notice_extraction():
    facts = _facts(NOTICE_V1)
    by = {c: [f for f in facts if f.category == c] for c in ("deadline", "fee", "eligibility", "document")}
    assert [f.normalized for f in by["deadline"]] == ["2026-11-30"]
    assert by["deadline"][0].confidence == "high"
    fees = {f.normalized: f.label for f in by["fee"]}
    assert fees["200.00"].startswith("Fee")
    assert fees["25000.00"].startswith("Benefit")
    assert any("60%" in f.value for f in by["eligibility"])
    assert any("income" in f.value.lower() for f in by["eligibility"])
    docs = " | ".join(f.value.lower() for f in by["document"])
    for word in ("mark sheet", "income certificate", "aadhaar", "passbook"):
        assert word in docs
    assert all(f.page == 1 and f.evidence for f in facts)
    assert missing_categories(facts) == []


def test_missing_categories_reported():
    facts = _facts("General notice: the library will remain closed tomorrow.")
    assert set(missing_categories(facts)) == {"deadline", "eligibility", "fee", "document"}


def test_tasks_generated():
    tasks = build_tasks(_facts(NOTICE_V1))
    assert tasks[0].category == "deadline" and tasks[0].due_date == "2026-11-30"
    assert any(t.category == "fee" and "200" in t.title for t in tasks)
    assert not any(t.category == "fee" and "25,000" in t.title for t in tasks)  # benefits are not payments


def test_compare_detects_changes():
    a = [f.model_dump() for f in _facts(NOTICE_V1)]
    b = [f.model_dump() for f in _facts(NOTICE_V2)]
    diff = compare_facts(a, b)
    assert diff["deadline"]["changed"][0]["after"]["normalized"] == "2026-12-15"
    assert diff["fee"]["changed"][0]["after"]["normalized"] == "300.00"
    assert any("photograph" in f["value"].lower() for f in diff["document"]["added"])


def test_list_section_ends_and_income_limit_not_a_fee():
    facts = _facts(NOTICE_V1)
    docs = [f.value for f in facts if f.category == "document"]
    assert len(docs) == 4, docs  # only the bulleted list items
    limit = next(f for f in facts if f.category == "fee" and f.normalized == "800000.00")
    assert limit.label.startswith("Eligibility limit")
    assert not any("8,00,000" in t.title for t in build_tasks(facts) if t.category == "fee")
