from tests.conftest import make_pdf, make_scanned_pdf


def upload(client, path, name=None, ctype="application/pdf"):
    with open(path, "rb") as fh:
        return client.post("/api/documents", files={"file": (name or path.name, fh, ctype)})


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "NoticeIQ" in r.text


def test_upload_analyze_save_revisit(client, notice_pdf):
    r = upload(client, notice_pdf)
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]

    doc = client.get(f"/api/documents/{doc_id}").json()
    assert doc["page_count"] == 1 and doc["missing"] == []
    deadline = next(f for f in doc["facts"] if f["category"] == "deadline")
    assert deadline["normalized"] == "2026-11-30" and deadline["page"] == 1
    assert "30/11/2026" in deadline["evidence"]

    page = client.get(f"/api/documents/{doc_id}/pages/1").json()
    assert "Last date for submission" in page["text"]

    listed = client.get("/api/documents").json()
    assert listed[0]["id"] == doc_id and listed[0]["fact_count"] == len(doc["facts"])


def test_duplicate_upload_returns_existing(client, notice_pdf):
    first = upload(client, notice_pdf).json()["id"]
    r = upload(client, notice_pdf)
    assert r.status_code == 200 and r.json() == {**r.json(), "id": first, "duplicate": True}


def test_rejects_non_pdf_extension(client, tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hello")
    assert upload(client, p).status_code == 400


def test_rejects_fake_pdf(client, tmp_path):
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"not really a pdf")
    r = upload(client, p)
    assert r.status_code == 400 and "PDF" in r.json()["detail"]


def test_rejects_corrupt_pdf(client, tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"%PDF-1.7\n garbage garbage")
    assert upload(client, p).status_code == 422


def test_rejects_empty_and_oversize(client, tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    assert upload(client, empty).status_code == 400
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"0" * 300_000)
    assert upload(client, big).status_code == 413


def test_scanned_pdf_reported(client, tmp_path):
    r = upload(client, make_scanned_pdf(tmp_path / "scan.pdf"))
    assert r.status_code == 201
    body = r.json()
    assert body["ocr_pages"] == [1] and "OCR" in body["message"]
    doc = client.get(f"/api/documents/{body['id']}").json()
    assert doc["ocr_pages"] == [1] and doc["facts"] == []


def test_task_toggle_and_dashboard(client, notice_pdf):
    doc_id = upload(client, notice_pdf).json()["id"]
    task = client.get(f"/api/documents/{doc_id}").json()["tasks"][0]
    r = client.patch(f"/api/tasks/{task['id']}", json={"done": True})
    assert r.status_code == 200 and r.json()["done"] is True
    all_tasks = client.get("/api/tasks").json()
    assert any(t["id"] == task["id"] and t["done"] for t in all_tasks)
    assert client.patch("/api/tasks/99999", json={"done": True}).status_code == 404
    assert client.patch(f"/api/tasks/{task['id']}", json={"done": "maybe"}).status_code == 422


def test_exports(client, notice_pdf):
    doc_id = upload(client, notice_pdf).json()["id"]
    j = client.get(f"/api/documents/{doc_id}/export.json")
    assert j.status_code == 200 and "attachment" in j.headers["content-disposition"]
    assert j.json()["facts"]
    h = client.get(f"/api/documents/{doc_id}/report.html")
    assert h.status_code == 200 and "Action checklist" in h.text and "30/11/2026" in h.text


def test_compare_endpoint(client, notice_pdf, notice_v2_pdf):
    a = upload(client, notice_pdf).json()["id"]
    b = upload(client, notice_v2_pdf).json()["id"]
    r = client.get(f"/api/compare?a={a}&b={b}")
    assert r.status_code == 200
    assert r.json()["changes"]["deadline"]["changed"]
    assert client.get(f"/api/compare?a={a}&b={a}").status_code == 400


def test_multi_page_page_numbers(client, tmp_path):
    p = make_pdf(tmp_path / "two.pdf", ["Intro page about the event.", "Fee: Rs. 500/-\nLast date: 10 January 2027"])
    doc_id = upload(client, p).json()["id"]
    facts = client.get(f"/api/documents/{doc_id}").json()["facts"]
    assert {f["page"] for f in facts if f["category"] in ("fee", "deadline")} == {2}


def test_delete_and_404(client, notice_pdf):
    doc_id = upload(client, notice_pdf).json()["id"]
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
    assert client.delete(f"/api/documents/{doc_id}").status_code == 404
