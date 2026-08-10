"""PDF 표/텍스트 기반 주석(note) 공시 대사.

(1) 재무제표 각 계정과목 행의 '주석' 컬럼 번호가 가리키는 주석 섹션을 찾아, 그 주석의
    본문/표 안에 재무제표 금액과 같은 숫자가 실제로 등장하는지 확인한다. 주석의 '합계행'을
    구조적으로 특정하려면 표 레이아웃을 회사마다 별도로 다뤄야 해 신뢰도가 낮아지므로,
    "해당 금액이 그 주석 안에 실제로 등장하는가"를 확인하는 방식을 사용한다(오탐이 적고,
    존재하지 않으면 공시 추적이 안 되는 것이므로 그 자체로 의미 있는 신호).
(2) 주석 섹션 내의 모든 표에도 재무제표와 동일한 계층별 합계검증(로마자/괄호숫자/총계류
    라벨 기반, pdf_hierarchy_check.py의 엔진 재사용)을 적용한다.
"""
import re

from ..pdf_utils import PdfDocument, find_numbers_in_text, parse_number
from .pdf_hierarchy_check import (
    _find_note_column, detect_periods, _resolve_groups, _cell, _strict_number,
    gather_statement_tables,
)
from .variance_analysis import STATEMENT_ORDER

TOLERANCE_RATIO = 0.001
NOTE_HEADING_RE = re.compile(r"(?m)^\s*(\d{1,2})\.(?!\d)\s*([가-힣A-Za-z()·ㆍ0-9 ]{2,24})\s*$")


def parse_note_sections(doc: PdfDocument) -> dict[int, dict]:
    """returns {note_num: {"title","page_start","page_end","text"}}. 번호가 1부터 연속으로
    증가하는 최상위 제목 줄만 인정한다(하위번호 '1.1' 등은 정규식 자체에서 배제됨). 주석
    시작 문구는 "재무제표에 대한 주석"/"1. 일반사항" 등으로 회사·보고서 종류(연결/별도)마다
    표현이 달라 신뢰할 수 없으므로(예: 별도재무제표는 '1. 당사의 개요') 특정 문구를 트리거로
    쓰지 않고, 문서 전체에서 1부터 연속으로 증가하는 제목 시퀀스 자체를 주석 섹션으로 본다."""
    headings: list[tuple[int, int, str]] = []
    last_num = 0
    for i, page_text in enumerate(doc.pages, start=1):
        for m in NOTE_HEADING_RE.finditer(page_text):
            num = int(m.group(1))
            if num != last_num + 1:
                continue
            headings.append((i, num, m.group(2).strip()))
            last_num = num

    sections: dict[int, dict] = {}
    for idx, (page_no, num, title) in enumerate(headings):
        page_end = headings[idx + 1][0] if idx + 1 < len(headings) else len(doc.pages)
        text = "\n".join(doc.pages[page_no - 1:page_end])
        sections[num] = {"title": title, "page_start": page_no, "page_end": page_end, "text": text}
    return sections


def _extract_labeled_items(rows: list[list[str]]) -> list[dict]:
    """[{"label","note_nums":[int,...],"value"}] - 당기 컬럼 값과 주석번호(주석 컬럼)."""
    note_col = _find_note_column(rows)
    if note_col is None:
        return []
    periods = detect_periods(rows, note_col)
    if not periods:
        return []
    p = periods[0]
    out = []
    for row in rows:
        label = (row[0] if row else "") or ""
        if not label.strip():
            continue
        note_cell = row[note_col] if note_col < len(row) else ""
        note_nums = [int(x) for x in re.findall(r"\d+", note_cell or "")]
        if not note_nums:
            continue
        val = _strict_number(_cell(row, p["item_col"]))
        if val is None:
            val = _strict_number(_cell(row, p["subtotal_col"]))
        if val is None:
            continue
        out.append({"label": label.strip(), "note_nums": note_nums, "value": val})
    return out


def _value_in_text(text: str, target: float, tolerance_ratio: float) -> bool:
    tol = max(2.0, abs(target) * tolerance_ratio)
    for raw in find_numbers_in_text(text):
        v = parse_number(raw)
        if v is not None and abs(v - target) <= tol:
            return True
    return False


def check_note_amount_tracing(doc: PdfDocument, tolerance_ratio: float = TOLERANCE_RATIO) -> dict:
    """returns {"confirmed": n, "unmatched": [{"stmt","label","value","notes":[...]}]}."""
    sections = parse_note_sections(doc)
    if not sections:
        return {"confirmed": 0, "unmatched": []}
    tables = gather_statement_tables(doc)
    confirmed = 0
    unmatched = []
    for stmt in STATEMENT_ORDER:
        for item in _extract_labeled_items(tables.get(stmt, [])):
            checked_notes = []
            found = False
            for num in item["note_nums"]:
                sec = sections.get(num)
                if not sec:
                    continue
                checked_notes.append(f"{num}. {sec['title']}")
                if _value_in_text(sec["text"], item["value"], tolerance_ratio):
                    found = True
                    break
            if not checked_notes:
                continue
            if found:
                confirmed += 1
            else:
                unmatched.append({"stmt": stmt, "label": item["label"], "value": item["value"],
                                   "notes": checked_notes})
    return {"confirmed": confirmed, "unmatched": unmatched}


def check_note_tables_hierarchy(doc: PdfDocument) -> list[dict]:
    """주석 섹션 내 모든 표에 계층별 합계검증(로마자/괄호숫자/총계류) 엔진을 재사용 적용."""
    sections = parse_note_sections(doc)
    if not sections:
        return []
    findings = []
    for note_num, sec in sections.items():
        note_tables = [rows for page_no, rows in doc.tables
                        if sec["page_start"] <= page_no <= sec["page_end"]]
        for rows in note_tables:
            note_col = _find_note_column(rows)
            periods = detect_periods(rows, note_col)
            for i, p in enumerate(periods):
                period_label = "당기" if i == 0 else ("전기" if i == 1 else None)
                # 주석 표는 구조가 매우 다양해(카테고리별 소계, 다통화 표 등) 로마자/괄호 계층이
                # 없는 '평범한 항목행 -> 합계' 형태까지 검증하면 오탐이 크게 늘어남이 실측으로
                # 확인됨. 재무제표 4종과 달리 신뢰도를 위해 로마자/괄호 계층이 명확한 경우만 검증.
                res = _resolve_groups(rows, p["item_col"], p["subtotal_col"], period_label=period_label,
                                       allow_flat_backward=False)
                for m in res["mismatches"]:
                    m2 = dict(m)
                    m2["note"] = f"{note_num}. {sec['title']}"
                    findings.append(m2)
    return findings
