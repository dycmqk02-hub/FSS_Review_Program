"""검토의견 유형 판단 및 근거문단 존재 여부 확인 (문단49~63 관련 스크리닝)."""
import re

APPROPRIATE_PATTERN = re.compile(r"공정하게\s*표시하지\s*않은\s*사항이\s*발견되지\s*아니하였습니다")


def detect_opinion(text: str) -> dict:
    if "의견거절" in text and "의견거절의 근거" in text:
        opinion_type = "의견거절"
    elif "부적정의견" in text and "부적정의견의 근거" in text:
        opinion_type = "부적정의견"
    elif "한정의견" in text and "한정의견의 근거" in text:
        opinion_type = "한정의견"
    elif APPROPRIATE_PATTERN.search(text):
        opinion_type = "적정(변형 없음)"
    else:
        opinion_type = "판단불가 (표준 문구 미검출 - 육안 확인 필요)"

    checks = []
    basis_kw_map = {
        "한정의견": "한정의견의 근거",
        "부적정의견": "부적정의견의 근거",
        "의견거절": "의견거절의 근거",
    }
    if opinion_type in basis_kw_map:
        basis_kw = basis_kw_map[opinion_type]
        checks.append({
            "item": f"{opinion_type} 표명 시 근거문단(\"{basis_kw}\") 존재 여부 (문단50~56)",
            "ok": basis_kw in text,
        })

    if "계속기업" in text:
        checks.append({
            "item": "계속기업 관련 문구 발견 - 중요한 불확실성 공시 적절성 및 검토의견 영향(문단58~63) 육안 확인 필요",
            "ok": None,
        })

    if "범위제한" in text or "범위 제한" in text:
        checks.append({
            "item": "범위제한 관련 문구 발견 - 문단52~57 절차 이행 여부 육안 확인 필요",
            "ok": None,
        })

    return {"opinion_type": opinion_type, "checks": checks}
