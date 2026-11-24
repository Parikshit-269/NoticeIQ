# NoticeIQ

Turns college circulars and scholarship notices (PDF) into evidence-backed action checklists.
Every extracted fact links to its page number and the exact source line. Nothing is guessed:
missing categories are flagged, and uncertain readings are marked low/medium confidence.

## Run (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python init_db.py
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
python -m pytest -q
```

Try it with the two PDFs in `samples/` (upload both, then use **Compare**).

## Features
- PDF upload: extension, `%PDF` header, 10 MB limit, corrupt/password-protected/oversize rejected with clear messages; duplicates detected by SHA-256.
- Page-by-page extraction (PyMuPDF). Pages with images but no text are reported as **needing OCR**.
- Rule-based detection of deadlines (many date formats; DD/MM vs MM/DD ambiguity flagged), eligibility, fees (separates payments, benefit amounts and income limits) and required documents.
- Evidence viewer: click *View evidence* to see the full page text with the source line highlighted.
- Task dashboard with done/overdue/upcoming filters; saved in SQLite (`data/noticeiq.db`).
- Version comparison of dates, fees, eligibility and documents.
- Export to JSON and a standalone HTML report (print to PDF from the browser if needed).

## Layout
`app/routes` API · `app/services` extraction, analysis, comparison, report · `app/db.py` SQLite · `app/static` UI · `tests/` pytest.

Config via env vars: `NOTICEIQ_DATA_DIR`, `NOTICEIQ_MAX_MB`.

## Limitations
- **No OCR.** Scanned pages are detected and reported, not read (would need Tesseract, intentionally not bundled).
- Extraction is rule-based English text matching; unusual layouts (tables, multi-column) may miss or mis-split facts. Always check the evidence.
- Comparison pairs changed deadlines/fees by context-word overlap; heavily reworded notices may show as removed + added instead of "changed".
- Single-user, no authentication.
