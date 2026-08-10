"""XBRL Presentation/Calculation Linkbase 기반 계정 계층구조 및 최하위(leaf) 계정 판정.

leaf 판정 3대 조건 (모두 만족해야 leaf):
  1) Abstract가 아님 (헤더성 요소가 아님)
  2) Presentation Linkbase 트리상 자식(하위 세부항목)이 없음
  3) Calculation Linkbase에서 합계의 부모(summation-item의 from)로 쓰이지 않음
     (Presentation상 자식이 없어도 "자산총계"처럼 Calculation상 합계 역할이면 leaf가 아님)

추가로 요소명이 Table/Axis/Domain/Member/LineItems로 끝나는 차원(dimension) 메타데이터
요소는 실제 계정이 아니므로 애초에 leaf 후보에서 제외한다.

role(재무제표 종류 x 연결/별도)은 특정 회사에 고정된 코드가 아니라, 스키마의
link:roleType/definition 텍스트에서 키워드로 동적 탐색한다(회사마다 세부 서식이
달라 D431410 같은 구체적 코드가 항상 같지 않을 수 있음).
"""
import xml.etree.ElementTree as ET
from collections import defaultdict

NS_LINK = "{http://www.xbrl.org/2003/linkbase}"
NS_XLINK = "{http://www.w3.org/1999/xlink}"

STATEMENT_ORDER = ["재무상태표", "손익계산서", "자본변동표", "현금흐름표"]
STATEMENT_KEYWORDS = {
    "재무상태표": ["재무상태표"],
    "손익계산서": ["포괄손익계산서", "손익계산서"],
    "자본변동표": ["자본변동표"],
    "현금흐름표": ["현금흐름표"],
}
NON_ACCOUNT_SUFFIXES = ("Abstract", "Table", "Axis", "Domain", "Member", "LineItems")


def _local_name(href: str) -> str:
    frag = href.split("#")[-1]
    return frag.split("_", 1)[1] if "_" in frag else frag


def _is_structural(name: str) -> bool:
    return any(name.endswith(suf) for suf in NON_ACCOUNT_SUFFIXES)


def find_statement_roles(xsd_path: str) -> dict:
    """returns {(stmt_key, 'consolidated'|'separate'): role_uri}
    stmt_key ∈ STATEMENT_ORDER. 같은 문(門)에 여러 서식이 있으면 먼저 발견된 것을 사용."""
    tree = ET.parse(xsd_path)
    root = tree.getroot()
    result: dict[tuple[str, str], str] = {}
    for role_type in root.iter(f"{NS_LINK}roleType"):
        role_uri = role_type.attrib.get("roleURI", "")
        defn_el = role_type.find(f"{NS_LINK}definition")
        if defn_el is None or not defn_el.text:
            continue
        defn = defn_el.text
        for stmt_key in STATEMENT_ORDER:
            if not any(kw in defn for kw in STATEMENT_KEYWORDS[stmt_key]):
                continue
            if "별도" in defn:
                kind = "separate"
            elif "연결" in defn:
                kind = "consolidated"
            else:
                continue  # 연결/별도 구분이 불명확한 역할은 스킵 (예: 주석용 역할)
            result.setdefault((stmt_key, kind), role_uri)
            break
    return result


def all_roles(xsd_path: str) -> list[tuple[str, str]]:
    """스키마에 정의된 모든 role의 (roleURI, definition) 목록. 재무제표 4종 외의 role은
    대부분 주석(note) 공시용이다."""
    tree = ET.parse(xsd_path)
    root = tree.getroot()
    result = []
    for role_type in root.iter(f"{NS_LINK}roleType"):
        role_uri = role_type.attrib.get("roleURI", "")
        defn_el = role_type.find(f"{NS_LINK}definition")
        result.append((role_uri, defn_el.text if defn_el is not None and defn_el.text else ""))
    return result


def role_elements(pre_path: str, role_uri: str) -> set[str]:
    """해당 role의 Presentation Linkbase에 등장하는 모든 요소명 집합
    (재무제표 계정이 어느 주석 role에도 등장하는지 대사할 때 사용)."""
    _roots, _children, all_elems = _parse_presentation_role(pre_path, role_uri)
    return all_elems


def _parse_presentation_role(pre_path: str, role_uri: str):
    tree = ET.parse(pre_path)
    root = tree.getroot()
    for plink in root.iter(f"{NS_LINK}presentationLink"):
        if plink.attrib.get(f"{NS_XLINK}role") != role_uri:
            continue
        loc_to_elem = {}
        for loc in plink.findall(f"{NS_LINK}loc"):
            label = loc.attrib[f"{NS_XLINK}label"]
            href = loc.attrib[f"{NS_XLINK}href"]
            loc_to_elem[label] = _local_name(href)
        children: dict[str, list[tuple[float, str]]] = defaultdict(list)
        all_children = set()
        for arc in plink.findall(f"{NS_LINK}presentationArc"):
            frm = loc_to_elem[arc.attrib[f"{NS_XLINK}from"]]
            to = loc_to_elem[arc.attrib[f"{NS_XLINK}to"]]
            order = float(arc.attrib.get("order", "0"))
            children[frm].append((order, to))
            all_children.add(to)
        all_elems = set(loc_to_elem.values())
        roots = sorted(e for e in all_elems if e not in all_children)
        return roots, children, all_elems
    return [], {}, set()


def _parse_calculation_parents(cal_path: str, role_uri: str) -> set:
    tree = ET.parse(cal_path)
    root = tree.getroot()
    for clink in root.iter(f"{NS_LINK}calculationLink"):
        if clink.attrib.get(f"{NS_XLINK}role") != role_uri:
            continue
        loc_to_elem = {}
        for loc in clink.findall(f"{NS_LINK}loc"):
            label = loc.attrib[f"{NS_XLINK}label"]
            href = loc.attrib[f"{NS_XLINK}href"]
            loc_to_elem[label] = _local_name(href)
        parents = set()
        for arc in clink.findall(f"{NS_LINK}calculationArc"):
            parents.add(loc_to_elem[arc.attrib[f"{NS_XLINK}from"]])
        return parents
    return set()


def load_labels(lab_path: str) -> dict[str, str]:
    """요소명 -> 한글(또는 해당 언어) 표준 라벨."""
    tree = ET.parse(lab_path)
    root = tree.getroot()
    loc_to_element = {}
    for loc in root.iter(f"{NS_LINK}loc"):
        label = loc.attrib[f"{NS_XLINK}label"]
        href = loc.attrib[f"{NS_XLINK}href"]
        loc_to_element[label] = _local_name(href)
    label_text: dict[str, dict[str, str]] = {}
    for lbl in root.iter(f"{NS_LINK}label"):
        label_id = lbl.attrib[f"{NS_XLINK}label"]
        role = lbl.attrib.get(f"{NS_XLINK}role", "")
        label_text.setdefault(label_id, {})[role] = lbl.text or ""
    arc_map = {}
    for arc in root.iter(f"{NS_LINK}labelArc"):
        arc_map[arc.attrib[f"{NS_XLINK}from"]] = arc.attrib[f"{NS_XLINK}to"]
    element_to_label = {}
    std_role = "http://www.xbrl.org/2003/role/label"
    for loc_label, elem_name in loc_to_element.items():
        target = arc_map.get(loc_label)
        if target and target in label_text:
            roles = label_text[target]
            element_to_label[elem_name] = roles.get(std_role) or next(iter(roles.values()), elem_name)
    return element_to_label


def build_leaf_hierarchy(pre_path: str, cal_path: str, role_uri: str) -> list[dict]:
    """returns [{"name":, "level":, "parent":}, ...] - leaf 요소만, 표시 순서(계층 등장 순) 유지."""
    roots, children, _all_elems = _parse_presentation_role(pre_path, role_uri)
    calc_parents = _parse_calculation_parents(cal_path, role_uri)

    leaves: list[dict] = []

    def walk(node: str, level: int, parent: str | None):
        if _is_structural(node):
            for _order, child in sorted(children.get(node, []), key=lambda x: x[0]):
                walk(child, level + 1, node)
            return
        kids = sorted(children.get(node, []), key=lambda x: x[0])
        is_leaf = (not kids) and (node not in calc_parents)
        if is_leaf:
            leaves.append({"name": node, "level": level, "parent": parent})
        for _order, child in kids:
            walk(child, level + 1, node)

    for r in roots:
        walk(r, 0, None)
    return leaves
