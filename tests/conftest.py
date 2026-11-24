import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

NOTICE_V1 = """UNIVERSITY OF EXAMPLE
Notice: Merit Scholarship 2026-27
Applications are invited for the Merit Scholarship for the academic year 2026-27.
Eligibility Criteria:
1. Student must have secured minimum 60% marks in the previous examination.
2. Annual family income should not exceed Rs. 8,00,000.
3. Only for regular students of second and third year.
Documents Required:
- Copy of previous year mark sheet
- Income certificate issued by Tahsildar
- Aadhaar card copy
- Bank passbook first page
Application fee: Rs. 200/- payable online.
The scholarship amount of Rs. 25,000 per annum will be credited to the bank account.
Last date for submission of application: 30/11/2026
"""

NOTICE_V2 = NOTICE_V1.replace("30/11/2026", "15/12/2026").replace("Rs. 200/-", "Rs. 300/-") \
    .replace("- Aadhaar card copy\n", "- Aadhaar card copy\n- Two passport size photographs\n")


def make_pdf(path, pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 560, 800), text, fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


def make_scanned_pdf(path):
    """A page with only an image and no text layer."""
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 60), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(50, 50, 300, 300), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", max_upload_bytes=200_000))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def notice_pdf(tmp_path):
    return make_pdf(tmp_path / "merit_scholarship.pdf", [NOTICE_V1])


@pytest.fixture
def notice_v2_pdf(tmp_path):
    return make_pdf(tmp_path / "merit_scholarship_v2.pdf", [NOTICE_V2])
