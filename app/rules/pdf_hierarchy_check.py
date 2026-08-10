"""PDF 표(pdfplumber) 기반 재무제표별 합계검증 - 휴리스틱(오탐 가능, XBRL 대비 정확도 낮음).

재무제표별로 레이아웃/검증 규칙이 서로 다름 (실제 하림 반기(연결/별도)검토보고서 표를
직접 추출해 확인한 결과 기준):

- 재무상태표: "Ⅰ./I." 로마자 소계행은 세부항목 컬럼과 "다른" 컬럼에 forward 방식으로
  값이 미리 찍혀 있고(그 아래 세부항목들의 합), "OO총계"(합계/소계/총계/계로 끝나는 라벨)
  행은 그 앞의 로마자 소계행들의 합을 같은 컬럼에 backward 방식으로 담는다.
- 현금흐름표: 재무상태표와 동일한 forward 로마자 패턴 위에 "(1)/(2)..." 괄호숫자로 된
  중간소계가 한 단계 더 있고(세부항목과 같은 컬럼), 로마자 합계 행 자체에 "(Ⅰ+Ⅱ+Ⅲ+Ⅳ)"
  처럼 수식이 라벨에 그대로 적혀 있는 경우가 있으며, "기말"행은 "기초"행 + 그 직전
  로마자(순증감)행의 합이다.
- 손익계산서: 로마자 소계행이 있지만 "위 항목들의 합"이 아니라 직전 소계 ± 다음 항목의
  가감 체인(예: 매출총이익=매출액-매출원가)이라 고정 수식 그래프로 검증한다. 회사마다
  "이익(손실)"/"손익"/"지배기업소유지분"/"지배주주지분" 등 표현이 달라 키워드 포함 매칭을
  사용한다.
- 자본변동표: 행=증감 이벤트, 열=자본구성요소. (a) 가로: 소계/총계 컬럼 = 그 앞 구성요소
  컬럼들의 합 (b) 세로: '기말' 행 = '기초' 행 + 그 사이 증감행들의 합(컬럼별).

결과 형태는 XBRL 검증(xbrl_calc_check.py)과 동일하게 맞춰 같은 렌더러를 재사용한다:
{stmt: {"mismatches": [...], "skipped": [...], "note": str|None}}
"""
import re

from ..pdf_utils import PdfDocument
from .variance_analysis import STATEMENT_ORDER

TOLERANCE_RATIO = 0.001
# 구조가 다양한 주석(note) 표에서 그룹 경계를 잘못 잡아 전혀 무관한 항목까지 합산되는 경우를
# 걸러내기 위한 안전장치: 기재값 대비 차이가 이 비율을 넘으면 '실제 불일치'가 아니라 '표 구조
# 오인식'으로 보고 결과에서 제외한다 (검토·감사를 통과한 재무제표의 진짜 합계 오류는 통상
# 반올림 수준의 작은 차이이지 몇 배씩 차이나지 않는다).
MAX_PLAUSIBLE_DIFF_RATIO = 0.5

DASH_VALUES = {"-", "–", "−", "‐", "―"}
_STRICT_NUM_RE = re.compile(r"^\d{1,3}(,\d{3})*(\.\d+)?$")

UNICODE_ROMAN_MAP = {
    "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
    "Ⅵ": "VI", "Ⅶ": "VII", "Ⅷ": "VIII", "Ⅸ": "IX", "Ⅹ": "X",
    "Ⅺ": "XI", "Ⅻ": "XII",
}
_ROMAN_PREFIX_RE = re.compile(
    r"^(?P<num>[IVXLCDM]+|[Ⅰ-Ⅻ]+)\s*\.\s*"
)
_PAREN_NUM_PREFIX_RE = re.compile(r"^\((?P<num>\d+)\)\s*")
_FORMULA_RE = re.compile(r"\(\s*([IVXLCDMⅠ-Ⅻ]+(?:\s*[+\-]\s*[IVXLCDMⅠ-Ⅻ]+)+)\s*\)")
_FORMULA_TOKEN_RE = re.compile(r"([+\-]?)\s*([IVXLCDM]+|[Ⅰ-Ⅻ]+)")


def _normalize_roman(num: str) -> str:
    return UNICODE_ROMAN_MAP.get(num, num)


def _norm_label(label: str) -> str:
    return re.sub(r"\s+", "", label or "")


def _is_suffix_total(label: str) -> bool:
    s = _norm_label(label)
    return bool(s) and (s.endswith("합계") or s.endswith("소계") or s.endswith("총계") or s == "계")


def classify_row(label: str) -> tuple[str, str | None, list[tuple[int, str]] | None]:
    """returns (kind, roman_key, formula_tokens).
    kind ∈ {"roman", "paren", "suffix_total", "plain"}.
    roman_key: 정규화된(ASCII) 로마자 표기 (kind=="roman"일 때만).
    formula_tokens: 라벨에 "(Ⅰ+Ⅱ-Ⅲ)" 형태의 수식이 있으면 [(sign, roman_key), ...]."""
    s = (label or "").strip()
    m = _ROMAN_PREFIX_RE.match(s)
    if m:
        roman_key = _normalize_roman(m.group("num"))
        formula_tokens = None
        fm = _FORMULA_RE.search(s)
        if fm:
            tokens = []
            for sign, num in _FORMULA_TOKEN_RE.findall(fm.group(1)):
                tokens.append((-1 if sign == "-" else 1, _normalize_roman(num)))
            formula_tokens = tokens
        return "roman", roman_key, formula_tokens
    if _PAREN_NUM_PREFIX_RE.match(s):
        return "paren", None, None
    if _is_suffix_total(s):
        return "suffix_total", None, None
    return "plain", None, None


def _strict_number(raw: str | None) -> float | None:
    """엄격한 숫자 파싱 - '5,6'/'5,6,11' 같은 주석번호 열이 금액으로 오인되지 않도록
    천단위 콤마 그룹이 정확한 문자열만 인정한다."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if s in DASH_VALUES:
        return 0.0
    neg = False
    s2 = s
    if s2.startswith("(") and s2.endswith(")"):
        neg, s2 = True, s2[1:-1]
    if s2.startswith("△") or s2.startswith("▲"):
        neg, s2 = True, s2[1:]
    if not _STRICT_NUM_RE.match(s2):
        return None
    val = float(s2.replace(",", ""))
    return -val if neg else val


def _find_note_column(rows: list[list[str]]) -> int | None:
    for row in rows[:2]:
        for c, cell in enumerate(row):
            if _norm_label(cell) in ("주석", "주 석"):
                return c
    return None


def _cell(row: list[str], col: int) -> str | None:
    return row[col] if col is not None and col < len(row) else None


def detect_periods(rows: list[list[str]], note_col: int | None) -> list[dict]:
    """returns [{"item_col":, "subtotal_col":} ...]. marker(로마자/합계 등)행이 값을 담는
    컬럼과 일반 항목행이 값을 담는 컬럼을 관찰해 (item_col, subtotal_col) 쌍을 구성한다.
    두 컬럼이 분리되지 않은(같은 컬럼을 공유하는) 표라면 item_col == subtotal_col."""
    ncols = max((len(r) for r in rows), default=0)
    marker_cols: set[int] = set()
    plain_cols: set[int] = set()
    for row in rows:
        label = row[0] if row else ""
        kind, _rk, _f = classify_row(label)
        is_marker = kind in ("roman", "suffix_total")
        for c in range(1, ncols):
            if c == note_col:
                continue
            if _strict_number(_cell(row, c)) is not None:
                (marker_cols if is_marker else plain_cols).add(c)

    if not plain_cols and not marker_cols:
        return []
    if marker_cols == plain_cols or not marker_cols:
        return [{"item_col": c, "subtotal_col": c} for c in sorted(plain_cols)]
    if not plain_cols:
        return [{"item_col": c, "subtotal_col": c} for c in sorted(marker_cols)]
    # 분리된 경우: 컬럼 순서대로 item_col 다음에 오는 marker_col과 짝짓는다
    all_cols = sorted(plain_cols | marker_cols)
    periods = []
    pending_item = None
    for c in all_cols:
        if c in plain_cols:
            pending_item = c
        else:
            periods.append({"item_col": pending_item if pending_item is not None else c, "subtotal_col": c})
            pending_item = None
    return periods


def _resolve_groups(rows: list[list[str]], item_col: int, subtotal_col: int,
                     tolerance_ratio: float = TOLERANCE_RATIO,
                     allow_roman_open=None, period_label: str | None = None,
                     allow_flat_backward: bool = True) -> dict:
    """로마자(forward, subtotal_col)·괄호숫자(forward, item_col) 중첩 그룹과 총계류
    (backward, subtotal_col) 행을 한 번의 순회로 검증. 로마자 그룹이 다른 로마자/괄호
    그룹의 자식이 아니면(최상위) backward 총계 검증을 위해 순서대로 보관한다.
    returns {"mismatches":[], "skipped":[], "roman_top_level":[{"roman_key","label","stated","row_idx"}]}"""
    RANK = {"paren": 2, "roman": 1}
    mismatches: list[dict] = []
    skipped: list[dict] = []
    roman_top_level: list[dict] = []
    stack: list[dict] = []
    backward_acc: list[dict] = []

    def close_top(min_rank: int):
        while stack and stack[-1]["rank"] >= min_rank:
            grp = stack.pop()
            if grp["has_all_children"] and grp["n_children"] > 0:
                tol = max(2.0, abs(grp["stated"]) * tolerance_ratio)
                diff = grp["children_sum"] - grp["stated"]
                plausible = abs(diff) <= max(abs(grp["stated"]), abs(grp["children_sum"])) * MAX_PLAUSIBLE_DIFF_RATIO
                if abs(diff) > tol and plausible:
                    mismatches.append({
                        "parent": grp["label"], "period": period_label, "segment": None,
                        "stated": grp["stated"], "computed": grp["children_sum"],
                        "diff": diff, "children": grp["children"],
                    })
            elif grp["n_children"] == 0:
                pass  # 자식이 없는 로마자행(예: CF의 leaf성 로마자) - 검증 대상 아님
            else:
                skipped.append({"parent": grp["label"], "segment": None, "missing": grp["missing"]})
            if stack:
                stack[-1]["children_sum"] += grp["stated"]
                stack[-1]["n_children"] += 1
                stack[-1]["children"].append(grp["label"])
            elif grp["kind"] == "roman":
                roman_top_level.append({"roman_key": grp["roman_key"], "label": grp["label"],
                                          "stated": grp["stated"], "row_idx": grp["row_idx"]})
                backward_acc.append({"label": grp["label"], "stated": grp["stated"]})

    for row_idx, row in enumerate(rows):
        label = (row[0] if row else "") or ""
        if not label.strip():
            continue
        kind, roman_key, _formula = classify_row(label)
        if kind == "roman" and allow_roman_open is not None and not allow_roman_open(label):
            kind = "plain"  # 가감 체인 성격의 로마자행(예: IS 대부분)은 그룹합(forward-header) 대상에서 제외
        if kind in ("roman", "paren"):
            close_top(RANK[kind])
            stated = _strict_number(_cell(row, subtotal_col if kind == "roman" else item_col))
            if stated is None:
                continue
            stack.append({"kind": kind, "rank": RANK[kind], "row_idx": row_idx, "label": label.strip(),
                          "roman_key": roman_key, "stated": stated, "children_sum": 0.0,
                          "n_children": 0, "has_all_children": True, "children": [], "missing": []})
        elif kind == "suffix_total":
            close_top(0)
            stated = _strict_number(_cell(row, subtotal_col))
            if stated is not None and backward_acc:
                computed = sum(g["stated"] for g in backward_acc)
                tol = max(2.0, abs(stated) * tolerance_ratio)
                diff = computed - stated
                # 차이가 기재값 대비 지나치게 크면(예: 50% 이상) 실제 오류라기보다 표 구조
                # 오인식(다른 항목까지 잘못 합산됨) 가능성이 높으므로 결과에 포함하지 않는다
                plausible = abs(diff) <= max(abs(stated), abs(computed)) * MAX_PLAUSIBLE_DIFF_RATIO
                if abs(diff) > tol and plausible:
                    mismatches.append({
                        "parent": label.strip(), "period": period_label, "segment": None,
                        "stated": stated, "computed": computed, "diff": diff,
                        "children": [g["label"] for g in backward_acc],
                    })
            backward_acc = []
        else:
            val = _strict_number(_cell(row, item_col))
            if val is None:
                if stack:
                    stack[-1]["has_all_children"] = False
                    stack[-1]["missing"].append(label.strip())
                elif _norm_label(label).endswith((":", "：")):
                    backward_acc = []  # 'OO으로 인식:' 같은 소제목 행은 새 구간의 시작으로 본다
                continue
            if stack:
                stack[-1]["children_sum"] += val
                stack[-1]["n_children"] += 1
                stack[-1]["children"].append(label.strip())
            elif allow_flat_backward:
                # 로마자/괄호 그룹 없이 평범한 항목행이 곧바로 총계류 행으로 이어지는 표
                # (예: 주석 표에 흔한 '항목, 항목, 합계' 구조)도 backward 합계 검증 대상에 포함
                backward_acc.append({"label": label.strip(), "stated": val})

    close_top(0)
    return {"mismatches": mismatches, "skipped": skipped, "roman_top_level": roman_top_level}


def check_bs_or_cf_hierarchy(rows: list[list[str]]) -> dict:
    note_col = _find_note_column(rows)
    periods = detect_periods(rows, note_col)
    all_mismatches, all_skipped, roman_top_level = [], [], []
    for i, p in enumerate(periods):
        period_label = "당기" if i == 0 else ("전기" if i == 1 else None)
        res = _resolve_groups(rows, p["item_col"], p["subtotal_col"], period_label=period_label)
        all_mismatches.extend(res["mismatches"])
        all_skipped.extend(res["skipped"])
        roman_top_level.append(res["roman_top_level"])
    return {"mismatches": all_mismatches, "skipped": all_skipped, "roman_top_level_by_period": roman_top_level}


def check_cf_special_rows(roman_top_level: list[dict], tolerance_ratio: float = TOLERANCE_RATIO,
                           period_label: str | None = None) -> list[dict]:
    """현금흐름표 전용: (a) 로마자 라벨에 '(Ⅰ+Ⅱ+Ⅲ+Ⅳ)'식 수식이 있으면 그대로 검증
    (b) '기말' 라벨 로마자 = '기초' 라벨 로마자 + 그 직전 로마자(순증감) 값."""
    mismatches = []
    by_key = {g["roman_key"]: g["stated"] for g in roman_top_level}
    for i, g in enumerate(roman_top_level):
        kind, roman_key, formula = classify_row(g["label"])
        if formula:
            missing = [k for _s, k in formula if k not in by_key]
            if not missing:
                computed = sum(sign * by_key[k] for sign, k in formula)
                tol = max(2.0, abs(g["stated"]) * tolerance_ratio)
                if abs(computed - g["stated"]) > tol:
                    mismatches.append({
                        "parent": g["label"], "period": period_label, "segment": None,
                        "stated": g["stated"], "computed": computed, "diff": computed - g["stated"],
                        "children": [k for _s, k in formula],
                    })
        elif "기말" in _norm_label(g["label"]):
            begin_idx = next((j for j in range(i - 1, -1, -1) if "기초" in _norm_label(roman_top_level[j]["label"])), None)
            if begin_idx is not None and begin_idx > 0:
                begin = roman_top_level[begin_idx]
                net_change = roman_top_level[begin_idx - 1]
                computed = begin["stated"] + net_change["stated"]
                tol = max(2.0, abs(g["stated"]) * tolerance_ratio)
                if abs(computed - g["stated"]) > tol:
                    mismatches.append({
                        "parent": g["label"], "period": period_label, "segment": None,
                        "stated": g["stated"], "computed": computed, "diff": computed - g["stated"],
                        "children": [net_change["label"], begin["label"]],
                    })
    return mismatches


# ------------------------------------------------------------------ 손익계산서 (가감 체인)
_PROFIT_SUFFIX_RE = re.compile(r"(이익|손실|손익)$")
_CONCEPT_ALIASES = [
    ("지배기업소유지분", "지배기업지분"), ("지배기업소유주지분", "지배기업지분"), ("지배주주지분", "지배기업지분"),
    ("판관비", "판매비와관리비"),
]

NET_INCOME_KEYS = {"반기순", "분기순", "당기순", "순"}
PRETAX_KEYS = {"법인세비용차감전순", "법인세차감전순"}
GROSS_PROFIT_KEYS = {"매출총"}
OPERATING_KEYS = {"영업"}
OTHER_GAINLOSS_KEYS = {"기타"}  # '기타손익' 자체가 '손익'으로 끝나 접미사 정규화 시 '기타'로 축약됨
FIN_GAINLOSS_KEYS = {"금융"}    # '금융손익'도 동일하게 '금융'으로 축약됨
TOTAL_COMPREHENSIVE_KEYS = {"총포괄"}
OCI_KEYS = {"기타포괄"}

# (결과 concept 키 후보, [(부호, 피연산자 concept 키 후보), ...]) - 사용자 제공 손익계산서 수식
IS_FORMULAS = [
    (GROSS_PROFIT_KEYS, [(1, {"매출액", "매출"}), (-1, {"매출원가"})]),
    (OPERATING_KEYS, [(1, GROSS_PROFIT_KEYS), (-1, {"판매비와관리비"})]),
    (OTHER_GAINLOSS_KEYS, [(1, {"기타수익"}), (-1, {"기타비용"})]),
    (FIN_GAINLOSS_KEYS, [(1, {"금융수익"}), (-1, {"금융비용"})]),
    (PRETAX_KEYS, [(1, OPERATING_KEYS), (1, OTHER_GAINLOSS_KEYS), (1, FIN_GAINLOSS_KEYS)]),
    (NET_INCOME_KEYS, [(1, PRETAX_KEYS), (-1, {"법인세비용"})]),
    (TOTAL_COMPREHENSIVE_KEYS, [(1, NET_INCOME_KEYS), (1, OCI_KEYS)]),
]


def _concept_key(label: str) -> str:
    """'매출총이익(손실)'/'매출총손실'/'매출총손익' 등 회사별 표현 차이를 하나의 키로 정규화.
    로마자('I.')·괄호숫자('(1)') 접두사를 모두 제거하므로 CF의 '(1) 반기순이익(손실)'처럼
    괄호숫자 접두사가 붙은 라벨의 개념 매칭(FS간 교차검증)에도 그대로 재사용할 수 있다."""
    s = label.strip()
    m = _ROMAN_PREFIX_RE.match(s)
    if m:
        s = s[m.end():]
    else:
        m = _PAREN_NUM_PREFIX_RE.match(s)
        if m:
            s = s[m.end():]
    s = _norm_label(s)
    s = re.sub(r"\(손실\)|\(이익\)|\(손익\)", "", s)
    for src, dst in _CONCEPT_ALIASES:
        s = s.replace(src, dst)
    s = _PROFIT_SUFFIX_RE.sub("", s)
    return s


def check_is_formulas(rows: list[list[str]], tolerance_ratio: float = TOLERANCE_RATIO) -> list[dict]:
    """매출총손익=매출액-매출원가, 영업손익=매출총손익-판관비, 기타손익=기타수익-기타비용,
    금융손익=금융수익-금융비용, 세전손익=영업손익+기타손익+금융손익, 순손익=세전손익-법인세비용,
    총포괄손익=순손익+기타포괄손익 (사용자 제공 수식). 회사별 '이익(손실)'/'손익' 등 표현 차이는
    concept 키 정규화로 흡수한다."""
    note_col = _find_note_column(rows)
    periods = detect_periods(rows, note_col)
    header_text_by_col: dict[int, str] = {}
    for r in rows[:2]:
        for c, cell in enumerate(r):
            header_text_by_col[c] = header_text_by_col.get(c, "") + _norm_label(cell)
    mismatches = []
    for p in periods:
        col = p["subtotal_col"]
        htxt = header_text_by_col.get(col, "")
        period_label = " ".join(x for x in (
            "당기" if "당" in htxt else ("전기" if "전" in htxt else None),
            "누적" if "누적" in htxt else ("3개월" if "3개월" in htxt else None),
        ) if x) or None
        values: dict[str, float] = {}
        labels_by_key: dict[str, str] = {}
        for row in rows:
            label = (row[0] if row else "") or ""
            kind, _rk, _f = classify_row(label)
            if kind != "roman":
                continue
            val = _strict_number(_cell(row, col))
            if val is None:
                continue
            key = _concept_key(label)
            values[key] = val
            labels_by_key[key] = label.strip()
        for result_keys, operands in IS_FORMULAS:
            result_key = next((k for k in result_keys if k in values), None)
            if result_key is None:
                continue
            operand_vals = []
            missing = False
            for sign, keyset in operands:
                k = next((kk for kk in keyset if kk in values), None)
                if k is None:
                    missing = True
                    break
                operand_vals.append((sign, k))
            if missing:
                continue
            computed = sum(sign * values[k] for sign, k in operand_vals)
            stated = values[result_key]
            tol = max(2.0, abs(stated) * tolerance_ratio)
            if abs(computed - stated) > tol:
                mismatches.append({
                    "parent": labels_by_key[result_key], "period": period_label, "segment": None,
                    "stated": stated, "computed": computed, "diff": computed - stated,
                    "children": [labels_by_key[k] for _s, k in operand_vals],
                })
    return mismatches


# ------------------------------------------------------------------ 자본변동표
def _count_header_rows(rows: list[list[str]]) -> int:
    n = 0
    for row in rows:
        if any(_strict_number(c) is not None for c in row):
            break
        n += 1
    return n


def _equity_column_roles(header_rows: list[list[str]]) -> list[tuple[int, str]]:
    ncols = max((len(r) for r in header_rows), default=0)
    combined = ["".join(_norm_label(r[c]) if c < len(r) else "" for r in header_rows) for c in range(ncols)]
    roles = []
    for c in range(1, ncols):
        text = combined[c]
        role = "total" if ("총계" in text or "소계" in text or "합계" in text) else "component"
        roles.append((c, role))
    return roles


def check_equity_row_wise(rows: list[list[str]], tolerance_ratio: float = TOLERANCE_RATIO) -> list[dict]:
    """가로 방향: 소계/총계 컬럼 = 그 앞(왼쪽) 구성요소 컬럼들의 누적 합."""
    header_n = _count_header_rows(rows)
    roles = _equity_column_roles(rows[:header_n])
    mismatches = []
    for row in rows[header_n:]:
        label = (row[0] if row else "") or ""
        if not label.strip():
            continue
        acc = 0.0
        acc_labels: list[str] = []
        for c, role in roles:
            val = _strict_number(_cell(row, c))
            if role == "component":
                if val is not None:
                    acc += val
                    acc_labels.append(f"{c}열")
                continue
            if val is not None:
                tol = max(2.0, abs(val) * tolerance_ratio)
                if abs(acc - val) > tol:
                    mismatches.append({
                        "parent": f"{label.strip()} ({c}열)", "period": None, "segment": None,
                        "stated": val, "computed": acc, "diff": acc - val, "children": acc_labels,
                    })
            acc = val if val is not None else 0.0
            acc_labels = [f"{c}열(소계/총계)"]
    return mismatches


def check_equity_column_wise(rows: list[list[str]], tolerance_ratio: float = TOLERANCE_RATIO) -> list[dict]:
    """세로 방향: '기말' 행 = 가장 최근 '기초' 행 + 그 사이 증감행들의 합 (컬럼별)."""
    header_n = _count_header_rows(rows)
    roles = _equity_column_roles(rows[:header_n])
    value_cols = [c for c, _role in roles]
    data_rows = [r for r in rows[header_n:] if (r[0] if r else "").strip()]
    mismatches = []
    begin_idx = None
    for i, row in enumerate(data_rows):
        label = _norm_label(row[0])
        if "기초" in label:
            begin_idx = i
        elif "기말" in label and begin_idx is not None:
            for c in value_cols:
                begin_val = _strict_number(_cell(data_rows[begin_idx], c))
                end_val = _strict_number(_cell(row, c))
                if begin_val is None or end_val is None:
                    continue
                movement_sum = sum(
                    mv for j in range(begin_idx + 1, i)
                    if (mv := _strict_number(_cell(data_rows[j], c))) is not None
                )
                computed = begin_val + movement_sum
                tol = max(2.0, abs(end_val) * tolerance_ratio)
                if abs(computed - end_val) > tol:
                    mismatches.append({
                        "parent": f"{row[0].strip()} ({c}열)", "period": None, "segment": None,
                        "stated": end_val, "computed": computed, "diff": computed - end_val,
                        "children": [f"{data_rows[begin_idx][0].strip()} + 증감 {i - begin_idx - 1}건"],
                    })
    return mismatches


# ------------------------------------------------------------------ 표 -> 재무제표 매핑 + 오케스트레이션
NOTE_SECTION_MARKERS = ["재무제표에 대한 주석", "1. 일반사항", "1.일반사항", "1. 일반적 사항",
                         "일반사항 및 주요 회계정책", "주요 회계정책"]


def _table_stmt_hint(rows: list[list[str]]) -> str | None:
    labels = [_norm_label(r[0] if r else "") for r in rows]
    joined = "".join(labels)
    if "자산총계" in joined or "부채총계" in joined:
        return "재무상태표"
    if re.search(r"\d{4}\.\d{2}\.\d{2}", joined) and any(("기초" in lbl or "기말" in lbl) for lbl in labels):
        return "자본변동표"
    if "인한현금흐름" in joined or "현금및현금성자산의증감" in joined or "현금및현금성자산의순증가" in joined:
        return "현금흐름표"
    if "매출총이익" in joined or "매출총손익" in joined or "매출총손실" in joined:
        return "손익계산서"
    if any(lbl.endswith("매출액") and classify_row(lbl)[0] == "roman" for lbl in labels):
        return "손익계산서"
    return None


def gather_statement_tables(doc: PdfDocument) -> dict[str, list[list[str]]]:
    """페이지 텍스트가 아니라 표 자체의 행 라벨 내용으로 재무제표를 판별한다(요약 문단 등에
    여러 재무제표명이 한꺼번에 언급되는 경우가 많아 페이지 텍스트 기반 판별은 부정확함).
    표 힌트가 없으면 직전 힌트를 '바로 다음 페이지'까지만 이어붙인다(같은 표가 페이지 경계에서
    분할된 경우 대응, 관련없는 후속 주석표가 잘못 흡수되는 것은 방지)."""
    result: dict[str, list[list[str]]] = {s: [] for s in STATEMENT_ORDER}
    current: str | None = None
    last_page: int | None = None
    for page_no, rows in doc.tables:
        hint = _table_stmt_hint(rows)
        if hint:
            current = hint
        elif current and (last_page is None or page_no - last_page > 1):
            current = None
        if current:
            result[current].extend(rows)
            last_page = page_no
    return result


def check_pdf_calculations(doc: PdfDocument) -> dict:
    """returns {stmt: {"mismatches": [...], "skipped": [...], "note": str|None}} - XBRL 쪽
    check_xbrl_calculations()와 동일한 형태로 맞춰 같은 렌더러를 재사용한다."""
    tables_by_stmt = gather_statement_tables(doc)
    result = {}
    for stmt in STATEMENT_ORDER:
        rows = tables_by_stmt[stmt]
        if not rows:
            result[stmt] = {"mismatches": [], "skipped": [],
                             "note": "해당 재무제표에서 표를 자동 인식하지 못했습니다 (표 없음 또는 인식 실패 - 육안 확인 필요)."}
            continue
        if stmt == "재무상태표":
            res = check_bs_or_cf_hierarchy(rows)
            result[stmt] = {"mismatches": res["mismatches"], "skipped": res["skipped"], "note": None}
        elif stmt == "현금흐름표":
            res = check_bs_or_cf_hierarchy(rows)
            mismatches = list(res["mismatches"])
            for i, period_top in enumerate(res["roman_top_level_by_period"]):
                period_label = "당기" if i == 0 else ("전기" if i == 1 else None)
                mismatches.extend(check_cf_special_rows(period_top, period_label=period_label))
            result[stmt] = {"mismatches": mismatches, "skipped": res["skipped"], "note": None}
        elif stmt == "손익계산서":
            note_col = _find_note_column(rows)
            periods = detect_periods(rows, note_col)
            def _allow_roman_open(label: str) -> bool:
                # IS는 로마자 대부분이 '가감 체인'(check_is_formulas가 처리)이라 그룹합 대상이
                # 아니다. '기타포괄이익' 계열과 'OO의 귀속'행만 실제로 아래 항목들의 합이다.
                return _concept_key(label) in OCI_KEYS or _norm_label(label).endswith("귀속")

            mismatches = []
            for p in periods:
                res = _resolve_groups(rows, p["item_col"], p["subtotal_col"],
                                       allow_roman_open=_allow_roman_open)
                mismatches.extend(res["mismatches"])
            mismatches.extend(check_is_formulas(rows))
            result[stmt] = {"mismatches": mismatches, "skipped": [], "note": None}
        else:  # 자본변동표
            mismatches = check_equity_row_wise(rows) + check_equity_column_wise(rows)
            result[stmt] = {"mismatches": mismatches, "skipped": [], "note": None}
    return result
