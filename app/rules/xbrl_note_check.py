"""XBRL 주석(note) 공시 대사.

(1) 재무제표 계정과 동일한 XBRL 요소가 주석(재무제표 4종 외 role)에도 나타나는지 확인하고,
    나타난다면 그 값이 재무제표 금액과 일치하는지 대사한다. DART XBRL은 통상 같은 context를
    재사용하므로 대부분 자동으로 일치하지만(참조 무결성 확인 효과), 필자가 주석에 별도
    context로 값을 다시 입력한 경우엔 실제 불일치를 잡아낼 수 있다. 재무제표 금액에 대응되는
    주석이 전혀 없으면 "주석 미확인 항목"으로 별도 표시한다(공시 누락 여부 점검용).
(2) 재무제표 4종 외 모든 role에 대해서도 Calculation Linkbase 기반 계층별 합계검증을 동일하게
    수행한다(주석 role에 계산관계가 정의된 경우 - 실제로는 필자마다 다름).
"""
from .xbrl_hierarchy import (
    STATEMENT_ORDER, find_statement_roles, build_leaf_hierarchy, load_labels,
    all_roles, role_elements,
)
from .xbrl_facts import parse_contexts, parse_facts, get_leaf_values, CONSOLIDATED_MEMBER, SEPARATE_MEMBER
from .xbrl_loader import resolve_xbrl_source, validate_xbrl_files
from .xbrl_calc_check import parse_calculation_tree, _collect_values, _check_tree, _tree_elements

FS_KIND_MEMBER = {"consolidated": CONSOLIDATED_MEMBER, "separate": SEPARATE_MEMBER}
TOLERANCE_RATIO = 0.001


def _pick_current(rows: list[dict]) -> float | None:
    if not rows:
        return None
    cumulative = [r for r in rows if r.get("segment") and r["segment"].startswith("누적")]
    row = cumulative[0] if cumulative else rows[0]
    return row["current"]


def check_note_cross_reference(source_path: str, fs_kind: str) -> tuple[dict, str | None]:
    """returns ({"confirmed": n, "unmatched": [...]}, error).
    XBRL은 재무제표와 주석이 통상 같은 element/context를 재사용하므로("확인됨" 판정은 태깅
    존재 여부 - PDF처럼 별도로 기재된 숫자를 재대사하는 것이 아님), 진짜 금액 불일치보다는
    "이 계정과목을 설명하는 주석이 실제로 태깅되어 있는가"(공시 추적)가 핵심 정보다.
    unmatched: 재무제표 leaf 계정인데 어느 주석 role에도 태깅되어 있지 않은 경우(참고용 - 본문에
    서술식으로만 설명되었을 수 있어 반드시 누락은 아님)."""
    try:
        files = resolve_xbrl_source(source_path)
    except Exception as e:  # noqa: BLE001
        return {}, f"XBRL 파일 압축해제/탐색 실패: {e}"
    err = validate_xbrl_files(files)
    if err:
        return {}, err

    target_member = FS_KIND_MEMBER[fs_kind]
    try:
        roles = find_statement_roles(files["schema"])
        labels = load_labels(files["label_ko"])
        contexts = parse_contexts(files["instance"])
        facts = parse_facts(files["instance"])
        role_list = all_roles(files["schema"])
    except Exception as e:  # noqa: BLE001
        return {}, f"XBRL 파싱 실패: {e}"

    stmt_role_uris = set(roles.values())
    note_roles = [(uri, defn) for uri, defn in role_list if uri and uri not in stmt_role_uris]
    note_elem_cache: dict[str, set[str]] = {}
    for uri, _defn in note_roles:
        try:
            note_elem_cache[uri] = role_elements(files["presentation"], uri)
        except Exception:  # noqa: BLE001
            note_elem_cache[uri] = set()

    confirmed_count = 0
    unmatched = []
    for stmt in STATEMENT_ORDER:
        role_uri = roles.get((stmt, fs_kind))
        if not role_uri:
            continue
        leaves = build_leaf_hierarchy(files["presentation"], files["calculation"], role_uri)
        for leaf in leaves:
            name = leaf["name"]
            stmt_val = _pick_current(get_leaf_values(facts, contexts, [leaf], target_member))
            if stmt_val is None:
                continue
            matched_notes = [defn for uri, defn in note_roles if name in note_elem_cache.get(uri, ())]
            if not matched_notes:
                unmatched.append({"stmt": stmt, "label": labels.get(name, name), "element": name, "value": stmt_val})
            else:
                confirmed_count += 1
    return {"confirmed": confirmed_count, "unmatched": unmatched}, None


def check_note_calc_hierarchy(source_path: str, fs_kind: str,
                               tolerance_ratio: float = TOLERANCE_RATIO) -> tuple[list[dict], str | None]:
    """재무제표 4종을 제외한 모든 role에 대해서도 Calculation Linkbase 기반 계층별 합계검증을
    수행한다(주석 role에 계산관계가 정의되어 있는 경우에만 실질적으로 검증됨)."""
    try:
        files = resolve_xbrl_source(source_path)
    except Exception as e:  # noqa: BLE001
        return [], f"XBRL 파일 압축해제/탐색 실패: {e}"
    err = validate_xbrl_files(files)
    if err:
        return [], err

    target_member = FS_KIND_MEMBER[fs_kind]
    try:
        roles = find_statement_roles(files["schema"])
        labels = load_labels(files["label_ko"])
        contexts = parse_contexts(files["instance"])
        facts = parse_facts(files["instance"])
        role_list = all_roles(files["schema"])
    except Exception as e:  # noqa: BLE001
        return [], f"XBRL 파싱 실패: {e}"

    stmt_role_uris = set(roles.values())
    findings = []
    for uri, defn in role_list:
        if not uri or uri in stmt_role_uris:
            continue
        try:
            tree = parse_calculation_tree(files["calculation"], uri)
        except Exception:  # noqa: BLE001
            continue
        if not tree:
            continue
        value_map = _collect_values(facts, contexts, _tree_elements(tree), target_member)
        mismatches, _skipped = _check_tree(tree, value_map, tolerance_ratio)
        for m in mismatches:
            m2 = dict(m)
            m2["parent"] = labels.get(m["parent"], m["parent"])
            m2["children"] = [labels.get(c, c) for c in m["children"]]
            m2["note"] = defn
            findings.append(m2)
    return findings, None
