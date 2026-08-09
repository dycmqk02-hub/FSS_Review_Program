"""비교표시 재무정보 관련 스크리닝 (문단47~48)."""


def check_comparative(text: str) -> list[dict]:
    checks = [
        {"item": "비교표시(전년도 대응기간) 관련 문구 존재",
         "ok": ("전년도" in text) or ("비교표시" in text)},
        {"item": "기타사항 문단 존재",
         "ok": "기타사항" in text},
        {"item": "타감사인/전임감사인 검토 관련 언급 존재 (문단48(2))",
         "ok": ("타감사인" in text) or ("전임감사인" in text)},
        {"item": "'검토받지 아니한(않은)' 비교재무제표 문구 존재 (문단48(3))",
         "ok": ("검토받지 아니한" in text) or ("검토받지 않은" in text) or ("검토 받지 않은" in text)},
        {"item": "'감사받지 아니한(않은)' 전기말 재무상태표 문구 존재 (문단48(4))",
         "ok": ("감사받지 아니한" in text) or ("감사받지 않은" in text) or ("감사 받지 않은" in text)},
        {"item": "전기 감사보고서 일자·의견 요약 언급 존재 (문단48(4))",
         "ok": ("감사보고서" in text) and any(k in text for k in ["적정의견", "한정의견", "부적정의견", "의견거절"])},
    ]
    return checks
