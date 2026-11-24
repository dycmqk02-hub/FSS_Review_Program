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
    lines.append(_render_calc_check(data.get("calc_check", {})))
    lines.append(_render_cross_check_fs(data.get("cross_check_fs", {})))
    lines.append(_render_note_check(data.get("note_check", {})))

    return "\n".join(lines)


_CALC_CHECK_SOURCE_LABELS = {"xbrl": "XBRL(정밀 매칭)", "pdf": "PDF 표(휴리스틱, 오탐 가능)",
                              "excel": "Excel(직접 검토, 가장 신뢰도 높음)"}


def _render_calc_check(calc_check: dict) -> str:
    lines = ["  [재무제표 계층별 합계검증 - leaf 합계 -> 소계 -> 최상위 총계, 전 레벨]"]
    sources = [(k, calc_check.get(k)) for k in ("xbrl", "pdf", "excel") if calc_check.get(k)]
    if not sources:
        lines.append("   - 검증 결과가 없습니다.")
        return "\n".join(lines)
    for src_key, src_data in sources:
        lines.append(f"   [{_CALC_CHECK_SOURCE_LABELS[src_key]}]")
        for stmt in ["재무상태표", "손익계산서", "자본변동표", "현금흐름표"]:
            data = src_data.get(stmt, {})
            lines.append(f"     [{stmt}]")
            note = data.get("note")
            if note:
                lines.append(f"       - {note}")
            mismatches = data.get("mismatches", [])
            if not mismatches:
                if not note:
                    lines.append("       - 불일치 없음")
                continue
            for f in mismatches[:60]:
                seg = f" · {f['segment']}" if f.get("segment") else ""
                period = f"[{f['period']}] " if f.get("period") else ""
                lines.append(
                    f"       - {period}'{f['parent']}'{seg}: 기재값 {f['stated']:,.0f} "
                    f"vs 하위항목합계 {f['computed']:,.0f} (차이 {f['diff']:,.0f}) "
                    f"- 하위항목: {', '.join(f['children'])}"
                )
            if len(mismatches) > 60:
                lines.append(f"       - 외 {len(mismatches) - 60}건 (GUI 화면에서 전체 확인 가능)")
    return "\n".join(lines)


def _render_cross_check_fs(cross_check: dict) -> str:
    lines = ["  [FS간 교차검증 - 동일 계정과목의 재무제표간 대사]"]
    sources = [(k, cross_check.get(k)) for k in ("xbrl", "pdf", "excel") if cross_check.get(k) is not None]
    if not sources:
        lines.append("   - 검증 결과가 없습니다.")
        return "\n".join(lines)
    for src_key, findings in sources:
        lines.append(f"   [{_CALC_CHECK_SOURCE_LABELS[src_key]}]")
        if not findings:
            lines.append("     - 불일치 없음")
            continue
        for f in findings:
            lines.append(f"     - {f['item']}:")
            for v in f["values"]:
                lines.append(f"        · [{v['source']}] {v['label']} = {v['value']:,.0f}")
    return "\n".join(lines)


def _render_note_check(note_check: dict) -> str:
    lines = ["  [주석(Note) 공시 대사]"]
    xbrl = note_check.get("xbrl")
    pdf = note_check.get("pdf") or {}

    if xbrl:
        lines.append("   [XBRL(정밀 매칭)]")
        cr = xbrl.get("cross_reference") or {}
        lines.append(f"     - 확인됨 {cr.get('confirmed', 0)}건 / 주석 미확인 {len(cr.get('unmatched', []))}건")
        for u in cr.get("unmatched", [])[:40]:
            lines.append(f"        · [{u['stmt']}] {u['label']} ({u['element']}) = {u['value']:,.0f}")
        calc_hier = xbrl.get("calc_hierarchy") or []
        lines.append("     [주석 내 계층별 합계검증]")
        if not calc_hier:
            lines.append("       - 불일치 없음")
        else:
            for m in calc_hier[:40]:
                lines.append(f"       - [{m['note']}] '{m['parent']}': 기재값 {m['stated']:,.0f} "
                             f"vs 하위항목합계 {m['computed']:,.0f} (차이 {m['diff']:,.0f})")

    lines.append("   [PDF 표(휴리스틱, 오탐 가능)]")
    at = pdf.get("amount_tracing") or {}
    lines.append(f"     - 확인됨 {at.get('confirmed', 0)}건 / 주석 미확인 {len(at.get('unmatched', []))}건")
    for u in at.get("unmatched", [])[:40]:
        lines.append(f"        · [{u['stmt']}] {u['label']} = {u['value']:,.0f} (참조 주석: {', '.join(u['notes'])})")
    table_hier = pdf.get("table_hierarchy") or []
    lines.append("     [주석 표 내 계층별 합계검증]")
    if not table_hier:
        lines.append("       - 불일치 없음")
    else:
        for m in table_hier[:40]:
            lines.append(f"       - [{m['note']}] '{m['parent']}': 기재값 {m['stated']:,.0f} "
                         f"vs 하위항목합계 {m['computed']:,.0f} (차이 {m['diff']:,.0f})")
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
            flag_txt = " [금액차이기준초과]" if r.get("amount_flag") else ""
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


def _render_footing_summary(title: str, data: dict) -> str:
    out = [title, f"  {'검증영역':<18}{'건수':>6}{'일치':>6}{'단수차이':>8}{'불일치':>6}{'기타':>6}"]
    for a in data["footing_summary"]:
        out.append(f"  {a['area']:<18}{a['total']:>6}{a['ok']:>6}{a['rounding']:>8}{a['mismatch']:>6}{a['other']:>6}")
    for e in data.get("footing_errors") or []:
        out.append(f"  [오류] {e}")
    rep = data.get("footing")
    if rep is not None:
        from .rules.audit_footing import exceptions
        ex = exceptions(rep)
        if ex:
            out.append(f"  예외 {len(ex)}건 (상위 40건, 전체는 Excel '풋팅예외' 시트):")
            for e in ex[:40]:
                amt = f" {e[5]:,.0f} vs {e[6]:,.0f}" if isinstance(e[5], (int, float)) and isinstance(e[6], (int, float)) else ""
                out.append(f"   - [{e[7]}] {e[0]} {e[1]} p.{e[2]} {e[3]} :: {str(e[4])[:70]}{amt}")
    return "\n".join(out)


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
    doc_word = "감사보고서" if result.get("report_type") == "감사" else "검토보고서"
    for key, lbl in (("single", result["fs_type"]), ("consol", "연결"), ("separate", "별도")):
        if key in sections and sections[key].get("footing_summary"):
            lines.append("")
            lines.append(_render_footing_summary(f"[{lbl} {doc_word} 정밀 풋팅 요약]", sections[key]))
    if "single" in sections:
        lines.append("")
        lines.append(_render_single(f"[{result['fs_type']} {result['report_type']}보고서]", sections["single"]))
        lines.append("")
        lines.append(_render_reference(sections.get("reference_matches", {}), result.get("ref_sources", [])))
    else:
        lines.append("")
        lines.append(_render_single(f"[연결재무제표 {doc_word}]", sections["consol"]))
        lines.append("")
        lines.append(_render_single(f"[별도재무제표 {doc_word}]", sections["separate"]))
        lines.append("")
        lines.append(_render_consol_vs_sep(sections["consol_vs_sep"]))
        lines.append("")
        lines.append(_render_reference(sections.get("reference_matches", {}), result.get("ref_sources", [])))

    return "\n".join(lines)
