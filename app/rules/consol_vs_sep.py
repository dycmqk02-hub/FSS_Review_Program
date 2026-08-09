"""연결재무제표 vs 별도재무제표 비교 스크리닝 (실무 참고용 - 준칙 명문 조항은 아님)."""

ANCHOR_KEYWORDS = [
    "특수관계자", "종속기업", "관계기업", "공동기업", "내부거래",
    "종속기업투자주식", "지분법", "연결실체", "비지배지분", "영업권",
]

PRACTICE_CHECKLIST = [
    {"item": "별도재무제표상 '종속기업투자주식' 금액과 연결재무제표 주석의 종속기업 취득원가/현황이 대사되는지",
     "note": "연결조정에서 투자주식과 종속기업 자본을 상계하는 근거가 되므로 금액 일치 여부를 수동 확인하십시오."},
    {"item": "연결재무제표 주석에 내부거래(매출·매입·채권·채무) 제거 관련 공시가 있는지",
     "note": "연결실체 내 거래는 연결조정으로 제거되어야 하며, 별도재무제표에는 해당 거래가 그대로 존재해야 합니다."},
    {"item": "특수관계자 공시 범위가 재무제표 종류에 맞게 구성되어 있는지",
     "note": "일반적으로 별도재무제표의 특수관계자 범위(종속·관계기업 포함)가 연결재무제표(연결실체 외부만 해당)보다 넓습니다."},
    {"item": "비지배지분·지분법손익 등 연결 고유 계정이 연결재무제표에만 존재하는지",
     "note": "별도재무제표에는 비지배지분 계정이 존재하지 않아야 하며, 종속기업 투자는 원가법(또는 준칙상 인정되는 방법)으로 표시됩니다."},
    {"item": "연결·별도 검토의견(적정/한정/부적정/의견거절)이 서로 다른 경우 그 사유가 합리적으로 설명되는지",
     "note": "연결과 별도의 왜곡표시 원인(예: 특정 종속기업 이슈)이 각 재무제표에 미치는 영향 범위를 확인하십시오."},
]


def _extract_sections(pages: list[str], anchors: list[str], context_chars: int = 400) -> dict:
    full = "\n".join(pages)
    sections = {}
    for kw in anchors:
        idx = full.find(kw)
        if idx == -1:
            sections[kw] = None
            continue
        start = max(0, idx - 50)
        end = min(len(full), idx + context_chars)
        sections[kw] = full[start:end].replace("\n", " ").strip()
    return sections


def compare_consol_separate(consol_pages: list[str], separate_pages: list[str]) -> dict:
    consol_sections = _extract_sections(consol_pages, ANCHOR_KEYWORDS)
    separate_sections = _extract_sections(separate_pages, ANCHOR_KEYWORDS)

    comparison = []
    for kw in ANCHOR_KEYWORDS:
        comparison.append({
            "keyword": kw,
            "in_consol": consol_sections[kw] is not None,
            "in_separate": separate_sections[kw] is not None,
            "consol_snippet": consol_sections[kw],
            "separate_snippet": separate_sections[kw],
        })

    return {
        "keyword_comparison": comparison,
        "practice_checklist": PRACTICE_CHECKLIST,
    }
