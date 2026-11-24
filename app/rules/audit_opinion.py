"""감사보고서 감사의견 유형 판단 및 관련 단락 스크리닝 (회계감사기준서 700/701/705/706/570).

검토보고서용 opinion_detect.py는 '공정하게 표시하지 않은 사항이 발견되지 아니하였습니다'(검토 결론
문구)를 기준으로 하므로 감사보고서에서는 항상 '판단불가'가 된다. 이 모듈은 감사보고서 표준 문구로
판단하며 결과 포맷({"opinion_type", "checks":[{"item","ok"}]})은 기존과 동일하다.
"""
import re


def _has(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


def _norm(text: str) -> str:
    """공백·줄바꿈 제거 (PDF 줄바꿈으로 표준문구가 끊기는 문제 대응)."""
    return re.sub(r"\s+", "", text)


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

    if re.search(r"(?m)^\s*강\s*조\s*사\s*항\s*$", text):
        checks.append({"item": "강조사항 단락 존재 (감사기준서 706) - 내용 확인", "ok": None})
    if re.search(r"(?m)^\s*기\s*타\s*사\s*항\s*$", text):
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


# ----------------------------------------------------------------------------------------------
# 개요(감사의견/KAM/강조사항/내부회계 등) 추출 - Excel '개요' 시트 및 전기 대비 비교용
# ----------------------------------------------------------------------------------------------
def _para_after(text: str, heading: str, max_chars: int = 160) -> str | None:
    """줄 머리의 단락 제목(heading) 다음 문단 첫 문장(최대 max_chars)."""
    m = re.search(rf"(?m)^\s*{heading}\s*$\n(.+?)(?:\n\s*\n|$)", text, re.S)
    if not m:
        return None
    body = re.sub(r"\s*\n\s*", "", m.group(1)).strip()
    first = re.split(r"(?<=니다\.)", body)[0]
    return first[:max_chars]


def _audit_hours(rep) -> dict:
    """외부감사 실시내용 '감사참여자 구분별 인원수 및 감사시간' 표의 합계열(당기/전기)."""
    out = {}
    if rep is None:
        return out
    started = False
    for p in rep.pages:
        for l in p["lines"]:
            t = l["text"].replace(" ", "")
            if "감사참여자구분별인원수" in t:
                started = True
                continue
            if not started:
                continue
            nums = [tk["t"] for tk in l["toks"] if re.fullmatch(r"[\d,]+|-", tk["t"])]
            if t.startswith("투입인원수") and len(nums) >= 2:
                out["투입인원수"] = (nums[-2], nums[-1])
            elif (t.startswith("합계") or t.startswith("간합계")) and len(nums) >= 2 and "투입시간합계" not in out:
                out["투입시간합계"] = (nums[-2], nums[-1])
            elif t.startswith("3.주요감사실시내용"):
                return out
    return out


def build_overview(text: str, rep=None) -> list[dict]:
    """[{"key","label","value","prior_in_report"}] - 당기 보고서에서 읽은 개요 항목.
    prior_in_report: 당기 보고서 안에 전기 값이 함께 있는 항목(감사시간 등)의 전기 값."""
    t = _norm(text)
    op = detect_audit_opinion(text)
    items = []

    def add(key, label, value, prior=None):
        items.append({"key": key, "label": label, "value": value if value not in (None, "") else "해당없음",
                      "prior_in_report": prior})

    m = re.search(r"우리는\s*(.+?)\s*\(이하", text)
    add("entity", "감사대상 회사", m.group(1).replace("\n", "") if m else None)
    m = re.search(r"제\s*(\d+)\s*기\s*\n?\s*(20\d{2})\s*년\s*(\d{2})\s*월\s*(\d{2})\s*일\s*부터\s*\n?\s*(20\d{2})\s*년\s*(\d{2})\s*월\s*(\d{2})\s*일", text)
    add("period", "회계기간", f"제{m.group(1)}기 {m.group(2)}.{m.group(3)}.{m.group(4)}~{m.group(5)}.{m.group(6)}.{m.group(7)}" if m else None)
    m = re.search(r"([가-힣A-Za-z]+회계법인)", text)
    add("auditor", "감사인", m.group(1) if m else None)
    m = re.search(r"업무수행이사는\s*([가-힣]{2,4})\s*입니다", text)
    add("partner", "업무수행이사", m.group(1) if m else None)
    pos = t.find("업무수행이사는")
    m = re.search(r"(20\d{2})년(\d{1,2})월(\d{1,2})일", t[pos:]) if pos >= 0 else None
    add("report_date", "감사보고서일", f"{m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}" if m else None)
    add("opinion", "감사의견 유형", op["opinion_type"])
    basis = None
    for h in ("한정의견근거", "부적정의견근거", "의견거절근거"):
        if h in t:
            basis = _para_after(text, r"\s*".join(h))
    add("opinion_basis", "의견변형 근거 요지", basis)

    if "계속기업관련중요한불확실성" in t:
        m = re.search(r"영업손실과당기순손실이각각([\d,]+)(백만원|천원)및([\d,]+)(백만원|천원)", t)
        m2 = re.search(r"유동부채가유동자산보다([\d,]+)(백만원|천원)", t)
        gc = "있음"
        if m:
            gc += f" (영업손실 {m.group(1)}{m.group(2)}, 순손실 {m.group(3)}{m.group(4)}"
            gc += f", 유동부채 초과 {m2.group(1)}{m2.group(2)})" if m2 else ")"
    else:
        gc = "없음"
    add("going_concern", "계속기업 관련 중요한 불확실성", gc)
    add("kam", "핵심감사사항(KAM)", " / ".join(op.get("kam_titles") or []) or ("기재됨(제목 자동추출 실패)" if "핵심감사사항" in t else "없음"))
    add("emphasis", "강조사항", _para_after(text, r"강\s*조\s*사\s*항") or "없음")
    add("other_matter", "기타사항", _para_after(text, r"기\s*타\s*사\s*항") or "없음")

    if _has(t, r"내부회계관리제도를감사하였"):
        kind = "감사"
    elif _has(t, r"내부회계관리제도.{0,30}검토하였"):
        kind = "검토"
    else:
        kind = None
    if kind:
        if _has(t, r"중요한취약점") and not _has(t, r"효과적으로설계및운영되고있습니다"):
            icfr = f"{kind} - 비적정(중요한 취약점)"
        elif _has(t, r"의견을표명하지않|의견거절"):
            icfr = f"{kind} - 의견거절 여부 확인"
        elif _has(t, r"효과적으로설계및운영되고있습니다|적정의견을표명하였습니다|발견되지아니하였습니다"):
            icfr = f"{kind} - 적정"
        else:
            icfr = f"{kind} - 의견 확인필요"
        if "독립된감사인의내부회계관리제도감사보고서" in t:
            icfr += " (내부회계관리제도 감사보고서 첨부)"
    else:
        icfr = "기재 없음 (연결보고서는 통상 별도보고서에 첨부)"
    add("icfr", "내부회계관리제도 의견", icfr)

    hours = _audit_hours(rep)
    if "투입인원수" in hours:
        add("staff", "감사 투입인원수(명) - 외부감사 실시내용", hours["투입인원수"][0], hours["투입인원수"][1])
    if "투입시간합계" in hours:
        add("hours", "감사 투입시간 합계(시간) - 외부감사 실시내용", hours["투입시간합계"][0], hours["투입시간합계"][1])
    return items
