"""PDF 텍스트/표 추출 및 숫자 파싱 유틸리티."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pypdf import PdfReader

try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False

NUMBER_RE = re.compile(r"\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?")
DASH_VALUES = {"-", "–", "−", "‐", "―"}


@dataclass
class PdfDocument:
    path: str
    pages: list[str] = field(default_factory=list)  # 페이지별 텍스트 (1-based 접근은 pages[n-1])
    tables: list[tuple[int, list[list[str]]]] = field(default_factory=list)  # (page_no, rows)

    @property
    def full_text(self) -> str:
        return "\n".join(self.pages)

    def page_count(self) -> int:
        return len(self.pages)


def parse_number(raw: str | None) -> float | None:
    """'1,234' '(1,234)' '-' 등 표 셀 문자열을 숫자로 변환. 파싱 불가 시 None."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if s in DASH_VALUES:
        return 0.0
    s2 = s.replace(",", "").replace(" ", "").replace("원", "").replace("%", "")
    neg = False
    if s2.startswith("(") and s2.endswith(")"):
        neg = True
        s2 = s2[1:-1]
    if s2.startswith("△") or s2.startswith("▲"):
        neg = True
        s2 = s2[1:]
    try:
        val = float(s2)
    except ValueError:
        return None
    return -val if neg else val


def load_pdf(path: str, extract_tables: bool = True) -> PdfDocument:
    doc = PdfDocument(path=path)
    reader = PdfReader(path)
    for page in reader.pages:
        try:
            doc.pages.append(page.extract_text() or "")
        except Exception:
            doc.pages.append("")

    if extract_tables and _HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(path) as pdf:
                for i, page in enumerate(pdf.pages, start=1):
                    for tbl in page.extract_tables() or []:
                        cleaned = [[(c or "").strip() for c in row] for row in tbl]
                        if cleaned:
                            doc.tables.append((i, cleaned))
        except Exception:
            pass  # 표 추출 실패는 치명적이지 않음 - 텍스트 검색은 계속 진행

    return doc


def find_numbers_in_text(text: str) -> list[str]:
    return NUMBER_RE.findall(text)


def find_context_snippets(text: str, keywords: list[str], window: int = 60) -> list[str]:
    """키워드 주변 문맥 스니펫 추출 (참조자료 매칭/근거 표시용)."""
    snippets = []
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text):
            start = max(0, m.start() - window)
            end = min(len(text), m.end() + window)
            snippet = text[start:end].replace("\n", " ").strip()
            snippets.append(snippet)
    return snippets


LABEL_LINE_RE = re.compile(
    r"^(?P<label>[가-힣A-Za-z()·ㆍ\s]{2,30}?)\s+(?P<value>\(?-?\d{1,3}(?:,\d{3})+\)?)\s*$"
)


def build_label_value_index(pages: list[str]) -> dict:
    """'라벨  금액' 형태의 줄들을 스캔해 {정규화라벨: [(값, 페이지)...]} 색인 구축.
    재무제표 본문 vs 주석 간 동일 라벨의 금액이 서로 다르게 나타나는지 스크리닝하는 용도(휴리스틱)."""
    index: dict[str, list[tuple[float, int]]] = {}
    for page_no, text in enumerate(pages, start=1):
        for line in text.splitlines():
            m = LABEL_LINE_RE.match(line.strip())
            if not m:
                continue
            label = re.sub(r"\s+", "", m.group("label"))
            if len(label) < 2:
                continue
            val = parse_number(m.group("value"))
            if val is None:
                continue
            index.setdefault(label, []).append((val, page_no))
    return index
