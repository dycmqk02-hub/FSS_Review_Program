"""XBRL 인스턴스 문서(.xbrl)에서 요소별 당기/전기 사실(fact) 값 추출.

XBRL 인스턴스는 같은 계정 요소라도 주석 세부공시용으로 여러 차원(axis)이 덧붙은 context가
같이 존재하므로(예: 현금및현금성자산을 금융상품 분류별로 쪼갠 주석 수치), 본문 재무제표
숫자만 골라내려면 "연결/별도 구분 축 하나만 있고 다른 축은 없는" context만 사용해야 한다.
"""
import xml.etree.ElementTree as ET
from datetime import date

NS_XBRLI = "{http://www.xbrl.org/2003/instance}"

CONSOLIDATED_MEMBER = "ConsolidatedMember"
SEPARATE_MEMBER = "SeparateMember"


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def parse_contexts(xbrl_path: str) -> dict[str, dict]:
    """returns {context_id: {"instant":, "start":, "end":, "dims": {axis_local: member_local}}}"""
    tree = ET.parse(xbrl_path)
    root = tree.getroot()
    contexts = {}
    for ctx in root.iter(f"{NS_XBRLI}context"):
        cid = ctx.attrib["id"]
        period = ctx.find(f"{NS_XBRLI}period")
        instant = period.findtext(f"{NS_XBRLI}instant") if period is not None else None
        start = period.findtext(f"{NS_XBRLI}startDate") if period is not None else None
        end = period.findtext(f"{NS_XBRLI}endDate") if period is not None else None
        dims: dict[str, str] = {}
        entity = ctx.find(f"{NS_XBRLI}entity")
        segment = entity.find(f"{NS_XBRLI}segment") if entity is not None else None
        if segment is not None:
            for em in segment:
                if _local(em.tag) != "explicitMember":
                    continue
                axis_local = em.attrib.get("dimension", "").split(":")[-1]
                member_local = (em.text or "").split(":")[-1]
                dims[axis_local] = member_local
        contexts[cid] = {"instant": instant, "start": start, "end": end, "dims": dims}
    return contexts


def parse_facts(xbrl_path: str) -> dict[str, list[tuple[str, str]]]:
    """returns {element_local_name: [(context_id, value_str), ...]}"""
    tree = ET.parse(xbrl_path)
    root = tree.getroot()
    facts: dict[str, list[tuple[str, str]]] = {}
    for el in root:
        ctx_ref = el.attrib.get("contextRef")
        if not ctx_ref:
            continue
        facts.setdefault(_local(el.tag), []).append((ctx_ref, el.text))
    return facts


def _duration_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _duration_bucket(days: int) -> str:
    """당기/전기 구간을 대략적인 범위로 묶는다. 윤년 등으로 인해 '같은 개념의 기간'(예: 반기
    누적)이라도 당기·전기 실제 일수가 1~2일 차이날 수 있으므로, 정확한 일수가 아닌 근사
    범위로 그룹핑해야 당기/전기가 올바르게 짝지어진다."""
    if days <= 15:
        return "1개월"
    if days <= 100:
        return "3개월"
    if days <= 195:
        return "누적(6개월)"
    if days <= 285:
        return "누적(9개월)"
    return "누적(12개월)"


def get_leaf_values(facts: dict, contexts: dict, leaves: list[dict], target_member: str) -> list[dict]:
    """leaf 요소별 당기/전기 값 추출. 통계표 하나에도 시점(instant, 예: 기초/기말현금)과
    기간(duration, 예: 흐름 항목)이 섞여 있을 수 있으므로 문서 전체를 기준으로 요소별로
    실제 존재하는 컨텍스트 종류를 그대로 사용한다(통계표 단위로 미리 고정하지 않음)."""
    rows = []
    for leaf in leaves:
        name = leaf["name"]
        entries = facts.get(name, [])
        instant_candidates: list[tuple[str, float]] = []
        duration_candidates: dict[str, list[tuple[str, float]]] = {}

        for ctx_id, value in entries:
            if value is None:
                continue
            ctx = contexts.get(ctx_id)
            if not ctx:
                continue
            dims = ctx["dims"]
            if len(dims) != 1:
                continue  # 축이 여러개면 주석 세부분류 - 본문 재무제표 숫자가 아님
            member = next(iter(dims.values()))
            if member != target_member:
                continue
            try:
                val = float(value)
            except ValueError:
                continue
            if ctx["instant"]:
                instant_candidates.append((ctx["instant"], val))
            elif ctx["start"] and ctx["end"]:
                bucket = _duration_bucket(_duration_days(ctx["start"], ctx["end"]))
                duration_candidates.setdefault(bucket, []).append((ctx["end"], val))

        if len(instant_candidates) >= 2:
            instant_candidates.sort(key=lambda x: x[0], reverse=True)
            (_cur_date, cur_val), (_pri_date, pri_val) = instant_candidates[0], instant_candidates[1]
            rows.append(_build_row(leaf, None, cur_val, pri_val))
        for seg_label, items in sorted(duration_candidates.items()):
            items.sort(key=lambda x: x[0], reverse=True)
            if len(items) < 2:
                continue
            (_cur_end, cur_val), (_pri_end, pri_val) = items[0], items[1]
            rows.append(_build_row(leaf, seg_label, cur_val, pri_val))

    return rows


def _build_row(leaf: dict, segment: str | None, current: float, prior: float) -> dict:
    diff = current - prior
    pct = (diff / prior) if prior not in (0, None) else None
    return {
        "label": leaf["name"], "level": leaf["level"], "segment": segment,
        "current": current, "prior": prior, "diff": diff, "pct": pct,
    }


EQUITY_COMPONENT_AXIS = "ComponentsOfEquityAxis"


def get_equity_leaf_values(facts: dict, contexts: dict, leaves: list[dict], target_member: str) -> list[dict]:
    """자본변동표 전용 값 추출. 다른 3대 재무제표와 달리 자본변동표는 요소(leaf, 예: 당기순이익,
    배당금, 기초자본)마다 '연결/별도' 축 + '자본구성요소'(EQUITY_COMPONENT_AXIS, 예: 자본금/
    자본잉여금/이익잉여금) 축 2개가 함께 붙어야 실제 표의 한 셀(행×열) 값이 나오는 2차원
    구조다. 따라서 leaf별로 등장하는 자본구성요소 멤버 조합별로 별도 행을 만든다."""
    rows = []
    for leaf in leaves:
        name = leaf["name"]
        entries = facts.get(name, [])
        # {component_member: {"instant": [...], "duration": {bucket: [...]}}}
        by_component: dict[str, dict] = {}

        for ctx_id, value in entries:
            if value is None:
                continue
            ctx = contexts.get(ctx_id)
            if not ctx:
                continue
            dims = ctx["dims"]
            if dims.get("ConsolidatedAndSeparateFinancialStatementsAxis") != target_member:
                continue
            component = dims.get(EQUITY_COMPONENT_AXIS)
            if component is None or len(dims) != 2:
                continue  # 자본구성요소 축이 없거나(총계성) 다른 축이 더 있으면(주석) 제외
            try:
                val = float(value)
            except ValueError:
                continue
            bucket = by_component.setdefault(component, {"instant": [], "duration": {}})
            if ctx["instant"]:
                bucket["instant"].append((ctx["instant"], val))
            elif ctx["start"] and ctx["end"]:
                seg = _duration_bucket(_duration_days(ctx["start"], ctx["end"]))
                bucket["duration"].setdefault(seg, []).append((ctx["end"], val))

        for component, data in by_component.items():
            instant_candidates = data["instant"]
            if len(instant_candidates) >= 2:
                instant_candidates.sort(key=lambda x: x[0], reverse=True)
                (_c, cur_val), (_p, pri_val) = instant_candidates[0], instant_candidates[1]
                row = _build_row(leaf, None, cur_val, pri_val)
                row["component"] = component
                rows.append(row)
            for seg_label, items in sorted(data["duration"].items()):
                items.sort(key=lambda x: x[0], reverse=True)
                if len(items) < 2:
                    continue
                (_c, cur_val), (_p, pri_val) = items[0], items[1]
                row = _build_row(leaf, seg_label, cur_val, pri_val)
                row["component"] = component
                rows.append(row)

    return rows
