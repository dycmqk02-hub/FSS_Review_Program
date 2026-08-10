"""XBRL 기반 재무제표 간 교차검증(FS간 검증).

동일 계정(예: 반기순이익, 자본)이 여러 재무제표에 서로 다른 context(차원)로 흩어져
보고되지만 실제로는 같은 금액이어야 하는 경우를 대사한다:
  - 반기순이익(ProfitLoss): 손익계산서/현금흐름표(연결·별도 단일축) vs
    자본변동표(지배기업지분 + 비지배지분, ComponentsOfEquityAxis 합)
  - 자본총계(Equity): 재무상태표(단일축) vs 자본변동표(지배기업지분 + 비지배지분 합)
실제 하림 XBRL로 검증한 결과 두 값 모두 소수점 오차 없이 정확히 일치함을 확인했다."""
from .xbrl_facts import (
    parse_contexts, parse_facts, get_leaf_values, get_equity_leaf_values,
    CONSOLIDATED_MEMBER, SEPARATE_MEMBER,
)
from .xbrl_hierarchy import load_labels
from .xbrl_loader import resolve_xbrl_source, validate_xbrl_files

FS_KIND_MEMBER = {"consolidated": CONSOLIDATED_MEMBER, "separate": SEPARATE_MEMBER}
OWNERS_MEMBER = "EquityAttributableToOwnersOfParentMember"
NCI_MEMBER = "NoncontrollingInterestsMember"
TOLERANCE_RATIO = 0.001

CROSS_CHECK_ITEMS = [
    ("반기순이익(ProfitLoss)", "ProfitLoss", "손익계산서/현금흐름표"),
    ("자본총계(Equity)", "Equity", "재무상태표"),
]


def _pseudo(name: str) -> list[dict]:
    return [{"name": name, "level": 0, "parent": None}]


def _single_axis_value(facts, contexts, element, target_member):
    rows = get_leaf_values(facts, contexts, _pseudo(element), target_member)
    if not rows:
        return None
    cumulative = [r for r in rows if r["segment"] and r["segment"].startswith("누적")]
    row = cumulative[0] if cumulative else rows[0]
    return row["current"], row["prior"]


def _equity_total_value(facts, contexts, element, target_member):
    """자본변동표 문맥에서 지배기업지분+비지배지분 합(당기/전기). 둘 다 없으면 None."""
    rows = get_equity_leaf_values(facts, contexts, _pseudo(element), target_member)
    owners = next((r for r in rows if r.get("component") == OWNERS_MEMBER), None)
    nci = next((r for r in rows if r.get("component") == NCI_MEMBER), None)
    if owners is None and nci is None:
        return None
    cur = (owners["current"] if owners else 0.0) + (nci["current"] if nci else 0.0)
    pri = (owners["prior"] if owners else 0.0) + (nci["prior"] if nci else 0.0)
    return cur, pri


def check_cross_statement_xbrl(source_path: str, fs_kind: str,
                                tolerance_ratio: float = TOLERANCE_RATIO) -> tuple[list[dict], str | None]:
    """returns (findings, error_message). findings: [{"item","period","value_a","source_a",
    "value_b","source_b","diff"}, ...] (불일치 항목만 - 일치하는 항목은 포함하지 않음)."""
    try:
        files = resolve_xbrl_source(source_path)
    except Exception as e:  # noqa: BLE001
        return [], f"XBRL 파일 압축해제/탐색 실패: {e}"

    err = validate_xbrl_files(files)
    if err:
        return [], err

    target_member = FS_KIND_MEMBER[fs_kind]
    try:
        contexts = parse_contexts(files["instance"])
        facts = parse_facts(files["instance"])
        load_labels(files["label_ko"])  # 라벨 로드 실패 여부만 확인(현재 findings엔 원소명 그대로 사용)
    except Exception as e:  # noqa: BLE001
        return [], f"XBRL 파싱 실패: {e}"

    findings = []
    for display_name, element, source_a_label in CROSS_CHECK_ITEMS:
        single = _single_axis_value(facts, contexts, element, target_member)
        equity = _equity_total_value(facts, contexts, element, target_member)
        if single is None or equity is None:
            continue
        # 당기(가장 최근 시점)만 비교한다: 자본변동표는 통상 '반기말' 시점만 지배기업지분/
        # 비지배지분으로 태깅되고 재무상태표의 비교표시 시점(전기 '기말', 회계연도 말)과
        # 자본변동표의 '전반기말'(반기 기준) 날짜가 실제로 달라 전기 비교는 신뢰할 수 없다.
        for period_idx, period_label in ((0, "당기"),):
            a, b = single[period_idx], equity[period_idx]
            tol = max(2.0, abs(a) * tolerance_ratio)
            if abs(a - b) > tol:
                findings.append({
                    "item": f"{display_name} ({period_label})",
                    "values": [
                        {"source": source_a_label, "label": element, "value": a},
                        {"source": "자본변동표(지배기업지분+비지배지분)", "label": element, "value": b},
                    ],
                    "diff": a - b,
                })
    return findings, None
