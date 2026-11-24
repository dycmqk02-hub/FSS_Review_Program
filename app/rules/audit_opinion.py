"""감사보고서 감사의견 유형 판단 및 관련 단락 스크리닝 (회계감사기준서 700/701/705/706/570).

검토보고서용 opinion_detect.py는 '공정하게 표시하지 않은 사항이 발견되지 아니하였습니다'(검토 결론
문구)를 기준으로 하므로 감사보고서에서는 항상 '판단불가'가 된다. 이 모듈은 감사보고서 표준 문구로
판단하며 결과 포맷({"opinion_type", "checks":[{"item","ok"}]})은 기존과 동일하다.
"""
import re


def _has(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


def _norm(text: str) -> str:
    return re.sub(r"[ \t　]+", "", text)


def detect_audit_opinion(text: str) -> dict:
    t = _norm(text)
    if _has(t, r"의견거절근거") or _has(t, r"의견을표명하지않습니다"):
        op = "의견거절"
    elif _has(t, r"부적정의견근거"):
        op = "부적정의견"
    elif _has(t, r"한정의견근거"):
        op = "한정의견"
    elif _has(t, r"중요성의관점에서공정하게표시하고있습니다"):
        op = "적정(변형 없음)"
    else:
        op = "판단불가 (표준 문구 미검출 - 육안 확인 필요)"

    checks = []
    basis = {"적정(변형 없음)": "감사의견근거", "한정의견": "한정의견근거", "부적정의견": "부적정의견근거",
             "의견거절": "의견거절근거"}.get(op)
    if basis:
        checks.append({"item": f"의견근거 단락('{basis}') 존재 (감사기준서 700 문단28 / 705)", "ok": basis in t})

    if _has(t, r"계속기업관련중요한불확실성"):
        m = re.search(r"영업손실과당기순손실이각각([\d,]+)(백만원|천원)및([\d,]+)(백만원|천원)", t)
        detail = f" - 서술금액: 영업손실 {m.group(1)}{m.group(2)}, 순손실 {m.group(3)}{m.group(4)} ('본문수치대사'에서 재무제표와 대사)" if m else ""
        checks.append({"item": "'계속기업 관련 중요한 불확실성' 단락 존재 (감사기준서 570) - 주석 공시 및 서술금액 정합성 확인 필요" + detail,
                       "ok": None})
    elif "계속기업" in t:
        checks.append({"item": "계속기업 언급 있음 - 중요한 불확실성 단락 필요 여부 육안 확인", "ok": None})

    kam = []
    if "핵심감사사항" in t:
        # '핵심감사사항으로 결정된 이유' 직전 줄을 KAM 제목으로 본다
        for m in re.finditer(r"\n([^\n]{2,40})\n+\s*핵심감사사항으로\s*결정된\s*이유", text):
            kam.append(m.group(1).strip())
        checks.append({"item": f"핵심감사사항(KAM) 단락 존재 (감사기준서 701) - {len(kam)}건: " + (", ".join(kam) if kam else "제목 자동추출 실패"),
                       "ok": True})
        if kam:
            checks.append({"item": "각 KAM에 '감사에서 다루어진 방법' 기재", "ok": t.count("핵심감사사항이감사에서다루어진방법") >= len(kam)})
    else:
        checks.append({"item": "핵심감사사항(KAM) 단락 미검출 - 상장회사 등 적용대상 여부 확인 (감사기준서 701)", "ok": False})

    if "강조사항" in t:
        checks.append({"item": "강조사항 단락 존재 (감사기준서 706) - 내용 확인", "ok": None})
    if "기타사항" in t:
        checks.append({"item": "기타사항 단락 존재 (감사기준서 706) - 내용 확인", "ok": None})

    if "내부회계관리제도" in t:
        icfr = "감사" if _has(t, r"내부회계관리제도를감사하였") else ("검토" if _has(t, r"내부회계관리제도.{0,20}검토") else "언급")
        icfr_op = "적정" if _has(t, r"적정의견을표명하였습니다|중요성의관점에서효과적으로설계") else "확인필요"
        checks.append({"item": f"내부회계관리제도 {icfr} 관련 기재 - 의견: {icfr_op}", "ok": icfr_op == "적정" or None})

    m = re.search(r"(20\d{2})년(\d{1,2})월(\d{1,2})일", t[t.rfind("감사인의책임"):] if "감사인의책임" in t else t)
    if m:
        checks.append({"item": f"감사보고서일 기재: {m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}", "ok": True})
    m = re.search(r"업무수행이사는([가-힣]{2,4})입니다", t)
    checks.append({"item": f"업무수행이사 이름 기재 (감사기준서 700 문단46)" + (f": {m.group(1)}" if m else " 미검출"), "ok": bool(m)})
    return {"opinion_type": op, "checks": checks, "kam_titles": kam}
