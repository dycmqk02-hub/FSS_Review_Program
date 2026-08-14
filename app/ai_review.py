"""Claude API / Gemini API를 이용한 AI 심층 리뷰(서술형, 실질적 회계 판단 포함).

로컬 규칙·키워드 기반 검증(review_engine 등)과는 완전히 별개의 기능이다. PDF 원문을
그대로 외부 API로 전송해 LLM이 직접 읽고 판단한 서술형 리뷰를 받아온다. API 키는
소스에 포함하지 않고 secrets.json(프로그램 폴더, git 추적 대상 아님)에서 읽는다.
"""
import base64
import json
import os

from . import settings

SECRETS_PATH = os.path.join(settings._base_dir(), "secrets.json")

_DEFAULT_SECRETS = {
    "claude_api_key": "",
    "claude_model": "claude-sonnet-5",
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
}


def load_secrets() -> dict:
    if os.path.exists(SECRETS_PATH):
        try:
            with open(SECRETS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(_DEFAULT_SECRETS)
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_SECRETS)


def save_secrets(secrets: dict) -> None:
    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        json.dump(secrets, f, ensure_ascii=False, indent=2)


_PROMPT_TEMPLATE = """당신은 Big4 회계법인 품질관리실에서 20년간 근무한 심리위원입니다.
첨부된 재무제표 검토보고서 PDF({doc_desc})를 처음부터 끝까지 직접 읽고, 아래 형식으로
서술형 리뷰를 작성하십시오. 산술적 정합성(합계·소계·총계, 재무제표-주석 간 대사, EPS 등
재계산 가능한 모든 숫자)을 실제로 재계산해 확인하고, 그 다음으로 실질적 회계 판단이
필요한 사항(사업결합·지배력 판단·손상·분류 등)을 짚어내는 것이 핵심입니다. 표면적
키워드 매칭이 아니라 실제 내용을 이해하고 판단하십시오.

[개요] 대상 회사와 재무제표 구분을 한두 문장으로.

[I. 합계·소계·총계 검증] 재무상태표·손익계산서·자본변동표·현금흐름표 전 항목을
실제로 재계산해 일치 여부를 서술.

[II. 재무제표-주석 간 대사] 주요 주석(금융상품, 차입금, 기타부채, EPS 등)이 본문과
일치하는지 대사한 결과.

[III. 발견사항] 🔴(오류)/🟡(확인 필요)/ℹ️(참고사항) 등급으로 구체적 발견사항을 나열.
산술 오류가 없다면 명시하고, 실질적 판단이 필요한 사항을 ℹ️로 제시.

[IV. 연결-별도 일관성 검토] (연결과 별도 두 문서가 모두 주어진 경우만) 자본금 등
일치해야 할 항목과, 종속기업 실적 반영으로 차이가 나는 항목을 구분해 설명.

[V. 실질적 회계처리 검토포인트] 사업결합, 지배력 판단, 손상, 계정 분류 등 감사인이
추가로 확인해야 할 실질적 쟁점을 나열.

[VI. 결론] 산술적 정합성 여부와, 이번 검토에서 가장 중점적으로 다뤄야 할 감사포인트를
요약.

한국어로, 실제 금액과 계정과목명을 인용하며 구체적으로 작성하십시오.
"""


def _build_prompt(is_dual: bool) -> str:
    doc_desc = "연결재무제표와 별도재무제표 검토보고서 2건" if is_dual else "검토보고서 1건"
    return _PROMPT_TEMPLATE.format(doc_desc=doc_desc)


def run_claude_review(pdf_paths: list[str]) -> str:
    secrets = load_secrets()
    api_key = secrets.get("claude_api_key", "").strip()
    if not api_key:
        raise RuntimeError(
            "Claude API 키가 설정되지 않았습니다.\n\n"
            f"{SECRETS_PATH}\n\n"
            "파일을 열어 \"claude_api_key\" 값에 발급받은 키를 입력한 뒤 다시 시도하세요."
        )
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    content = [{"type": "text", "text": _build_prompt(len(pdf_paths) > 1)}]
    for p in pdf_paths:
        with open(p, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
        })
    msg = client.messages.create(
        model=secrets.get("claude_model") or "claude-sonnet-5",
        max_tokens=8000,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def classify_quota_error(err: Exception) -> str | None:
    """429/사용량 한도 오류면 사용자에게 보여줄 안내 문구를 반환하고, 그 외의 오류면 None을 반환한다."""
    try:
        import anthropic
        if isinstance(err, anthropic.RateLimitError):
            retry_after = None
            try:
                retry_after = err.response.headers.get("retry-after")
            except Exception:  # noqa: BLE001
                pass
            wait_txt = f"{retry_after}초 후" if retry_after else "잠시 후"
            return (f"Claude API 사용량 한도(rate limit)에 도달했습니다.\n\n"
                    f"{wait_txt} 다시 시도하세요.")
    except ImportError:
        pass

    try:
        from google.genai import errors as genai_errors
        if isinstance(err, genai_errors.APIError) and (
            getattr(err, "code", None) == 429
            or (getattr(err, "status", "") or "").upper() == "RESOURCE_EXHAUSTED"
        ):
            retry_after = None
            try:
                details = getattr(err, "details", None) or {}
                error_obj = details.get("error", details) if isinstance(details, dict) else {}
                for d in error_obj.get("details", []):
                    if "retryDelay" in d:
                        retry_after = d["retryDelay"]
                        break
            except Exception:  # noqa: BLE001
                pass
            wait_txt = f"{retry_after} 후" if retry_after else "일정 시간 후(보통 24시간 이내)"
            return ("Gemini 무료 API 사용량 한도(할당량)가 초과되어 오늘 가능한 리뷰가 "
                    f"종료되었습니다.\n\n{wait_txt} 다시 시도하세요.\n\n"
                    "무료 티어는 분당/일일 호출 횟수 제한이 있습니다.")
    except ImportError:
        pass

    msg = str(err).lower()
    if "429" in msg or "rate limit" in msg or "resource_exhausted" in msg or "quota" in msg:
        return ("API 사용량 한도(할당량)에 도달한 것으로 보입니다.\n\n"
                "잠시 후 다시 시도하세요.")
    return None


def run_gemini_review(pdf_paths: list[str]) -> str:
    secrets = load_secrets()
    api_key = secrets.get("gemini_api_key", "").strip()
    if not api_key:
        raise RuntimeError(
            "Gemini API 키가 설정되지 않았습니다.\n\n"
            f"{SECRETS_PATH}\n\n"
            "파일을 열어 \"gemini_api_key\" 값을 확인하세요."
        )
    from google import genai

    client = genai.Client(api_key=api_key)
    uploaded = [client.files.upload(file=p) for p in pdf_paths]
    resp = client.models.generate_content(
        model=secrets.get("gemini_model") or "gemini-2.5-flash",
        contents=[_build_prompt(len(pdf_paths) > 1), *uploaded],
    )
    return resp.text
