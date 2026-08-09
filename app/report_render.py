"""리뷰 결과(dict) -> 사람이 읽을 수 있는 텍스트/문서 렌더링."""

DISCLAIMER = "본 결과는 규칙/키워드 기반 1차 스크리닝(사전리뷰 보조도구)이며, 최종 판단·검토의견 형성은 검토자가 직접 수행하여야 합니다."


def _render_single(title: str, data: dict) -> str:
    lines = [title, f"  총 페이지 수: {data['page_count']}"]

    lines.append("  [필수 기재사항 체크리스트 - 문단46 등]")
    for item in data["checklist"]:
        if item["found"]:
            mark = "OK"
        elif item.get("required"):
            mark = "!! 필수 미확인"
        else:
            mark = "미확인(해당시)"
        matched = f" (매칭: '{item['matched']}')" if item["found"] else ""
        lines.append(f"   - [{mark}] {item.get('para', '')} {item.get('category', '')} : {item['title']}{matched}")

    lines.append("  [검토의견 유형 판단]")
    op = data["opinion"]
    lines.append(f"   - 판단된 의견유형: {op['opinion_type']}")
    for c in op["checks"]:
        mark = "OK" if c["ok"] else ("확인필요" if c["ok"] is None else "!! 미확인")
        lines.append(f"   - [{mark}] {c['item']}")

    lines.append("  [비교표시 재무정보 체크 - 문단47~48]")
    for c in data["comparative"]:
        mark = "OK" if c["ok"] else "미확인(해당시)"
        lines.append(f"   - [{mark}] {c['item']}")

    lines.append("  [전기말 대비 당반기중 회계처리 변경 관련 키워드 탐지]")
    changes = data["accounting_changes"]
    if not changes:
        lines.append("   - 탐지된 항목 없음")
    else:
        for f in changes[:40]:
            lines.append(f"   - p.{f['page']} [{f['keyword']}] ...{f['snippet']}...")
        if len(changes) > 40:
            lines.append(f"   - 외 {len(changes) - 40}건 더 있음 (GUI 화면에서 전체 확인 가능)")

    lines.append("  [표 소계·합계 검산 - 불일치 후보 (휴리스틱, 오탐 가능)]")
    sums = data["sum_check"]
    if not sums:
        lines.append("   - 불일치 후보 없음(또는 표 구조상 자동 검산 불가 - 육안 확인 권장)")
    else:
        for f in sums[:30]:
            lines.append(
                f"   - p.{f['page']} '{f['row_label']}' {f['column']}번째 숫자열: "
                f"기재값 {f['stated']:,.0f} vs 항목합계 {f['computed']:,.0f} "
                f"(차이 {f['diff']:,.0f}, 합산항목수 {f['n_items']})"
            )

    lines.append("  [동일 라벨 금액 교차대사 후보 - 상위 항목만, 휴리스틱]")
    cross = data["cross_check"]
    if not cross:
        lines.append("   - 탐지된 항목 없음")
    else:
        for f in cross[:20]:
            occ = ", ".join(f"{v:,.0f}(p.{p})" for v, p in f["occurrences"][:6])
            lines.append(f"   - '{f['label']}': {occ}")

    lines.append(_render_variance(data.get("variance_tables", {}), data.get("detected_unit"),
                                   data.get("pm_threshold")))

    return "\n".join(lines)


def _render_variance(variance_tables: dict, unit: str | None, pm_threshold: float | None) -> str:
    lines = ["  [재무제표 증감분석 - 당기 vs 전기 (휴리스틱)]"]
    if unit:
        lines.append(f"   - 감지된 단위: {unit}")
    lines.append(f"   - 금액차이 기준(PM): {pm_threshold:,.0f}" if pm_threshold else "   - 금액차이 기준(PM) 미입력 - 금액차이 음영 미적용")
    for stmt in ["재무상태표", "손익계산서", "자본변동표", "현금흐름표"]:
        data = variance_tables.get(stmt, {})
        lines.append(f"   [{stmt}]")
        note = data.get("note")
        if note:
            lines.append(f"     - {note}")
        rows = data.get("rows", [])
        if not rows:
            if not note:
                lines.append("     - 데이터 없음")
            continue
        for r in rows[:60]:
            flags = []
            if r.get("amount_flag"):
                flags.append("금액차이기준초과")
            if r.get("pct_flag"):
                flags.append("증감률5%이상")
            flag_txt = f" [{', '.join(flags)}]" if flags else ""
            seg = f"({r['segment']}) " if r.get("segment") else ""
            pct_txt = f"{r['pct'] * 100:.1f}%" if r["pct"] is not None else "N/A"
            lines.append(f"     - {seg}{r['label']}: 당기 {r['current']:,.0f} / 전기 {r['prior']:,.0f} "
                         f"/ 차이 {r['diff']:,.0f} / {pct_txt}{flag_txt}")
        if len(rows) > 60:
            lines.append(f"     - 외 {len(rows) - 60}건 (GUI 화면에서 전체 확인 가능)")
    return "\n".join(lines)


def _render_consol_vs_sep(data: dict) -> str:
    lines = ["[연결 vs 별도 비교 스크리닝 - 실무 참고, 준칙 명문조항 아님]", "  [핵심 키워드 존재 여부 비교]"]
    for c in data["keyword_comparison"]:
        lines.append(f"   - {c['keyword']}: 연결({'O' if c['in_consol'] else 'X'}) / 별도({'O' if c['in_separate'] else 'X'})")
    lines.append("  [실무 참고 체크리스트]")
    for item in data["practice_checklist"]:
        lines.append(f"   - {item['item']}")
        lines.append(f"     -> {item['note']}")
    return "\n".join(lines)


def _render_reference(ref_matches: dict, ref_sources: list) -> str:
    lines = ["[참조자료 자동 매칭 결과]"]
    for src in ref_sources or []:
        lines.append(f"  - 출처 [{src['label']}]: {src['status']}")
    hits_found = any(hits for hits in ref_matches.values())
    if not hits_found:
        lines.append("  - 탐지된 회계처리 변경 키워드가 없거나 참조폴더가 설정되지 않아 매칭 결과가 없습니다.")
        return "\n".join(lines)
    for kw, hits in ref_matches.items():
        if not hits:
            continue
        lines.append(f"  - 키워드 '{kw}':")
        for h in hits:
            lines.append(f"     · [{h.get('source_label', '참조자료')}] {h['file']} p.{h['page']}: ...{h['snippet']}...")
    return "\n".join(lines)


def render_text_report(result: dict) -> str:
    lines = []
    lines.append("=" * 78)
    lines.append("보고서 Review프로그램 - 사전리뷰 결과")
    lines.append(f"보고서종류: {result['report_type']}    재무제표구분: {result['fs_type']}    "
                 f"적용기준: {result['accounting_standard']}")
    for src in result.get("ref_sources", []):
        lines.append(f"참조자료 [{src['label']}]: {src['status']}")
    lines.append(DISCLAIMER)
    lines.append("=" * 78)

    if result.get("not_supported"):
        lines.append("")
        lines.append(result.get("not_supported_note", ""))
        for key, n in (result.get("page_counts") or {}).items():
            lines.append(f"  - {key}: {n if n is not None else '읽기 실패'} 페이지")
        return "\n".join(lines)

    sections = result["sections"]
    if "single" in sections:
        lines.append("")
        lines.append(_render_single(f"[{result['fs_type']} {result['report_type']}보고서]", sections["single"]))
        lines.append("")
        lines.append(_render_reference(sections.get("reference_matches", {}), result.get("ref_sources", [])))
    else:
        lines.append("")
        lines.append(_render_single("[연결재무제표 검토보고서]", sections["consol"]))
        lines.append("")
        lines.append(_render_single("[별도재무제표 검토보고서]", sections["separate"]))
        lines.append("")
        lines.append(_render_consol_vs_sep(sections["consol_vs_sep"]))
        lines.append("")
        lines.append(_render_reference(sections.get("reference_matches", {}), result.get("ref_sources", [])))

    return "\n".join(lines)


def export_txt(result: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_text_report(result))


def export_docx(result: dict, path: str) -> None:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.add_heading("보고서 Review프로그램 - 사전리뷰 결과", level=1)
    meta = doc.add_paragraph()
    meta.add_run(f"보고서종류: {result['report_type']}    재무제표구분: {result['fs_type']}    "
                 f"적용기준: {result['accounting_standard']}\n").bold = True
    for src in result.get("ref_sources", []):
        meta.add_run(f"참조자료 [{src['label']}]: {src['status']}\n")
    disclaimer_p = doc.add_paragraph()
    disclaimer_run = disclaimer_p.add_run(DISCLAIMER)
    disclaimer_run.italic = True
    disclaimer_run.font.size = Pt(9)

    text = render_text_report(result)
    started = False
    for line in text.splitlines():
        stripped = line.strip()
        if not started:
            # 상단 메타 정보 블록은 위에서 이미 작성했으므로 첫 구분선까지 건너뜀
            if stripped.startswith("=" * 5):
                started = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            doc.add_heading(stripped.strip("[]"), level=2)
        elif not stripped:
            continue
        else:
            doc.add_paragraph(line)

    doc.save(path)
