"""감사보고서 필수 기재사항 체크리스트 (회계감사기준서 700/701/570, 외부감사법 시행령).
검토준칙 문단46 체크리스트(checklist_46.py)와 동일한 결과 포맷을 사용해 기존 UI가 그대로 렌더링한다."""
import re

AUDIT_CHECKLIST = [
    {"id": "A700-21", "category": "형식", "para": "700 문단21", "title": "제목 - '독립된 감사인의 감사보고서'",
     "any_of": [r"독립된\s*감사인의\s*감사보고서"], "regex": True, "required": True},
    {"id": "A700-22", "category": "형식", "para": "700 문단22", "title": "수신인 표시(주주 및 이사회 귀중 등)",
     "any_of": ["귀중"], "required": True},
    {"id": "A700-23", "category": "감사의견", "para": "700 문단23~27", "title": "'감사의견' 단락 및 감사대상 재무제표 명칭·기간",
     "any_of": [r"감사의견\s*\n", r"재무제표를\s*감사하였습니다"], "regex": True, "required": True},
    {"id": "A700-28", "category": "감사의견", "para": "700 문단28", "title": "'감사의견근거' 단락 (독립성·윤리적 요구사항 포함)",
     "any_of": [r"의견\s*근거"], "regex": True, "required": True},
    {"id": "A700-28b", "category": "감사의견", "para": "700 문단28(c)", "title": "윤리적 요구사항에 따른 독립성 언급",
     "any_of": [r"독립적이며"], "regex": True, "required": True},
    {"id": "A570-22", "category": "계속기업", "para": "570 문단22", "title": "계속기업 관련 중요한 불확실성 단락 (해당 시)",
     "any_of": [r"계속기업\s*관련\s*중요한\s*불확실성"], "regex": True, "required": False},
    {"id": "A701-11", "category": "핵심감사사항", "para": "701 문단11~13", "title": "핵심감사사항 단락 (상장회사 등)",
     "any_of": ["핵심감사사항"], "required": False},
    {"id": "A701-13", "category": "핵심감사사항", "para": "701 문단13", "title": "KAM - '감사에서 다루어진 방법' 기술",
     "any_of": [r"감사에서\s*다루어진\s*방법"], "regex": True, "required": False},
    {"id": "A700-33", "category": "책임", "para": "700 문단33~36", "title": "경영진과 지배기구의 책임 단락",
     "any_of": [r"경영진과\s*지배기구의\s*책임"], "regex": True, "required": True},
    {"id": "A700-37", "category": "책임", "para": "700 문단37~40", "title": "재무제표감사에 대한 감사인의 책임 단락",
     "any_of": [r"감사에\s*대한\s*감사인의\s*책임"], "regex": True, "required": True},
    {"id": "A700-40", "category": "책임", "para": "700 문단40", "title": "부정·오류, 내부통제, 계속기업, 전반적 표시 평가 기술",
     "any_of": [r"전문가적\s*의구심"], "regex": True, "required": True},
    {"id": "A700-46", "category": "서명", "para": "700 문단46", "title": "업무수행이사 이름 기재 (상장회사)",
     "any_of": [r"업무수행이사는"], "regex": True, "required": True},
    {"id": "A700-47", "category": "서명", "para": "700 문단47~48", "title": "감사인 명칭·주소 및 대표이사",
     "any_of": [r"회계법인"], "regex": True, "required": True},
    {"id": "A700-49", "category": "서명", "para": "700 문단49", "title": "감사보고서일",
     "any_of": [r"20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"], "regex": True, "required": True},
    {"id": "A720", "category": "기타", "para": "720", "title": "기타정보 단락 (해당 시)",
     "any_of": [r"기타\s*정보"], "regex": True, "required": False},
    {"id": "A706", "category": "기타", "para": "706", "title": "강조사항/기타사항 단락 (해당 시)",
     "any_of": ["강조사항", "기타사항"], "required": False},
    {"id": "ACT-ICFR", "category": "외감법", "para": "외감법 §8", "title": "내부회계관리제도 감사(검토)의견 언급",
     "any_of": ["내부회계관리제도"], "required": False},
    {"id": "ACT-외감", "category": "외감법", "para": "외감법 §18", "title": "외부감사 실시내용 첨부",
     "any_of": [r"외부감사\s*실시내용"], "regex": True, "required": True},
    {"id": "FS-주석", "category": "재무제표", "para": "1001", "title": "재무제표 4종 + 주석 구성",
     "any_of": [r"현금흐름표"], "regex": True, "required": True},
]


def evaluate_audit_checklist(text: str, extra_items: list[dict] | None = None) -> list[dict]:
    items = AUDIT_CHECKLIST + list(extra_items or [])
    flat = re.sub(r"\s+", "", text)   # PDF 줄바꿈으로 '독\n립적이며'처럼 단어가 끊기는 경우 대비
    out = []
    for item in items:
        found, matched = False, None
        for kw in item.get("any_of", []):
            if item.get("regex"):
                m = re.search(kw, text) or re.search(kw.replace(r"\s*", ""), flat)
            else:
                m = kw if (kw in text or kw.replace(" ", "") in flat) else None
            if m:
                found, matched = True, (m.group(0).strip() if item.get("regex") else kw)
                break
        out.append({**item, "found": found, "matched": matched})
    return out
