"""Pydantic models shared by services and API."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["deadline", "date", "eligibility", "fee", "document"]
Confidence = Literal["high", "medium", "low"]
CORE_CATEGORIES = ("deadline", "eligibility", "fee", "document")


class PageText(BaseModel):
    page_no: int
    text: str
    needs_ocr: bool = False


class Fact(BaseModel):
    category: Category
    value: str
    normalized: Optional[str] = None  # ISO date for dates, plain number for amounts
    label: str = ""
    page: int
    evidence: str
    confidence: Confidence = "medium"
    note: Optional[str] = None


class Task(BaseModel):
    title: str
    category: str
    due_date: Optional[str] = None
    source_page: Optional[int] = None
    done: bool = False


class TaskUpdate(BaseModel):
    done: bool


class TitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
