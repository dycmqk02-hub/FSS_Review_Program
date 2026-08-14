"""재무상태표/손익계산서/자본변동표/현금흐름표 당기 vs 전기(비교표시) 증감분석표 - 휴리스틱.

PDF 표 추출(pdfplumber) 기반이며, 실제 보고서 표 레이아웃이 매우 다양하므로
정확도를 보장하지 않는다. 특히:
- 재무상태표/손익계산서/현금흐름표: 한 행에 숫자열이 2개(당기/전기)면 그대로,
  4개(당기 1구간·2구간 + 전기 1구간·2구간, 예: 3개월/누적)면 앞쪽 절반을 당기,
  뒤쪽 절반을 전기로 간주하여 위치 기준으로 짝짓는다(라벨 의미까지 자동 판별하지 않음).
- 자본변동표: 당기표·전기표가 별도의 표로 나뉘어 있는 것이 일반적이므로, 같은
  페이지 구간에서 인식된 표 중 첫 번째를 당기, 두 번째를 전기로 보고 행 라벨을
  매칭하여 각 행의 마지막 숫자열(통상 '합계')을 비교한다.
"""
import re

from ..pdf_utils import PdfDocument, parse_number

STATEMENT_ORDER = ["재무상태표", "손익계산서", "자본변동표", "현금흐름표"]

STATEMENT_KEYWORDS = {
    "재무상태표": ["재무상태표"],
    "손익계산서": ["손익계산서", "포괄손익계산서"],
    "자본변동표": ["자본변동표"],
    "현금흐름표": ["현금흐름표"],
}

# 주석 섹션 진입으로 보고 통계표 인식을 중단시키는 마커 (재무상태표 내 "(주석4)" 같은
# 인라인 각주와 구분하기 위해 절 제목 성격의 문구만 사용)
NOTE_SECTION_MARKERS = ["재무제표에 대한 주석", "1. 일반사항", "1.일반사항", "일반사항 및 주요 회계정책"]

UNIT_RE = re.compile(r"단위\s*[:：]\s*(원|천\s*원|백만\s*원|억\s*원)")


def detect_unit(full_text: str) -> str | None:
    m = UNIT_RE.search(full_text)
    if not m:
        return None
    return m.group(1).replace(" ", "")


def _classify_page(page_text: str) -> str | None:
    for stmt in STATEMENT_ORDER:
        if any(kw in page_text for kw in STATEMENT_KEYWORDS[stmt]):
            return stmt
    return None


def _classify_pages(pages: list[str]) -> dict[int, str | None]:
    classification = {}
    current = None
    for i, text in enumerate(pages, start=1):
        found = _classify_page(text)
        if found:
            current = found
        elif any(marker in text for marker in NOTE_SECTION_MARKERS):
            current = None
        classification[i] = current
    return classification


def _row_numbers(row: list[str]) -> list[float]:
    nums = []
    for cell in row[1:]:
        v = parse_number(cell)
        if v is not None:
            nums.append(v)
    return nums


def _pair_diff(current: float, prior: float) -> dict:
    diff = current - prior
    pct = (diff / prior) if prior not in (0, None) else None
    return {"current": current, "prior": prior, "diff": diff, "pct": pct}


def _build_rows_from_table(rows: list[list[str]]) -> list[dict]:
    out = []
    for row in rows:
        if not row or not (row[0] or "").strip():
            continue
        label = row[0].strip()
        nums = _row_numbers(row)
        if len(nums) == 2:
            out.append({"label": label, "segment": None, **_pair_diff(nums[0], nums[1])})
        elif len(nums) == 4:
            out.append({"label": label, "segment": "구간1", **_pair_diff(nums[0], nums[2])})
            out.append({"label": label, "segment": "구간2", **_pair_diff(nums[1], nums[3])})
        # 그 외 숫자열 개수(1, 3, 5개 이상)는 당기/전기 짝을 신뢰할 수 없어 건너뜀
    return out


def _last_number_by_label(rows: list[list[str]]) -> dict[str, float]:
    d = {}
    for row in rows:
        if not row or not (row[0] or "").strip():
            continue
        label = row[0].strip()
        nums = _row_numbers(row)
        if nums:
            d[label] = nums[-1]
    return d


def _build_equity_rows(tables: list[list[list[str]]]) -> list[dict]:
    if len(tables) < 2:
        return []
    cur_map = _last_number_by_label(tables[0])
    pri_map = _last_number_by_label(tables[1])
    out = []
    for label, cur_val in cur_map.items():
        if label in pri_map:
            out.append({"label": label, "segment": "합계(마지막 숫자열)", **_pair_diff(cur_val, pri_map[label])})
    return out


def build_variance_tables(doc: PdfDocument) -> dict:
    """returns {statement_name: {"rows": [...], "note": str|None}}"""
    page_class = _classify_pages(doc.pages)
    tables_by_stmt: dict[str, list[list[list[str]]]] = {s: [] for s in STATEMENT_ORDER}
    for page_no, rows in doc.tables:
        stmt = page_class.get(page_no)
        if stmt:
            tables_by_stmt[stmt].append(rows)

    result = {}
    for stmt in STATEMENT_ORDER:
        tables = tables_by_stmt[stmt]
        if not tables:
            result[stmt] = {"rows": [], "note": "해당 재무제표에서 표를 자동 인식하지 못했습니다 (표 없음 또는 인식 실패 - 육안 확인 필요)."}
            continue
        if stmt == "자본변동표":
            rows = _build_equity_rows(tables)
            note = None if rows else ("자본변동표는 당기표·전기표가 별도로 구성되는 경우가 많아 자동 매칭에 "
                                       "실패했습니다. 육안으로 확인해 주십시오.")
        else:
            rows = []
            for t in tables:
                rows.extend(_build_rows_from_table(t))
            note = None if rows else "표에서 당기/전기 숫자열 쌍을 인식하지 못했습니다 (표 구조 상이 - 육안 확인 필요)."
        result[stmt] = {"rows": rows, "note": note}
    return result


def apply_flags(variance_tables: dict, pm_threshold: float | None) -> dict:
    """금액차이(PM 기준) 초과 여부 플래그 부여. 증감률(pct)은 값만 계산해 표시하고 음영은 적용하지 않는다."""
    for data in variance_tables.values():
        for row in data["rows"]:
            row["amount_flag"] = bool(pm_threshold) and abs(row["diff"]) >= pm_threshold
    return variance_tables
