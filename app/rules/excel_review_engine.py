"""Excel 기반 정밀 검증 엔진 - fin-review-toolkit(dycmqk02-hub/fin-review-toolkit)의
app.py에서 이식. 재무제표 숫자를 Excel 템플릿에 옮겨 적으면
  1) 합계·소계·총계 검증
  2) 재무제표 간 대사(현금흐름표 기초/기말 현금 등) + 주석 간 대사(대사규칙 시트에 등록한
     모든 규칙 - 재무제표간/주석간 구분 없이 동일한 방식으로 처리됨)
  3) 연결-별도 비교
를 수행한다. GUI에 독립적인 순수 로직만 이 모듈에 둔다(원본의 tkinter App 클래스는 제외).
"""
import os
import re
import tempfile

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.hyperlink import Hyperlink

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

STATEMENT_SHEETS = [
    "별도_BS", "별도_IS", "별도_CF", "별도_SOCE", "별도_주석",
    "연결_BS", "연결_IS", "연결_CF", "연결_SOCE", "연결_주석",
]

STMT_HEADERS = ["계정과목", "구분", "당기금액", "전기금액", "비고"]
RECON_HEADERS = [
    "검증명", "값1_시트", "값1_계정과목", "값1_컬럼",
    "값2_시트", "값2_계정과목", "값2_컬럼", "허용오차",
]

SEP_CON_PAIRS = [
    ("별도_BS", "연결_BS", "재무상태표"),
    ("별도_IS", "연결_IS", "손익계산서"),
    ("별도_CF", "연결_CF", "현금흐름표"),
    ("별도_SOCE", "연결_SOCE", "자본변동표"),
]


# --------------------------------------------------------------------------
# 숫자 파싱
# --------------------------------------------------------------------------
def to_number(val):
    """'1,234' / '(1,234)' / 1234 / 1234.0 -> float, 빈값이면 None"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s in ("", "-", "－", "–"):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace(",", "").replace(" ", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def fmt(n):
    if n is None:
        return ""
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.2f}"


def _norm_name(s):
    """계정과목명 비교용 정규화: 공백 제거. 'A B' == 'AB'로 매칭되게 한다."""
    return re.sub(r"\s+", "", str(s or "").strip())


# --------------------------------------------------------------------------
# 템플릿 생성
# --------------------------------------------------------------------------
def create_template(path):
    wb = openpyxl.Workbook()
    guide = wb.active
    guide.title = "사용법"
    lines = [
        ("반기재무제표 검토 템플릿", None),
        ("", None),
        ("1. 별도_BS/IS/CF/SOCE, 연결_BS/IS/CF/SOCE 시트에 재무제표 '본문' 숫자를 그대로 옮겨 적으세요.", None),
        ("   - 계정과목: 재무제표에 표시된 이름 그대로 (별도/연결 동일 항목은 이름을 통일)", None),
        ("   - 구분: '세부' / '소계' / '합계' 중 하나만 입력", None),
        ("     세부 항목들은 바로 다음에 나오는 소계(또는 합계)에 합산되어 검증됩니다.", None),
        ("   - 당기금액/전기금액: 숫자만. 음수는 (1,234) 형식도 인식됩니다.", None),
        ("2. 별도_주석/연결_주석 시트에는 서로 대사해야 할 주석 항목들을 옮겨 적으세요.", None),
        ("   예: 금융상품 범주별 분류표의 '기타채권/기타채무'와 개별 명세 주석(기타채권,", None),
        ("   매입채무및기타채무 등)의 합계는 반드시 일치해야 하는데 실무상 자주 어긋납니다.", None),
        ("   같은 계정과목명이 여러 주석에 반복되면 값이 덮어써지므로, '주석5_기타채권_유동'처럼", None),
        ("   주석 번호를 붙여 각 행이 서로 다른 이름을 갖도록 입력하세요.", None),
        ("3. 대사규칙 시트에 서로 다른 표/주석에서 같아야 하는 두 항목을 등록하세요.", None),
        ("   3가지 유형 모두 같은 방식으로 등록합니다: (a) 재무제표간(예: CF기말현금=BS현금),", None),
        ("   (b) 재무제표-주석간(예: BS 매출채권=주석의 매출채권및기타채권 합계),", None),
        ("   (c) 주석간(예: 범주별금융상품 주석의 기타채권=개별 명세 주석의 기타채권 합계).", None),
        ("   예시 행이 이미 채워져 있습니다. 계정과목명만 실제 재무제표에 맞게 수정하세요.", None),
        ("4. 이 파일을 [① PDF 불러오기] 또는 [② 파일 선택]으로 불러온 뒤 [검증 실행]을 누르세요.", None),
    ]
    for i, (text, _) in enumerate(lines, start=1):
        guide.cell(row=i, column=1, value=text)
    guide.column_dimensions["A"].width = 100

    sample_rows = {
        "BS": [
            ("현금및현금성자산", "세부", 1000, 900, ""),
            ("매출채권", "세부", 2000, 1800, ""),
            ("유동자산", "소계", 3000, 2700, "= 세부 합"),
            ("유형자산", "세부", 5000, 5100, ""),
            ("비유동자산", "소계", 5000, 5100, ""),
            ("자산총계", "합계", 8000, 7800, "= 소계 합"),
        ],
        "IS": [
            ("매출액", "세부", 10000, 9000, ""),
            ("매출원가", "세부", -6000, -5400, ""),
            ("매출총이익", "소계", 4000, 3600, ""),
            ("판매비와관리비", "세부", -2000, -1800, ""),
            ("영업이익", "합계", 2000, 1800, ""),
            ("반기순이익", "세부", 1500, 1300, "대사규칙에서 참조"),
        ],
        "CF": [
            ("영업활동현금흐름", "세부", 1200, 1000, ""),
            ("투자활동현금흐름", "세부", -800, -600, ""),
            ("재무활동현금흐름", "세부", -200, -100, ""),
            ("현금증감액", "소계", 200, 300, "= 세부 합"),
            ("기초현금및현금성자산", "세부", 900, 600, "전기말 BS 현금과 대사"),
            ("환율변동효과", "세부", 0, 0, ""),
            ("기말현금및현금성자산", "합계", 1100, 900, "당기 BS 현금과 대사"),
        ],
        "SOCE": [
            ("자본금_기초", "세부", 500, 500, ""),
            ("반기순이익", "세부", 1500, 1300, "IS와 대사"),
            ("배당금지급", "세부", -300, -200, ""),
            ("자본총계_기말", "합계", 8000, 6500, "BS 자본총계와 대사"),
        ],
        "주석": [
            ("주석_매출채권및기타채권_유동비유동합계", "세부", 2000, 1800,
             "예: 재무제표 본문(BS)의 '매출채권' 계정과 대사 - 재무제표-주석 간 대사"),
            ("주석5_범주별금융자산_기타채권_유동", "세부", 520, 564,
             "예: 금융상품 범주별 분류표에 나오는 '기타채권'"),
            ("주석_기타채권명세_유동합계", "세부", 713, 566,
             "예: 기타채권 세부명세(미수금+미수수익+보증금 등) 합계. 대사규칙에서 위 항목과 비교"),
            ("주석5_범주별금융부채_기타채무_유동", "세부", 9364, 8369,
             "예: 금융상품 범주별 분류표에 나오는 '기타채무'"),
            ("주석14_매입채무및기타채무_기타채무_유동합계", "세부", 9686, 11162,
             "예: 매입채무및기타채무 주석(미지급금+미지급비용+임대보증금 등) 합계"),
        ],
    }

    for name in STATEMENT_SHEETS:
        ws = wb.create_sheet(name)
        ws.append(STMT_HEADERS)
        kind = name.split("_")[1]
        for row in sample_rows.get(kind, []):
            ws.append(list(row))
        for col, width in zip("ABCDE", (28, 10, 16, 16, 30)):
            ws.column_dimensions[col].width = width

    recon = wb.create_sheet("대사규칙")
    recon.append(RECON_HEADERS)
    default_rules = [
        ("별도 CF기말현금 = 별도 BS현금(당기)", "별도_CF", "기말현금및현금성자산", "당기",
         "별도_BS", "현금및현금성자산", "당기", 1),
        ("별도 CF기초현금 = 별도 BS현금(전기말)", "별도_CF", "기초현금및현금성자산", "당기",
         "별도_BS", "현금및현금성자산", "전기", 1),
        ("연결 CF기말현금 = 연결 BS현금(당기)", "연결_CF", "기말현금및현금성자산", "당기",
         "연결_BS", "현금및현금성자산", "당기", 1),
        ("연결 CF기초현금 = 연결 BS현금(전기말)  ※ 신규 종속기업 편입 시 누락 잦음", "연결_CF",
         "기초현금및현금성자산", "당기", "연결_BS", "현금및현금성자산", "전기", 1),
        ("별도 IS반기순이익 = 별도 SOCE반기순이익", "별도_IS", "반기순이익", "당기",
         "별도_SOCE", "반기순이익", "당기", 1),
        ("연결 IS반기순이익 = 연결 SOCE반기순이익", "연결_IS", "반기순이익", "당기",
         "연결_SOCE", "반기순이익", "당기", 1),
        ("별도 SOCE자본총계(기말) = 별도 BS자본총계", "별도_SOCE", "자본총계_기말", "당기",
         "별도_BS", "자본총계", "당기", 1),
        ("연결 SOCE자본총계(기말) = 연결 BS자본총계", "연결_SOCE", "자본총계_기말", "당기",
         "연결_BS", "자본총계", "당기", 1),
        ("별도 BS매출채권 = 별도 주석 매출채권및기타채권 합계  ※ 재무제표-주석 간 대사",
         "별도_BS", "매출채권", "당기",
         "별도_주석", "주석_매출채권및기타채권_유동비유동합계", "당기", 1),
        ("연결 BS매출채권 = 연결 주석 매출채권및기타채권 합계  ※ 재무제표-주석 간 대사",
         "연결_BS", "매출채권", "당기",
         "연결_주석", "주석_매출채권및기타채권_유동비유동합계", "당기", 1),
        ("별도 주석5(범주별금융자산)기타채권 = 별도 기타채권 명세 합계  ※ 주석 간 대사, 놓치기 매우 쉬움",
         "별도_주석", "주석5_범주별금융자산_기타채권_유동", "당기",
         "별도_주석", "주석_기타채권명세_유동합계", "당기", 1),
        ("별도 주석5(범주별금융부채)기타채무 = 별도 주석14(매입채무및기타채무) 기타채무 합계",
         "별도_주석", "주석5_범주별금융부채_기타채무_유동", "당기",
         "별도_주석", "주석14_매입채무및기타채무_기타채무_유동합계", "당기", 1),
        ("연결 주석5(범주별금융자산)기타채권 = 연결 기타채권 명세 합계  ※ 주석 간 대사, 놓치기 매우 쉬움",
         "연결_주석", "주석5_범주별금융자산_기타채권_유동", "당기",
         "연결_주석", "주석_기타채권명세_유동합계", "당기", 1),
        ("연결 주석5(범주별금융부채)기타채무 = 연결 주석14(매입채무및기타채무) 기타채무 합계",
         "연결_주석", "주석5_범주별금융부채_기타채무_유동", "당기",
         "연결_주석", "주석14_매입채무및기타채무_기타채무_유동합계", "당기", 1),
    ]
    for row in default_rules:
        recon.append(list(row))
    widths = (46, 12, 22, 8, 12, 22, 8, 10)
    for col, width in zip("ABCDEFGH", widths):
        recon.column_dimensions[col].width = width

    wb.save(path)


# --------------------------------------------------------------------------
# PDF 자동 추출 (best-effort assistant, 완전 자동화 아님)
# --------------------------------------------------------------------------
SECTION_MARKERS = [
    ("BS", ("재무상태표",)),
    ("IS", ("포괄손익계산서", "손익계산서")),
    ("CF", ("현금흐름표",)),
    ("SOCE", ("자본변동표",)),
    ("STOP", ("재무제표에 대한 주석", "1. 일반사항", "1.일반사항")),
]

BS_SUBTOTAL_NAMES = {"유동자산", "비유동자산", "유동부채", "비유동부채"}
BS_TOTAL_NAMES = {"자산총계", "부채총계", "자본총계"}
IS_SUBTOTAL_NAMES = {
    "매출총이익", "매출총이익(손실)", "매출총손익",
    "후속적으로당기손익으로재분류되는항목", "후속적으로당기손익으로재분류되지않는항목",
}
IS_TOTAL_NAMES = {
    "영업이익", "영업이익(손실)", "영업손익",
    "법인세비용차감전순이익(손실)", "법인세비용차감전순이익", "법인세비용차감전손익",
    "반기순이익", "반기순이익(손실)", "분기순이익", "분기순이익(손실)",
    "당기순이익", "당기순이익(손실)", "총포괄손익", "총포괄손익(손실)",
}
CF_TOTAL_NAMES = set()

IS_SUBTRACT_NAMES = {
    "매출원가", "판매비와관리비", "기타비용", "금융비용",
    "법인세비용", "법인세비용(수익)", "법인세비용(이익)", "법인세비용(수익)등", "영업비용",
}
HARD_RESET_TOTAL_NAMES = {"자산총계", "부채총계", "자본총계", "총포괄손익", "총포괄손익(손실)"}

_NUM_TOKEN_RE = re.compile(r"\(?-?[0-9][0-9,]*\)?")
_AMOUNT_SHAPE_RE = re.compile(r"^\(?-?\d{1,3}(,\d{3})*\)?$")
_LEADING_MARK_RE = re.compile(r"^[\sⅠ-Ⅻ0-9①-⑳.\)\(:·]+")


def _looks_like_amount(token):
    return bool(_AMOUNT_SHAPE_RE.match(token))


def _is_small_standalone_number(token):
    return "," not in token and len(token.lstrip("-(").rstrip(")")) <= 2


def extract_pdf_lines(path):
    if pdfplumber is None:
        raise RuntimeError(
            "pdfplumber 패키지가 필요합니다. 먼저 다음을 실행하세요:\n"
            "    pip install pdfplumber"
        )
    lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(text.split("\n"))
    return lines


def _parse_amount_line(line, max_amounts=2):
    line = line.strip()
    if not line:
        return None
    all_tokens = _NUM_TOKEN_RE.findall(line)
    if not all_tokens:
        return None
    first_idx = line.find(all_tokens[0])
    name = line[:first_idx]
    name = _LEADING_MARK_RE.sub("", name).strip(" .·:")
    if len(name) < 2:
        return None
    tokens = [t for t in all_tokens if _looks_like_amount(t)]
    while len(tokens) > max_amounts and _is_small_standalone_number(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return None
    numbers = [to_number(t) for t in tokens]
    numbers = [n for n in numbers if n is not None]
    if not numbers:
        return None
    return name, numbers


def _pick_period_amounts(section, numbers):
    if section == "IS" and len(numbers) >= 4:
        return numbers[1], numbers[3]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    return numbers[0], None


def _classify_gubun(section, name):
    n = name.replace(" ", "")
    if section == "BS":
        if n in BS_TOTAL_NAMES:
            return "합계"
        if n in BS_SUBTOTAL_NAMES:
            return "소계"
    elif section == "IS":
        if n in IS_TOTAL_NAMES:
            return "합계"
        if n in IS_SUBTOTAL_NAMES:
            return "소계"
    elif section == "CF":
        if n in CF_TOTAL_NAMES:
            return "합계"
    return "세부"


_SKIP_LINE_NAMES = {
    "과목", "구분", "주석", "금액", "단위", "당반기말", "전기말", "합계",
    "기타포괄손익", "기타포괄손익(손실)",
}
_BS_TRAILING_SKIP_NAMES = {"부채와자본총계", "부채및자본총계", "자본과부채총계"}
_IS_HEADER_FIRST_SUBTOTAL_NAMES = {
    "후속적으로당기손익으로재분류되는항목", "후속적으로당기손익으로재분류되지않는항목",
}


def _reorder_is_oci_rows(rows):
    result = []
    i, n = 0, len(rows)
    while i < n:
        row = rows[i]
        name, gubun = row[0], row[1]
        if gubun == "소계" and _norm_name(name) in _IS_HEADER_FIRST_SUBTOTAL_NAMES:
            j = i + 1
            details = []
            while j < n and rows[j][1] == "세부":
                details.append(rows[j])
                j += 1
            result.extend(details)
            result.append(row)
            i = j
        else:
            result.append(row)
            i += 1
    return result


def _reorder_bs_rows(rows):
    result = []
    pending_subtotal = None
    detail_buffer = []
    trailing = []

    def _flush_pending():
        nonlocal pending_subtotal, detail_buffer
        result.extend(detail_buffer)
        detail_buffer = []
        if pending_subtotal is not None:
            result.append(pending_subtotal)
            pending_subtotal = None

    for row in rows:
        name, gubun = row[0], row[1]
        if _norm_name(name) in _BS_TRAILING_SKIP_NAMES:
            trailing.append(row)
            continue
        if gubun == "소계":
            _flush_pending()
            pending_subtotal = row
        elif gubun == "합계":
            _flush_pending()
            result.append(row)
        else:
            detail_buffer.append(row)
    _flush_pending()
    result.extend(trailing)
    return result


def parse_financial_pdf(path):
    """PDF 한 개에서 BS/IS/CF 섹션의 (계정과목, 구분, 당기, 전기, 비고) 행을 추출.
    SOCE(자본변동표)·주석은 구조가 복잡해 자동 추출하지 않는다."""
    lines = extract_pdf_lines(path)
    result = {"BS": [], "IS": [], "CF": []}
    section = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        line_compact = re.sub(r"\s+", "", line)
        matched_marker = None
        for sec, keywords in SECTION_MARKERS:
            if any(kw in line_compact for kw in keywords) and len(line_compact) < 40:
                matched_marker = sec
                break
        if matched_marker == "STOP":
            break
        if matched_marker == "SOCE":
            section = None
            continue
        if matched_marker:
            section = matched_marker
            continue

        if section not in result:
            continue

        max_amounts = 4 if section == "IS" else 2
        parsed = _parse_amount_line(line, max_amounts=max_amounts)
        if parsed is None:
            continue
        name, numbers = parsed
        if _norm_name(name) in _SKIP_LINE_NAMES:
            continue

        cur, prev = _pick_period_amounts(section, numbers)
        if section == "IS" and _norm_name(name) in IS_SUBTRACT_NAMES:
            if cur is not None and cur > 0:
                cur = -cur
            if prev is not None and prev > 0:
                prev = -prev
        gubun = _classify_gubun(section, name)
        note = "[PDF 자동추출] " + raw.strip()
        result[section].append((name, gubun, cur, prev, note))
    result["BS"] = _reorder_bs_rows(result["BS"])
    result["IS"] = _reorder_is_oci_rows(result["IS"])
    return result


def _clear_sheet_to_header(ws):
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)


def _find_row_name(rows, must_contain):
    for name, *_ in rows:
        if all(sub in name for sub in must_contain):
            return name
    return None


def _update_cash_recon_names(wb, label, bs_rows, cf_rows):
    if "대사규칙" not in wb.sheetnames:
        return
    ws = wb["대사규칙"]
    idx = _header_index(ws)
    name_col = idx.get("검증명")
    v1_col = idx.get("값1_계정과목")
    v2_col = idx.get("값2_계정과목")
    if None in (name_col, v1_col, v2_col):
        return

    bs_cash = _find_row_name(bs_rows, ("현금및현금성자산",)) or "현금및현금성자산"
    cf_close = _find_row_name(cf_rows, ("현금", "기말"))
    cf_open = _find_row_name(cf_rows, ("현금", "기초"))

    for row in ws.iter_rows(min_row=2):
        vname = row[name_col].value
        if not vname or not str(vname).startswith(f"{label} CF"):
            continue
        if "기말현금" in str(vname) and cf_close:
            row[v1_col].value = cf_close
            row[v2_col].value = bs_cash
        elif "기초현금" in str(vname) and cf_open:
            row[v1_col].value = cf_open
            row[v2_col].value = bs_cash


def build_workbook_from_pdfs(sep_pdf_path, con_pdf_path):
    """별도/연결 PDF 2개로부터 워크북을 생성. 반환: (workbook, 추출건수 요약 dict)"""
    tmp_path = os.path.join(tempfile.gettempdir(), "_fin_review_base_template.xlsx")
    create_template(tmp_path)
    wb = openpyxl.load_workbook(tmp_path)
    try:
        os.remove(tmp_path)
    except OSError:
        pass

    for name in STATEMENT_SHEETS:
        if name.endswith("_SOCE") or name.endswith("_주석"):
            if name in wb.sheetnames:
                _clear_sheet_to_header(wb[name])

    counts = {}
    for label, pdf_path in (("별도", sep_pdf_path), ("연결", con_pdf_path)):
        if not pdf_path:
            continue
        extracted = parse_financial_pdf(pdf_path)
        for section in ("BS", "IS", "CF"):
            rows = extracted.get(section, [])
            sheet_name = f"{label}_{section}"
            if sheet_name not in wb.sheetnames:
                counts[sheet_name] = 0
                continue
            ws = wb[sheet_name]
            _clear_sheet_to_header(ws)
            for row in rows:
                ws.append(list(row))
            counts[sheet_name] = len(rows)
        _update_cash_recon_names(wb, label, extracted.get("BS", []), extracted.get("CF", []))
    return wb, counts


# --------------------------------------------------------------------------
# 시트 파싱
# --------------------------------------------------------------------------
def _header_index(ws):
    headers = [c.value for c in ws[1]]
    return {h: i for i, h in enumerate(headers) if h}


def sheet_to_dict(ws):
    """계정과목 -> {"당기":.., "전기":..}"""
    idx = _header_index(ws)
    d = {}
    if "계정과목" not in idx:
        return d
    for r in ws.iter_rows(min_row=2, values_only=False):
        cells = list(r)
        name = cells[idx["계정과목"]].value
        if name is None or str(name).strip() == "":
            continue
        cur = to_number(cells[idx["당기금액"]].value) if "당기금액" in idx else None
        prev = to_number(cells[idx["전기금액"]].value) if "전기금액" in idx else None
        d[_norm_name(name)] = {"당기": cur, "전기": prev, "_계정과목": str(name).strip()}
    return d


# --------------------------------------------------------------------------
# 1) 합계·소계·총계 검증
# --------------------------------------------------------------------------
def verify_sheet(sheet_name, ws, tolerance):
    results = []
    idx = _header_index(ws)
    for needed in ("계정과목", "구분", "당기금액", "전기금액"):
        if needed not in idx:
            return results

    for col_key, col_label in (("당기금액", "당기"), ("전기금액", "전기")):
        detail_acc = 0.0
        subtotal_acc = 0.0
        for r in ws.iter_rows(min_row=2, values_only=False):
            cells = list(r)
            name = cells[idx["계정과목"]].value
            typ = cells[idx["구분"]].value
            if name is None or typ is None:
                continue
            typ = str(typ).strip()
            val = to_number(cells[idx[col_key]].value)
            if val is None:
                continue
            if typ == "세부":
                detail_acc += val
            elif typ == "소계":
                expected = detail_acc
                diff = val - expected
                ok = abs(diff) <= tolerance
                results.append({
                    "시트": sheet_name, "구간": col_label, "계정과목": str(name).strip(),
                    "구분": "소계", "표시값": val, "계산값": expected, "차이": diff,
                    "결과": "일치" if ok else "불일치",
                })
                subtotal_acc += val
                detail_acc = 0.0
            elif typ == "합계":
                expected = detail_acc + subtotal_acc
                diff = val - expected
                ok = abs(diff) <= tolerance
                results.append({
                    "시트": sheet_name, "구간": col_label, "계정과목": str(name).strip(),
                    "구분": "합계", "표시값": val, "계산값": expected, "차이": diff,
                    "결과": "일치" if ok else "불일치",
                })
                detail_acc = 0.0
                if _norm_name(name) in HARD_RESET_TOTAL_NAMES:
                    subtotal_acc = 0.0
                else:
                    subtotal_acc = val
    return results


def run_sum_verification(wb, tolerance):
    all_results = []
    for name in STATEMENT_SHEETS:
        if name in wb.sheetnames:
            all_results.extend(verify_sheet(name, wb[name], tolerance))
    return all_results


# --------------------------------------------------------------------------
# 2) 대사검증 (재무제표간/주석간 - 대사규칙 시트에 등록한 모든 규칙)
# --------------------------------------------------------------------------
def build_lookup(wb):
    lookup = {}
    for name in STATEMENT_SHEETS:
        if name in wb.sheetnames:
            lookup[name] = sheet_to_dict(wb[name])
    return lookup


def run_recon_verification(wb, lookup):
    results = []
    if "대사규칙" not in wb.sheetnames:
        return results
    ws = wb["대사규칙"]
    idx = _header_index(ws)
    for r in ws.iter_rows(min_row=2, values_only=False):
        cells = list(r)

        def get(col):
            i = idx.get(col)
            if i is None or i >= len(cells):
                return None
            return cells[i].value

        name = get("검증명")
        if not name:
            continue
        s1, n1, c1 = get("값1_시트"), get("값1_계정과목"), (get("값1_컬럼") or "당기")
        s2, n2, c2 = get("값2_시트"), get("값2_계정과목"), (get("값2_컬럼") or "당기")
        tol = to_number(get("허용오차"))
        if tol is None:
            tol = 1

        v1 = lookup.get(str(s1).strip(), {}).get(_norm_name(n1)) if s1 and n1 else None
        v2 = lookup.get(str(s2).strip(), {}).get(_norm_name(n2)) if s2 and n2 else None
        a = v1.get(str(c1).strip()) if v1 else None
        b = v2.get(str(c2).strip()) if v2 else None

        # 값1/값2가 실제로 어느 시트·계정과목·컬럼에서 왔는지 함께 보관해둔다
        # (차이 요약 시트의 하이퍼링크가 원본 셀을 정확히 찾아가려면 필요함).
        ref1 = {"시트": s1, "계정과목": n1, "컬럼": c1} if s1 and n1 else None
        ref2 = {"시트": s2, "계정과목": n2, "컬럼": c2} if s2 and n2 else None

        if a is None or b is None:
            results.append({
                "검증명": str(name), "값1": a, "값2": b, "차이": None,
                "결과": "데이터없음", "값1_참조": ref1, "값2_참조": ref2,
            })
            continue
        diff = a - b
        ok = abs(diff) <= tol
        results.append({
            "검증명": str(name), "값1": a, "값2": b, "차이": diff,
            "결과": "일치" if ok else "불일치", "값1_참조": ref1, "값2_참조": ref2,
        })
    return results


# --------------------------------------------------------------------------
# 3) 연결-별도 비교
# --------------------------------------------------------------------------
def run_sep_con_compare(wb):
    results = []
    for sep, con, label in SEP_CON_PAIRS:
        if sep not in wb.sheetnames or con not in wb.sheetnames:
            continue
        sd = sheet_to_dict(wb[sep])
        cd = sheet_to_dict(wb[con])
        norm_keys = sorted(set(sd) | set(cd))
        for key in norm_keys:
            display_name = sd.get(key, {}).get("_계정과목") or cd.get(key, {}).get("_계정과목") or key
            for col in ("당기", "전기"):
                a = sd.get(key, {}).get(col)
                b = cd.get(key, {}).get(col)
                if a is None and b is None:
                    continue
                diff = (b if b is not None else 0) - (a if a is not None else 0)
                results.append({
                    "구분표": label, "계정과목": display_name, "기간": col,
                    "별도": a, "연결": b, "차이": diff,
                })
    return results


# --------------------------------------------------------------------------
# 요약 / 리포트
# --------------------------------------------------------------------------
def summary_lines(file_path, sum_results, recon_results, compare_results):
    import datetime

    n_sum = len(sum_results)
    fail_sum = [r for r in sum_results if r["결과"] == "불일치"]
    n_recon = len(recon_results)
    fail_recon = [r for r in recon_results if r["결과"] == "불일치"]
    na_recon = [r for r in recon_results if r["결과"] == "데이터없음"]
    n_compare = len(compare_results)
    diff_compare = [r for r in compare_results if (r.get("차이") or 0) != 0]

    lines = []
    lines.append(f"파일: {file_path or '(없음)'}")
    lines.append(f"검증 시각: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("[1] 합계·소계·총계 검증")
    lines.append(f"  총 {n_sum}건 중 불일치 {len(fail_sum)}건")
    for r in fail_sum:
        lines.append(
            f"   \U0001f534 {r['시트']} / {r['계정과목']}({r['구간']}, {r['구분']}): "
            f"표시값 {fmt(r['표시값'])} vs 계산값 {fmt(r['계산값'])} (차이 {fmt(r['차이'])})"
        )
    lines.append("")
    lines.append("[2] 대사검증")
    lines.append(f"  총 {n_recon}건 중 불일치 {len(fail_recon)}건, 데이터없음 {len(na_recon)}건")
    for r in fail_recon:
        lines.append(
            f"   \U0001f534 {r['검증명']}: {fmt(r['값1'])} vs {fmt(r['값2'])} (차이 {fmt(r['차이'])})"
        )
    for r in na_recon:
        lines.append(f"   ⚪ {r['검증명']}: 값을 찾지 못함(계정과목명/시트명 확인 필요)")
    lines.append("")
    lines.append("[3] 연결-별도 비교")
    lines.append(f"  비교 {n_compare}건 중 차이 존재 {len(diff_compare)}건 (차이=0은 표시 생략 가능)")
    lines.append("  ※ 차이가 있다고 오류는 아님. 연결조정으로 설명되는지 확인 필요한 후보 목록.")
    lines.append("")
    lines.append("[4] 실질적 회계처리 검토포인트 (자동화 불가 - 체크리스트)")
    lines.append("  [ ] 종속기업/관계기업 손실 발생 시 투자자산 손상징후 검토 여부")
    lines.append("  [ ] 영업권 손상평가 핵심가정이 손상 트리거 발생에도 전기와 동일 유지되는지")
    lines.append("  [ ] 신규 종속기업 편의취득일 사용 시 중요성 판단 근거 문서화 여부")
    lines.append("  [ ] 관계기업 투자 손상차손 환입 불가 원칙과의 정합성")
    lines.append("  [ ] 자기주식 취득/배당정책과 유동성 지표 추세")
    return lines


def _write_report_sheet(ws, columns, rows):
    header_fill = PatternFill(start_color="BEE0F7", end_color="BEE0F7", fill_type="solid")
    fail_fill = PatternFill(start_color="FBE1E1", end_color="FBE1E1", fill_type="solid")
    ok_fill = PatternFill(start_color="E6F5EA", end_color="E6F5EA", fill_type="solid")
    na_fill = PatternFill(start_color="EFEFEF", end_color="EFEFEF", fill_type="solid")
    info_fill = PatternFill(start_color="FFF6D9", end_color="FFF6D9", fill_type="solid")

    ws.append(list(columns))
    for c in range(1, len(columns) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="1F3A5F")
        cell.fill = header_fill

    for row in rows:
        ws.append([row.get(col) for col in columns])
        r = ws.max_row
        result = row.get("결과")
        if result == "불일치":
            fill = fail_fill
        elif result == "일치":
            fill = ok_fill
        elif result == "데이터없음":
            fill = na_fill
        else:
            diff = row.get("차이")
            fill = info_fill if (diff is not None and diff != 0) else None
        if fill:
            for c in range(1, len(columns) + 1):
                ws.cell(row=r, column=c).fill = fill

    for c, col in enumerate(columns, start=1):
        width = 30 if col in ("검증명", "계정과목") else 14
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = width
    ws.freeze_panes = "A2"


_STMT_COL_BY_PERIOD = {"당기": "C", "전기": "D"}


def _find_account_row(ws, account_name):
    """계정과목 열(A)에서 이름이 일치하는 첫 행 번호(1-based)를 찾는다. 못 찾으면 None."""
    target = _norm_name(account_name)
    for row in ws.iter_rows(min_row=2):
        cell = row[0]
        if cell.value is not None and _norm_name(cell.value) == target:
            return cell.row
    return None


def _account_cell_location(wb, sheet_name, account_name, period):
    """(시트, 계정과목, 기간)에 해당하는 원본 워크북 셀 위치를 "'시트명'!C15" 형태로 반환.
    시트·행을 찾지 못하면 None."""
    if not sheet_name or not account_name or not wb or sheet_name not in wb.sheetnames:
        return None
    row = _find_account_row(wb[sheet_name], account_name)
    if row is None:
        return None
    col = _STMT_COL_BY_PERIOD.get(str(period).strip(), "C")
    return f"'{sheet_name}'!{col}{row}"


def build_diff_summary_rows(source_wb, sum_results, recon_results, compare_results):
    """세 검증 결과 중 '차이가 있는' 항목만 모아 원본 셀 위치와 함께 반환한다.
    returns [{"구분","내용","값1","값2","차이","위치1","위치2"}, ...] (위치는 "'시트'!C15" 형태
    또는 원본에서 계정과목을 찾지 못하면 None)."""
    rows = []
    for r in sum_results:
        if r.get("결과") != "불일치":
            continue
        rows.append({
            "구분": "합계검증",
            "내용": f"{r['시트']} / {r['계정과목']} ({r['구간']}, {r['구분']})",
            "값1": r.get("표시값"), "값2": r.get("계산값"), "차이": r.get("차이"),
            "위치1": _account_cell_location(source_wb, r.get("시트"), r.get("계정과목"), r.get("구간")),
            "위치2": None,
        })
    for r in recon_results:
        if r.get("결과") != "불일치":
            continue
        ref1, ref2 = r.get("값1_참조"), r.get("값2_참조")
        loc1 = _account_cell_location(source_wb, ref1["시트"], ref1["계정과목"], ref1["컬럼"]) if ref1 else None
        loc2 = _account_cell_location(source_wb, ref2["시트"], ref2["계정과목"], ref2["컬럼"]) if ref2 else None
        rows.append({
            "구분": "대사검증", "내용": r["검증명"],
            "값1": r.get("값1"), "값2": r.get("값2"), "차이": r.get("차이"),
            "위치1": loc1, "위치2": loc2,
        })
    sep_con_lookup = {label: (sep, con) for sep, con, label in SEP_CON_PAIRS}
    for r in compare_results:
        diff = r.get("차이")
        if diff in (None, 0):
            continue
        sep_sheet, con_sheet = sep_con_lookup.get(r["구분표"], (None, None))
        rows.append({
            "구분": "연결-별도비교", "내용": f"{r['구분표']} / {r['계정과목']} ({r['기간']})",
            "값1": r.get("별도"), "값2": r.get("연결"), "차이": diff,
            "위치1": _account_cell_location(source_wb, sep_sheet, r["계정과목"], r["기간"]),
            "위치2": _account_cell_location(source_wb, con_sheet, r["계정과목"], r["기간"]),
        })
    return rows


def _to_file_uri(path: str) -> str:
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def _write_diff_summary_sheet(ws, rows, source_path):
    header_fill = PatternFill(start_color="BEE0F7", end_color="BEE0F7", fill_type="solid")
    diff_fill = PatternFill(start_color="FBE1E1", end_color="FBE1E1", fill_type="solid")
    columns = ("구분", "내용", "값1", "값2", "차이", "바로가기1", "바로가기2")

    ws.append(list(columns))
    for c in range(1, len(columns) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="1F3A5F")
        cell.fill = header_fill

    if not rows:
        ws.append(["불일치 없음 - 합계검증/대사검증/연결-별도비교 모두 차이가 없습니다.", "", "", "", "", "", ""])
    for row in rows:
        ws.append([row["구분"], row["내용"], row.get("값1"), row.get("값2"), row.get("차이"), None, None])
        r = ws.max_row
        for c in range(1, 6):
            ws.cell(row=r, column=c).fill = diff_fill
        for col_idx, loc_key in ((6, "위치1"), (7, "위치2")):
            loc = row.get(loc_key)
            cell = ws.cell(row=r, column=col_idx)
            if loc and source_path:
                cell.value = "바로가기"
                cell.hyperlink = Hyperlink(ref=cell.coordinate, target=_to_file_uri(source_path), location=loc)
                cell.font = Font(color="0563C1", underline="single")
            else:
                cell.value = "-"

    widths = {"구분": 14, "내용": 42, "값1": 16, "값2": 16, "차이": 16, "바로가기1": 12, "바로가기2": 12}
    for c, col in enumerate(columns, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = widths[col]
    ws.freeze_panes = "A2"


def build_report_workbook(file_path, sum_results, recon_results, compare_results,
                           source_wb=None, source_path=None):
    """source_wb/source_path를 함께 주면 맨 왼쪽에 '차이요약' 시트를 추가한다 - 세 검증에서
    나온 불일치/차이 항목만 모아 원본 파일의 해당 셀로 바로 이동하는 하이퍼링크를 붙인다."""
    wb = openpyxl.Workbook()
    summary_ws = wb.active
    summary_ws.title = "요약"
    for line in summary_lines(file_path, sum_results, recon_results, compare_results):
        summary_ws.append([line])
    summary_ws.column_dimensions["A"].width = 100

    sum_ws = wb.create_sheet("합계검증")
    _write_report_sheet(
        sum_ws, ("시트", "구간", "계정과목", "구분", "표시값", "계산값", "차이", "결과"), sum_results,
    )

    recon_ws = wb.create_sheet("대사검증")
    _write_report_sheet(recon_ws, ("검증명", "값1", "값2", "차이", "결과"), recon_results)

    compare_ws = wb.create_sheet("연결-별도비교")
    _write_report_sheet(
        compare_ws, ("구분표", "계정과목", "기간", "별도", "연결", "차이"), compare_results,
    )

    if source_wb is not None:
        diff_rows = build_diff_summary_rows(source_wb, sum_results, recon_results, compare_results)
        diff_ws = wb.create_sheet("차이요약", 0)
        _write_diff_summary_sheet(diff_ws, diff_rows, source_path)
        wb.active = 0

    return wb
