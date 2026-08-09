"""XBRL(zip/폴더)로부터 4대 재무제표 증감분석표를 산출 - variance_analysis.build_variance_tables와
동일한 형태({stmt: {"rows": [...], "note": ...}})로 반환해 기존 렌더링/내보내기 코드를 그대로 재사용한다.

leaf(가장 하위계정) 판정: Presentation/Calculation Linkbase + Abstract 속성 기반 (xbrl_hierarchy.py)
값 추출: 인스턴스 문서 context/fact 매칭, 자본변동표는 자본구성요소 축까지 포함한 2차원 매칭
(xbrl_facts.py)."""
from .xbrl_hierarchy import STATEMENT_ORDER, find_statement_roles, build_leaf_hierarchy, load_labels
from .xbrl_facts import (
    parse_contexts, parse_facts, get_leaf_values, get_equity_leaf_values,
    CONSOLIDATED_MEMBER, SEPARATE_MEMBER,
)
from .xbrl_loader import resolve_xbrl_source, validate_xbrl_files

FS_KIND_MEMBER = {"consolidated": CONSOLIDATED_MEMBER, "separate": SEPARATE_MEMBER}


def _apply_labels(rows: list[dict], labels: dict) -> list[dict]:
    out = []
    for r in rows:
        label = labels.get(r["label"], r["label"])
        if "component" in r:
            comp_label = labels.get(r["component"], r["component"])
            label = f"{label} - {comp_label}"
        out.append({**r, "label": label})
    return out


def build_variance_tables_from_xbrl(source_path: str, fs_kind: str) -> tuple[dict, str | None]:
    """source_path: XBRL zip 파일 또는 폴더 경로. fs_kind: 'consolidated' 또는 'separate'.
    returns (variance_tables, error_message). error_message가 있으면 variance_tables는 빈 dict."""
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
            result[stmt] = {"rows": [], "note": f"XBRL 택소노미에서 {kind_label} {stmt} 역할(role)을 찾지 못했습니다."}
            continue
        leaves = build_leaf_hierarchy(files["presentation"], files["calculation"], role_uri)
        if stmt == "자본변동표":
            rows = get_equity_leaf_values(facts, contexts, leaves, target_member)
        else:
            rows = get_leaf_values(facts, contexts, leaves, target_member)
        rows = _apply_labels(rows, labels)
        note = None if rows else "XBRL에서 leaf 계정에 대한 당기/전기 값을 찾지 못했습니다."
        result[stmt] = {"rows": rows, "note": note}

    return result, None
