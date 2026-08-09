"""분·반기재무제표 검토준칙 문단46(검토보고서 필수 기재사항) 체크리스트."""
import re

CHECKLIST_46 = [
    {"id": "46-2", "category": "형식", "para": "문단46(2)", "title": "수신인 표시",
     "any_of": ["귀중"], "required": True},
    {"id": "46-3", "category": "형식", "para": "문단46(3)", "title": "검토대상 재무제표 명칭·기준일·보고기간 문단",
     "any_of": ["검토대상 재무제표", "재무상태표"], "required": True},
    {"id": "46-4", "category": "형식", "para": "문단46(4)", "title": "재무제표에 대한 경영진의 책임 문단",
     "any_of": ["재무제표에 대한 경영진의 책임", "경영진의 책임"], "required": True},
    {"id": "46-4a", "category": "형식", "para": "문단46(4)", "title": "적용 회계처리기준 명칭 명시",
     "any_of": ["한국채택국제회계기준", "일반기업회계기준"], "required": True},
    {"id": "46-5", "category": "형식", "para": "문단46(5)", "title": "감사인의 책임 문단",
     "any_of": ["감사인의 책임"], "required": True},
    {"id": "46-6", "category": "형식", "para": "문단46(6)", "title": "검토가 이 준칙에 따라 수행되었다는 문구",
     "any_of": ["분·반기재무제표 검토준칙", "분ㆍ반기재무제표 검토준칙", "분반기재무제표 검토준칙"], "required": True},
    {"id": "46-7", "category": "형식", "para": "문단46(7)", "title": "감사보다 범위가 제한적이며 감사의견을 표명하지 않는다는 문구",
     "any_of": ["감사의견을 표명하지 아니합니다", "감사의견을 표명하지 않습니다"], "required": True},
    {"id": "46-8", "category": "형식", "para": "문단46(8)", "title": "검토의견(결론) 문단",
     "any_of": ["검토의견", "한정의견", "부적정의견", "의견거절"], "required": True},
    {"id": "46-10", "category": "형식", "para": "문단46(10)", "title": "검토보고서 일자",
     "any_of": [r"\d{4}\s*[.년]\s*\d{1,2}\s*[.월]\s*\d{1,2}\s*일?"], "required": True, "regex": True},
    {"id": "46-11", "category": "형식", "para": "문단46(11)", "title": "감사인의 주소",
     "any_of": ["서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "경기도", "특별자치시"],
     "required": True},
    {"id": "46-12", "category": "형식", "para": "문단46(12)", "title": "감사인의 명칭과 서명",
     "any_of": ["회계법인", "대표이사"], "required": True},
    {"id": "46-1", "category": "형식(요약FS)", "para": "문단46-1", "title": "요약중간재무제표 해당 여부(감지된 경우 아래 문단65 항목도 확인)",
     "any_of": ["요약중간재무제표", "요약 중간재무제표", "요약재무제표"], "required": False},
    {"id": "65", "category": "형식(요약FS)", "para": "문단65", "title": "요약재무제표 이용 안내 문구(감사된 직전 연간재무제표와 함께 이해)",
     "any_of": ["감사된 직전 연간재무제표와 함께 이해"], "required": False},
    {"id": "47-48", "category": "비교표시", "para": "문단47~48", "title": "기타사항 문단(비교표시 재무정보 관련) 존재",
     "any_of": ["기타사항"], "required": False},
    {"id": "58", "category": "강조사항", "para": "문단58~63", "title": "강조사항 문단 존재(해당 시)",
     "any_of": ["강조사항"], "required": False},
    {"id": "36", "category": "경영진진술", "para": "문단36", "title": "서면진술(경영진확인서) 관련 언급(검토조서 확인 필요 - 보고서 본문에는 통상 미기재)",
     "any_of": ["서면진술", "경영진확인서"], "required": False},
]


def evaluate_checklist(text: str, extra_items: list[dict] | None = None) -> list[dict]:
    items = list(CHECKLIST_46)
    if extra_items:
        items = items + extra_items

    results = []
    for item in items:
        found = False
        matched = None
        for kw in item.get("any_of", []):
            if item.get("regex"):
                m = re.search(kw, text)
                if m:
                    found = True
                    matched = m.group(0)
                    break
            elif kw in text:
                found = True
                matched = kw
                break
        results.append({**item, "found": found, "matched": matched})
    return results
