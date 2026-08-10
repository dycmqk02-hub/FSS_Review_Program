"""PDF 표 기반 재무제표 간 교차검증(FS간 검증) - 동일 계정과목이 서로 다른 재무제표에
등장할 때(예: 반기순이익은 손익계산서/현금흐름표/자본변동표에, 자본총계는 재무상태표/
자본변동표에 등장) 각 표에서 독립적으로 추출한 당기 값이 서로 일치하는지 대사한다.
각 재무제표를 별도로 재파싱하므로 xbrl_cross_check.py(같은 XBRL fact 재사용)보다
오차 가능성이 높은 휴리스틱이다."""
from .pdf_hierarchy_check import (
    classify_row, _strict_number, _find_note_column, detect_periods, _cell, _concept_key,
    _norm_label, _count_header_rows, _equity_column_roles, gather_statement_tables,
    NET_INCOME_KEYS,
)
from ..pdf_utils import PdfDocument

TOLERANCE_RATIO = 0.001


def _find_current_period(rows: list[list[str]]) -> dict | None:
    note_col = _find_note_column(rows)
    periods = detect_periods(rows, note_col)
    if not periods:
        return None
    if len(periods) <= 2:
        return periods[0]  # 당기/전기 단순 구조(재무상태표/현금흐름표): 왼쪽이 당기
    header_text_by_col: dict[int, str] = {}
    for r in rows[:3]:
        for c, cell in enumerate(r):
            header_text_by_col[c] = header_text_by_col.get(c, "") + _norm_label(cell)
    for p in periods:
        if "누적" in header_text_by_col.get(p["item_col"], "") or "누적" in header_text_by_col.get(p["subtotal_col"], ""):
            return p
    return periods[0]


def _row_current_value(rows: list[list[str]], predicate) -> tuple[float, str] | None:
    """predicate(label)->bool 매칭 행의 당기(가장 왼쪽/누적) 값과 원본 라벨을 반환."""
    period = _find_current_period(rows)
    if period is None:
        return None
    for row in rows:
        label = (row[0] if row else "") or ""
        if not predicate(label):
            continue
        val = _strict_number(_cell(row, period["item_col"]))
        if val is None:
            val = _strict_number(_cell(row, period["subtotal_col"]))
        if val is None:
            continue
        return val, label.strip()
    return None


def _is_net_income_row(rows_kind: str):
    def pred(label: str) -> bool:
        kind, _rk, _f = classify_row(label)
        target_kind = "roman" if rows_kind == "roman" else "paren"
        if kind != target_kind:
            return False
        return _concept_key(label) in NET_INCOME_KEYS
    return pred


def _is_capital_total_row(label: str) -> bool:
    kind, _rk, _f = classify_row(label)
    if kind != "suffix_total":
        return False
    return "자본" in _norm_label(label) and "부채" not in _norm_label(label)


def _equity_net_income_and_capital(rows: list[list[str]]) -> dict:
    """자본변동표에서 (a) '반기순이익'류 증감행의 총계(가장 오른쪽 total 컬럼) (b) 최종 '기말'행의
    총계 값을 추출."""
    header_n = _count_header_rows(rows)
    roles = _equity_column_roles(rows[:header_n])
    total_cols = [c for c, role in roles if role == "total"]
    if not total_cols:
        return {}
    last_total_col = total_cols[-1]
    result: dict = {}
    for row in rows[header_n:]:
        label = (row[0] if row else "") or ""
        if not label.strip():
            continue
        norm = _norm_label(label)
        val = _strict_number(_cell(row, last_total_col))
        if val is None:
            continue
        if _concept_key(label) in NET_INCOME_KEYS:
            result["net_income"] = (val, label.strip())  # 당기 구간이 표에서 나중에 나오므로 계속 갱신
        if "기말" in norm:
            result["ending_equity"] = (val, label.strip())  # 가장 마지막(당기말) 것으로 계속 갱신
    return result


def check_cross_statement_pdf(doc: PdfDocument, tolerance_ratio: float = TOLERANCE_RATIO) -> list[dict]:
    """returns [{"item","values":[{"source","label","value"},...],"diff"}, ...] - 두 개 이상의
    출처에서 값을 찾았고 서로 tolerance 이상 차이나는 항목만 반환."""
    tables = gather_statement_tables(doc)
    findings: list[dict] = []

    is_ni = _row_current_value(tables["손익계산서"], _is_net_income_row("roman"))
    cf_ni = _row_current_value(tables["현금흐름표"], _is_net_income_row("paren"))
    eq = _equity_net_income_and_capital(tables["자본변동표"])
    eq_ni = eq.get("net_income")

    candidates = []
    if is_ni:
        candidates.append(("손익계산서", *is_ni))
    if cf_ni:
        candidates.append(("현금흐름표", *cf_ni))
    if eq_ni:
        candidates.append(("자본변동표", *eq_ni))
    if len(candidates) >= 2:
        base_val = candidates[0][1]
        mismatched = [c for c in candidates if abs(c[1] - base_val) > max(2.0, abs(base_val) * tolerance_ratio)]
        if mismatched:
            findings.append({
                "item": "반기(당기/분기)순이익(손실)",
                "values": [{"source": src, "label": lbl, "value": val} for src, val, lbl in candidates],
                "diff": max(c[1] for c in candidates) - min(c[1] for c in candidates),
            })

    bs_capital = _row_current_value(tables["재무상태표"], _is_capital_total_row)
    eq_capital = eq.get("ending_equity")
    if bs_capital and eq_capital:
        a, a_label = bs_capital
        b, b_label = eq_capital
        if abs(a - b) > max(2.0, abs(a) * tolerance_ratio):
            findings.append({
                "item": "자본총계",
                "values": [
                    {"source": "재무상태표", "label": a_label, "value": a},
                    {"source": "자본변동표", "label": b_label, "value": b},
                ],
                "diff": a - b,
            })

    bs_cash = _row_current_value(tables["재무상태표"], lambda lbl: "현금및현금성자산" in _norm_label(lbl)
                                  and classify_row(lbl)[0] == "plain")
    cf_cash = _row_current_value(tables["현금흐름표"], lambda lbl: classify_row(lbl)[0] == "roman"
                                  and "현금및현금성자산" in _norm_label(lbl) and "기말" in _norm_label(lbl))
    if bs_cash and cf_cash:
        a, a_label = bs_cash
        b, b_label = cf_cash
        if abs(a - b) > max(2.0, abs(a) * tolerance_ratio):
            findings.append({
                "item": "현금및현금성자산(기말)",
                "values": [
                    {"source": "재무상태표", "label": a_label, "value": a},
                    {"source": "현금흐름표", "label": b_label, "value": b},
                ],
                "diff": a - b,
            })

    return findings
