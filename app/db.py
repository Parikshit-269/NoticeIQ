"""SQLite persistence (standard-library sqlite3, no ORM)."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.models import Fact, PageText, Task

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    ocr_pages TEXT NOT NULL DEFAULT '',
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL,
    text TEXT NOT NULL,
    needs_ocr INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (document_id, page_no)
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    value TEXT NOT NULL,
    normalized TEXT,
    label TEXT NOT NULL DEFAULT '',
    page INTEGER NOT NULL,
    evidence TEXT NOT NULL,
    confidence TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    due_date TEXT,
    source_page INTEGER,
    done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_facts_doc ON facts(document_id);
CREATE INDEX IF NOT EXISTS idx_tasks_doc ON tasks(document_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def find_by_hash(self, sha256: str) -> int | None:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
            return row["id"] if row else None

    def save_document(self, *, title, filename, stored_name, sha256, size_bytes,
                      pages: list[PageText], facts: list[Fact], tasks: list[Task]) -> int:
        ocr = ",".join(str(p.page_no) for p in pages if p.needs_ocr)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO documents (title, filename, stored_name, sha256, size_bytes, page_count, ocr_pages, uploaded_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (title, filename, stored_name, sha256, size_bytes, len(pages), ocr, now))
            doc_id = cur.lastrowid
            conn.executemany("INSERT INTO pages VALUES (?,?,?,?)",
                             [(doc_id, p.page_no, p.text, int(p.needs_ocr)) for p in pages])
            conn.executemany(
                "INSERT INTO facts (document_id, category, value, normalized, label, page, evidence, confidence, note)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                [(doc_id, f.category, f.value, f.normalized, f.label, f.page, f.evidence, f.confidence, f.note) for f in facts])
            conn.executemany(
                "INSERT INTO tasks (document_id, title, category, due_date, source_page, done) VALUES (?,?,?,?,?,0)",
                [(doc_id, t.title, t.category, t.due_date, t.source_page) for t in tasks])
            return doc_id

    def list_documents(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT d.id, d.title, d.filename, d.page_count, d.ocr_pages, d.uploaded_at,
                  (SELECT COUNT(*) FROM facts f WHERE f.document_id = d.id) AS fact_count,
                  (SELECT COUNT(*) FROM tasks t WHERE t.document_id = d.id) AS task_count,
                  (SELECT COUNT(*) FROM tasks t WHERE t.document_id = d.id AND t.done = 1) AS done_count,
                  (SELECT MIN(due_date) FROM tasks t WHERE t.document_id = d.id AND t.done = 0
                     AND t.due_date IS NOT NULL AND t.due_date >= date('now')) AS next_due
                FROM documents d ORDER BY d.id DESC""").fetchall()
            return [_doc_row(r) for r in rows]

    def get_document(self, doc_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if not row:
                return None
            doc = _doc_row(row)
            doc["facts"] = [dict(r) for r in conn.execute(
                "SELECT * FROM facts WHERE document_id = ? ORDER BY category, page, id", (doc_id,))]
            doc["tasks"] = [_task_row(r) for r in conn.execute(
                "SELECT * FROM tasks WHERE document_id = ? ORDER BY due_date IS NULL, due_date, id", (doc_id,))]
            doc["pages"] = [{"page_no": r["page_no"], "needs_ocr": bool(r["needs_ocr"]), "chars": r["n"]}
                            for r in conn.execute("SELECT page_no, needs_ocr, LENGTH(text) AS n FROM pages"
                                                  " WHERE document_id = ? ORDER BY page_no", (doc_id,))]
            return doc

    def get_page(self, doc_id: int, page_no: int) -> dict | None:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM pages WHERE document_id = ? AND page_no = ?", (doc_id, page_no)).fetchone()
            return {"page_no": r["page_no"], "text": r["text"], "needs_ocr": bool(r["needs_ocr"])} if r else None

    def list_tasks(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("""SELECT t.*, d.title AS document_title FROM tasks t
                JOIN documents d ON d.id = t.document_id
                ORDER BY t.done, t.due_date IS NULL, t.due_date, t.id""").fetchall()
            return [_task_row(r) | {"document_title": r["document_title"]} for r in rows]

    def set_task_done(self, task_id: int, done: bool) -> dict | None:
        with self.connect() as conn:
            cur = conn.execute("UPDATE tasks SET done = ? WHERE id = ?", (int(done), task_id))
            if cur.rowcount == 0:
                return None
            return _task_row(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def rename_document(self, doc_id: int, title: str) -> bool:
        with self.connect() as conn:
            return conn.execute("UPDATE documents SET title = ? WHERE id = ?", (title, doc_id)).rowcount > 0

    def delete_document(self, doc_id: int) -> str | None:
        """Delete a document and return its stored file name so the caller can remove the file."""
        with self.connect() as conn:
            row = conn.execute("SELECT stored_name FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            return row["stored_name"]


def _doc_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d.pop("stored_name", None)
    d.pop("sha256", None)
    d["ocr_pages"] = [int(x) for x in d.get("ocr_pages", "").split(",") if x]
    return d


def _task_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["done"] = bool(d["done"])
    return d
