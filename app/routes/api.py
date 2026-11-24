"""JSON API routes."""
import hashlib
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from app.models import TaskUpdate, TitleUpdate
from app.services.analyzer import analyze_pages, build_tasks, missing_categories
from app.services.compare import compare_facts
from app.services.extractor import ExtractionError, extract_pages, looks_like_pdf
from app.services.report import render_report

router = APIRouter()
CHUNK = 1024 * 1024


def _ctx(request: Request):
    return request.app.state.settings, request.app.state.db


def _doc_or_404(db, doc_id: int) -> dict:
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found.")
    doc["missing"] = missing_categories(doc["facts"])
    return doc


def _safe_name(name: str) -> str:
    base = Path(name or "notice.pdf").name
    return re.sub(r"[^\w.\- ()]+", "_", base)[:150] or "notice.pdf"


@router.post("/documents", status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...)):
    settings, db = _ctx(request)
    filename = _safe_name(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files (.pdf) are accepted.")

    data = bytearray()
    while chunk := await file.read(CHUNK):
        data.extend(chunk)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // (1024 * 1024)} MB limit.")
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if not looks_like_pdf(bytes(data[:1024])):
        raise HTTPException(400, "The file does not look like a PDF (missing %PDF header).")

    sha = hashlib.sha256(data).hexdigest()
    existing = db.find_by_hash(sha)
    if existing:
        return JSONResponse({"id": existing, "duplicate": True,
                             "message": "This exact file was already analysed; showing saved results."}, status_code=200)

    stored_name = f"{uuid.uuid4().hex}.pdf"
    path = settings.upload_dir / stored_name
    path.write_bytes(data)
    try:
        pages = extract_pages(path, settings.max_pages)
    except ExtractionError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc))

    facts = analyze_pages(pages)
    tasks = build_tasks(facts)
    title = Path(filename).stem.replace("_", " ").strip() or "Untitled notice"
    doc_id = db.save_document(title=title, filename=filename, stored_name=stored_name, sha256=sha,
                              size_bytes=len(data), pages=pages, facts=facts, tasks=tasks)
    ocr = [p.page_no for p in pages if p.needs_ocr]
    msg = "Analysis complete."
    if ocr and len(ocr) == len(pages):
        msg = "No selectable text found: this looks like a scanned PDF. OCR is required (not included)."
    elif ocr:
        msg = f"Analysis complete. Pages {', '.join(map(str, ocr))} look scanned and need OCR."
    return {"id": doc_id, "duplicate": False, "message": msg, "ocr_pages": ocr}


@router.get("/documents")
def list_documents(request: Request):
    return request.app.state.db.list_documents()


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, request: Request):
    return _doc_or_404(request.app.state.db, doc_id)


@router.patch("/documents/{doc_id}")
def rename_document(doc_id: int, body: TitleUpdate, request: Request):
    if not request.app.state.db.rename_document(doc_id, body.title.strip()):
        raise HTTPException(404, "Document not found.")
    return {"ok": True}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, request: Request):
    settings, db = _ctx(request)
    stored = db.delete_document(doc_id)
    if stored is None:
        raise HTTPException(404, "Document not found.")
    (settings.upload_dir / stored).unlink(missing_ok=True)
    return {"ok": True}


@router.get("/documents/{doc_id}/pages/{page_no}")
def get_page(doc_id: int, page_no: int, request: Request):
    page = request.app.state.db.get_page(doc_id, page_no)
    if not page:
        raise HTTPException(404, "Page not found.")
    return page


@router.get("/documents/{doc_id}/export.json")
def export_json(doc_id: int, request: Request):
    doc = _doc_or_404(request.app.state.db, doc_id)
    return JSONResponse(doc, headers={"Content-Disposition": f'attachment; filename="noticeiq-{doc_id}.json"'})


@router.get("/documents/{doc_id}/report.html", response_class=HTMLResponse)
def export_report(doc_id: int, request: Request, download: bool = True):
    doc = _doc_or_404(request.app.state.db, doc_id)
    headers = {"Content-Disposition": f'attachment; filename="noticeiq-report-{doc_id}.html"'} if download else {}
    return HTMLResponse(render_report(doc), headers=headers)


@router.get("/tasks")
def list_tasks(request: Request):
    return request.app.state.db.list_tasks()


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate, request: Request):
    task = request.app.state.db.set_task_done(task_id, body.done)
    if not task:
        raise HTTPException(404, "Task not found.")
    return task


@router.get("/compare")
def compare(a: int, b: int, request: Request):
    db = request.app.state.db
    if a == b:
        raise HTTPException(400, "Choose two different documents to compare.")
    doc_a, doc_b = _doc_or_404(db, a), _doc_or_404(db, b)
    return {"a": {"id": a, "title": doc_a["title"]}, "b": {"id": b, "title": doc_b["title"]},
            "changes": compare_facts(doc_a["facts"], doc_b["facts"])}
