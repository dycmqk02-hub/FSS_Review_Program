"""공시사항점검표(감사조서서식 8400) 대사 - K-IFRS/일반기업회계기준 공시사항점검표를
검토보고서 본문과 대사하여 누락 가능성이 있는 공시사항을 스크리닝한다.

두 파일은 형식이 서로 다르다(레거시 .xls vs .xlsx, 컬럼 배치도 다름)는 것을 실제 파일을
열어 확인한 뒤 각각 전용 파서를 작성했다:
  - KIFRS(.xls, xlrd로 읽음): col0=관련 K-IFRS 참조문단, col1=요구사항 내용,
    (col2가 음수인 행은 하위 나열 항목 - col3에 텍스트)
  - 일반기준(.xlsx, openpyxl로 읽음): col0=요구사항 내용(항목행) 또는 섹션제목,
    col1=괄호숫자 불릿 마커, col2=불릿 텍스트, col4=참조기준(항목행에만 값이 있어
    섹션제목 행과 구분하는 기준이 됨)

개별 요구사항 문장이 대부분 추상적·절차적이라(예: "K-IFRS 1001 문단 40A: 다음 모두에
해당된다면...") 키워드 매칭만으로는 오탐(실제로는 있는데 "미확인"으로 표시)이 잦을 수
있다는 점을 사용자에게 확인받고 진행한 휴리스틱이다 - 반드시 최종 확인은 검토자가 원문·
주석과 직접 대조해야 한다.
"""
import os
import re

try:
    import xlrd
except ImportError:
    xlrd = None
import openpyxl

DEFAULT_KIFRS_PATH = r"C:\Users\seo\1st Review프로그램\기준서\감사조서서식_8400 공시사항점검표 (KIFRS용)_2025.xls"
DEFAULT_KGAAP_PATH = r"C:\Users\seo\1st Review프로그램\기준서\감사조서서식_8400 공시사항점검표 (일반기준용)_2025.xlsx"

_SECTION_NUM_RE = re.compile(r"^\d+(\.\d+)*\.?\s")

_STOPWORDS = {
    "경우", "사항", "정보", "내용", "다음", "있다", "한다", "하여", "또는", "그리고", "대한",
    "관련", "있는", "해야", "하는", "아니", "기재", "표시", "공시", "포함", "때문", "위한",
    "통해", "대해", "따라", "이상", "이하", "적용", "요구", "명시", "여부", "제공", "필요",
    "존재", "발생", "고려", "부분", "기준", "재무제표", "각각", "이러한", "그러한", "이는",
    "그러나", "다만", "또한", "및", "제외", "인식", "측정", "산정", "산출", "설명",
}

# 한글 조사 접미사 - 형태소 분석 없이도 "표시통화와"/"표시통화가"/"표시통화는" 등이 모두
# "표시통화"로 정규화되도록 후보 단어 끝에서 제거한다(긴 조사부터 매칭해야 "으로"를
# "로"보다 먼저 떼어내는 등 잘못된 부분제거를 피할 수 있음). 키워드 쪽만 제거하면 되고
# 원문(보고서) 쪽은 그대로 두어도 부분일치(substring) 검색이라 자동으로 매칭된다.
_PARTICLES = sorted([
    "으로서", "으로써", "이라도", "이나마", "이라는", "에서의", "에게서", "으로는", "으로도",
    "이라", "라면", "다면", "이며", "이고", "하고", "으로", "에서", "에게", "한테", "부터",
    "까지", "처럼", "만큼", "같이", "마저", "조차", "밖에", "이나", "이란", "라도", "든지",
    "은", "는", "이", "가", "을", "를", "의", "와", "과", "도", "만", "나", "야", "로", "에",
], key=len, reverse=True)


def _strip_particle(word: str) -> str:
    for p in _PARTICLES:
        if len(word) > len(p) + 1 and word.endswith(p):
            return word[: -len(p)]
    return word


def _extract_keywords(text: str, max_n: int = 5) -> list[str]:
    """요구사항 텍스트에서 검색용 핵심 단어를 추출한다. 형태소 분석 없이(이 프로그램은 규칙/
    키워드 기반이며 LLM/NLP를 쓰지 않기로 결정됨) 한글 2자 이상 연속 토큰을 뽑고, 흔히
    붙는 조사를 제거해 정규화한 뒤, 기능어를 제외하고 긴 단어부터 상위 max_n개를 사용한다
    (짧은 단어일수록 무관한 문맥과 우연히 일치할 위험이 크므로)."""
    words = re.findall(r"[가-힣]{2,}", text or "")
    stemmed = [_strip_particle(w) for w in words]
    candidates = [w for w in stemmed if len(w) >= 2 and w not in _STOPWORDS]
    uniq = sorted(set(candidates), key=len, reverse=True)
    return uniq[:max_n]


def parse_kifrs_checklist(path: str) -> list[dict]:
    """returns [{"section","reference","text"}, ...]"""
    if xlrd is None:
        raise RuntimeError("xlrd 패키지가 필요합니다 (pip install xlrd) - 레거시 .xls 파일 읽기용")
    wb = xlrd.open_workbook(path)
    ws = wb.sheet_by_name("8400")
    items: list[dict] = []
    current: dict | None = None
    current_section: str | None = None
    for r in range(ws.nrows):
        c0 = str(ws.cell_value(r, 0)).strip()
        c1 = str(ws.cell_value(r, 1)).strip()
        c2 = ws.cell_value(r, 2)
        c3 = str(ws.cell_value(r, 3)).strip()

        if c0.startswith("K-IFRS") or c0.startswith("K-GAAP"):
            current = {"section": current_section, "reference": c0.replace("\n", " "), "text": c1}
            items.append(current)
            continue
        if isinstance(c2, float) and c2 < 0 and c3:
            if current is not None:
                current["text"] += " " + c3
            continue
        if not c0 and c1 and current is not None and c1 != "내용" and c1 != "검 토":
            current["text"] += " " + c1
            continue
        if c0 and c0 != "관련 K-IFRS" and _SECTION_NUM_RE.match(c0):
            current_section = c0
            continue
    return items


def parse_kgaap_checklist(path: str) -> list[dict]:
    """returns [{"section","reference","text"}, ...]"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["8400"]
    items: list[dict] = []
    current: dict | None = None
    current_section: str | None = None
    for r in range(1, ws.max_row + 1):
        c0 = ws.cell(row=r, column=1).value
        c2 = ws.cell(row=r, column=3).value
        c4 = ws.cell(row=r, column=5).value
        c0s = str(c0).strip() if c0 is not None else ""
        c2s = str(c2).strip() if c2 is not None else ""
        c4s = str(c4).strip() if c4 is not None else ""

        if not c0s and c2s and current is not None:
            current["text"] += " " + c2s
            continue
        if c0s in ("내 용", "회 사 명 :", "결 산 일 :"):
            continue
        if c4s and c0s and c4s != "참조기준":
            current = {"section": current_section, "reference": c4s, "text": c0s}
            items.append(current)
            continue
        if c0s:
            current_section = c0s
            continue
    return items


def match_checklist_items(report_text: str, items: list[dict], min_hits: int = 1) -> list[dict]:
    """returns [{"section","reference","text","keywords","hits","found"}, ...]. found=True면
    항목에서 뽑은 키워드 중 min_hits개 이상이 보고서 본문(공백 제거 후 비교)에 등장함을 의미.
    키워드를 뽑을 수 없는 항목(텍스트가 너무 짧거나 기능어뿐인 경우)은 결과에서 제외한다."""
    norm_report = re.sub(r"\s+", "", report_text or "")
    results = []
    for item in items:
        keywords = _extract_keywords(item["text"])
        if not keywords:
            continue
        hits = [kw for kw in keywords if kw in norm_report]
        found = len(hits) >= min(min_hits, len(keywords))
        results.append({**item, "keywords": keywords, "hits": hits, "found": found})
    return results


def check_disclosure(report_text: str, accounting_standard: str, settings: dict) -> dict:
    """returns {"items": [...], "path": str|None, "error": str|None}."""
    if accounting_standard == "KIFRS":
        path = settings.get("checklist_kifrs_path") or DEFAULT_KIFRS_PATH
        parser = parse_kifrs_checklist
    else:
        path = settings.get("checklist_kgaap_path") or DEFAULT_KGAAP_PATH
        parser = parse_kgaap_checklist

    if not path or not os.path.exists(path):
        return {"items": [], "path": path, "error": f"공시사항점검표 파일을 찾을 수 없습니다: {path}"}
    try:
        raw_items = parser(path)
    except Exception as e:  # noqa: BLE001
        return {"items": [], "path": path, "error": f"공시사항점검표 파싱 실패: {e}"}
    results = match_checklist_items(report_text, raw_items)
    return {"items": results, "path": path, "error": None}
