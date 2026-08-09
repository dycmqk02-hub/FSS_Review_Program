"""전기말 대비 당반기중 회계처리 변경 여부 키워드 탐지."""
from .. import pdf_utils

CHANGE_KEYWORDS = [
    "회계정책의 변경",
    "회계추정의 변경",
    "회계추정치의 변경",
    "최초 적용",
    "조기적용",
    "소급적용",
    "전진적용",
    "재작성하였습니다",
    "재작성되었습니다",
    "기업회계기준서 제1116호",
    "기업회계기준서 제1109호",
    "기업회계기준서 제1115호",
    "기업회계기준서 제1117호",
    "일반기업회계기준 제",
    "개정된 기업회계기준서",
    "새로운 기업회계기준서",
]


def detect_accounting_changes(pages: list[str]) -> list[dict]:
    results = []
    seen = set()
    for page_no, text in enumerate(pages, start=1):
        for kw in CHANGE_KEYWORDS:
            for snippet in pdf_utils.find_context_snippets(text, [kw], window=80):
                key = (kw, snippet)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"page": page_no, "keyword": kw, "snippet": snippet})
    return results
