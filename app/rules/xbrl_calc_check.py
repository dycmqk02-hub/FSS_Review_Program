"""XBRL Calculation Linkbase 기반 계층별 합계검증.

Calculation Linkbase에는 "부모(합계) 요소 <- 자식(구성항목) 요소, weight" 형태의
summation-item 관계가 트리 전체(가장 하위 leaf부터 중간 소계, 최상위 총계까지) 그대로
들어있다. 이 트리의 모든 부모 노드에 대해 "자식 값(weight 적용) 합 == 부모 값"을
당기/전기 각각 독립적으로 검증하면:
  - 가장 하위(leaf) 계정들의 합이 바로 위 소계와 일치하는지
  - 그 소계가 다시 상위 소계/총계의 자식이라면, 상위 소계의 합도 그 위 총계와 일치하는지
가 트리의 모든 레벨에서 재귀적으로(레벨마다 독립적인 부모 노드 검사로) 커버된다.
예: 유동자산 leaf들의 합 == 유동자산합계, (유동자산합계 + 비유동자산합계) == 자산총계.

leaf 판정/역할 탐색은 xbrl_hierarchy.py, 값 추출은 xbrl_facts.py를 그대로 재사용한다.
"""
import xml.etree.ElementTree as ET

from .xbrl_hierarchy import STATEMENT_ORDER, find_statement_roles, load_labels
from .xbrl_facts import (
    parse_contexts, parse_facts, get_leaf_values, get_equity_leaf_values,
    CONSOLIDATED_MEMBER, SEPARATE_MEMBER,
)
from .xbrl_loader import resolve_xbrl_source, validate_xbrl_files

NS_LINK = "{http://www.xbrl.org/2003/linkbase}"
NS_XLINK = "{http://www.w3.org/1999/xlink}"

FS_KIND_MEMBER = {"consolidated": CONSOLIDATED_MEMBER, "separate": SEPARATE_MEMBER}
TOLERANCE_RATIO = 0.001


def _local_name(href: str) -> str:
    frag = href.split("#")[-1]
    return frag.split("_", 1)[1] if "_" in frag else frag


def parse_calculation_tree(cal_path: str, role_uri: str) -> dict[str, list[tuple[str, float]]]:
    """returns {parent_element: [(child_element, weight), ...]} (해당 role의 전체 합계 트리)."""
    tree = ET.parse(cal_path)
    root = tree.getroot()
    result: dict[str, list[tuple[str, float]]] = {}
    for clink in root.iter(f"{NS_LINK}calculationLink"):
        if clink.attrib.get(f"{NS_XLINK}role") != role_uri:
            continue
        loc_to_elem = {}
        for loc in clink.findall(f"{NS_LINK}loc"):
            label = loc.attrib[f"{NS_XLINK}label"]
            href = loc.attrib[f"{NS_XLINK}href"]
            loc_to_elem[label] = _local_name(href)
        for arc in clink.findall(f"{NS_LINK}calculationArc"):
            parent = loc_to_elem[arc.attrib[f"{NS_XLINK}from"]]
            child = loc_to_elem[arc.attrib[f"{NS_XLINK}to"]]
            weight = float(arc.attrib.get("weight", "1"))
            result.setdefault(parent, []).append((child, weight))
        return result
    return result


def _tree_elements(tree: dict[str, list[tuple[str, float]]]) -> set[str]:
    elements = set(tree.keys())
    for children in tree.values():
        elements.update(c for c, _w in children)
    return elements


def _collect_values(facts, contexts, element_names, target_member) -> dict[str, dict]:
    """returns {element: {segment: (current, prior)}}. segment는 None(시점) 또는 기간버킷 문자열."""
    pseudo_leaves = [{"name": e, "level": 0, "parent": None} for e in element_names]
    rows = get_leaf_values(facts, contexts, pseudo_leaves, target_member)
    value_map: dict[str, dict] = {}
    for r in rows:
        value_map.setdefault(r["label"], {})[r["segment"]] = (r["current"], r["prior"])
    return value_map


def _collect_equity_values(facts, contexts, element_names, target_member) -> dict[str, dict]:
    """returns {element: {(component, segment): (current, prior)}}. 자본구성요소별로 독립 검증."""
    pseudo_leaves = [{"name": e, "level": 0, "parent": None} for e in element_names]
    rows = get_equity_leaf_values(facts, contexts, pseudo_leaves, target_member)
    value_map: dict[str, dict] = {}
    for r in rows:
        key = (r.get("component"), r["segment"])
        value_map.setdefault(r["label"], {})[key] = (r["current"], r["prior"])
    return value_map


def _format_key(key) -> str | None:
    if isinstance(key, tuple):
        component, segment = key
        parts = [p for p in (component, segment) if p]
        return "/".join(parts) or None
    return key


def _check_tree(tree: dict[str, list[tuple[str, float]]], value_map: dict[str, dict],
                 tolerance_ratio: float = TOLERANCE_RATIO) -> tuple[list[dict], list[dict]]:
    """트리의 모든 부모 노드에 대해 당기/전기 각각 '자식 weight합 == 부모값'을 검증.
    부모가 다시 다른 부모의 자식이면(중간 소계) 그 관계도 트리에 별도 항목으로 존재하므로
    이 함수 한 번의 순회로 leaf->소계, 소계->총계 등 모든 레벨이 함께 검증된다."""
    mismatches: list[dict] = []
    skipped: list[dict] = []
    for parent, children in tree.items():
        parent_values = value_map.get(parent)
        if not parent_values:
            continue  # 부모 요소 자체가 본문(연결/별도 단일축)에 없음 - 검증 대상 아님
        for key, (parent_cur, parent_pri) in parent_values.items():
            child_entries = []
            missing = []
            for child, weight in children:
                cv = value_map.get(child, {}).get(key)
                if cv is None:
                    missing.append(child)
                else:
                    child_entries.append((child, weight, cv))
            segment = _format_key(key)
            if missing:
                skipped.append({"parent": parent, "segment": segment, "missing": missing})
                continue
            for period_idx, period_label in ((0, "당기"), (1, "전기")):
                parent_val = (parent_cur, parent_pri)[period_idx]
                computed = sum(weight * cv[period_idx] for _c, weight, cv in child_entries)
                tolerance = max(2.0, abs(parent_val) * tolerance_ratio)
                if abs(computed - parent_val) > tolerance:
                    mismatches.append({
                        "parent": parent, "segment": segment, "period": period_label,
                        "stated": parent_val, "computed": computed, "diff": computed - parent_val,
                        "children": [c for c, _w, _cv in child_entries],
                    })
    return mismatches, skipped


def check_calculation_consistency(cal_path, role_uri, facts, contexts, target_member,
                                   tolerance_ratio: float = TOLERANCE_RATIO) -> tuple[list[dict], list[dict]]:
    tree = parse_calculation_tree(cal_path, role_uri)
    if not tree:
        return [], []
    value_map = _collect_values(facts, contexts, _tree_elements(tree), target_member)
    return _check_tree(tree, value_map, tolerance_ratio)


def check_calculation_consistency_equity(cal_path, role_uri, facts, contexts, target_member,
                                          tolerance_ratio: float = TOLERANCE_RATIO) -> tuple[list[dict], list[dict]]:
    tree = parse_calculation_tree(cal_path, role_uri)
    if not tree:
        return [], []
    value_map = _collect_equity_values(facts, contexts, _tree_elements(tree), target_member)
    return _check_tree(tree, value_map, tolerance_ratio)


def _apply_labels(items: list[dict], labels: dict) -> list[dict]:
    out = []
    for it in items:
        new = dict(it)
        new["parent"] = labels.get(it["parent"], it["parent"])
        if "children" in it:
            new["children"] = [labels.get(c, c) for c in it["children"]]
        if "missing" in it:
            new["missing"] = [labels.get(c, c) for c in it["missing"]]
        out.append(new)
    return out


def check_xbrl_calculations(source_path: str, fs_kind: str) -> tuple[dict, str | None]:
    """source_path: XBRL zip 파일 또는 폴더 경로. fs_kind: 'consolidated' 또는 'separate'.
    returns ({stmt: {"mismatches": [...], "skipped": [...], "note": str|None}}, error_message)."""
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
    except Exception as e:  # noqa: BLE001
        return {}, f"XBRL 파싱 실패: {e}"

    result = {}
    for stmt in STATEMENT_ORDER:
        role_uri = roles.get((stmt, fs_kind))
        if not role_uri:
            kind_label = "연결" if fs_kind == "consolidated" else "별도"
            result[stmt] = {"mismatches": [], "skipped": [],
                             "note": f"XBRL 택소노미에서 {kind_label} {stmt} 역할(role)을 찾지 못했습니다."}
            continue
        tree = parse_calculation_tree(files["calculation"], role_uri)
        if not tree:
            result[stmt] = {"mismatches": [], "skipped": [],
                             "note": "계산 관계(Calculation Linkbase)가 정의되어 있지 않습니다."}
            continue
        if stmt == "자본변동표":
            value_map = _collect_equity_values(facts, contexts, _tree_elements(tree), target_member)
        else:
            value_map = _collect_values(facts, contexts, _tree_elements(tree), target_member)
        mismatches, skipped = _check_tree(tree, value_map)
        mismatches = _apply_labels(mismatches, labels)
        skipped = _apply_labels(skipped, labels)
        result[stmt] = {"mismatches": mismatches, "skipped": skipped, "note": None}

    return result, None
