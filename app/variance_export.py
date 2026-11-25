"""리뷰 결과 전체 및 증감분석표(재무상태표/손익계산서/자본변동표/현금흐름표) Excel 내보내기."""

STATEMENT_ORDER = ["재무상태표", "손익계산서", "자본변동표", "현금흐름표"]


def _write_sheet(wb, sheet_name: str, doc_label: str, stmt: str, data: dict, unit: str | None,
                  pm_threshold: float | None):
    from openpyxl.styles import Alignment, Font, PatternFill

    AMOUNT_FILL = PatternFill(start_color="FFF3B0", end_color="FFF3B0", fill_type="solid")
    HEADER_FILL = PatternFill(start_color="EDE7FB", end_color="EDE7FB", fill_type="solid")

    ws = wb.create_sheet(sheet_name[:31])
    ws.append([f"{doc_label} {stmt} 증감분석 (당기 vs 전기)"])
    ws["A1"].font = Font(bold=True, size=12)
    unit_text = f"단위: {unit}" if unit else "단위: 미확인(원본 PDF 확인 필요)"
    pm_text = f"금액차이 기준(PM): {pm_threshold:,.0f}" if pm_threshold else "금액차이 기준(PM): 미입력(음영 미적용)"
    ws.append([f"{unit_text}    |    {pm_text}"])
    ws.append([])

    headers = ["계정과목", "구분", "당기금액", "전기금액", "금액차이", "증감률"]
    ws.append(headers)
    header_row = ws.max_row
    for cell in ws[header_row]:
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    note = data.get("note")
    if note:
        ws.append([note])
        ws.cell(row=ws.max_row, column=1).font = Font(italic=True, color="8A83A0")

    rows = data.get("rows", [])
    for r in rows:
        pct_val = r["pct"]
        ws.append([
            r["label"], r.get("segment") or "-", r["current"], r["prior"], r["diff"],
            pct_val if pct_val is not None else "N/A",
        ])
        excel_row = ws.max_row
        if r.get("amount_flag"):
            for col in range(1, 7):
                ws.cell(row=excel_row, column=col).fill = AMOUNT_FILL
        for col in (3, 4, 5):
            ws.cell(row=excel_row, column=col).number_format = "#,##0"
        pct_cell = ws.cell(row=excel_row, column=6)
        if isinstance(pct_cell.value, (int, float)):
            pct_cell.number_format = "0.0%"

    widths = {"A": 30, "B": 16, "C": 16, "D": 16, "E": 16, "F": 10}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def _add_variance_sheets(wb, result: dict) -> None:
    sections = result.get("sections", {})
    if "single" in sections:
        docs = [(result.get("fs_type", "단일"), sections["single"])]
    elif "consol" in sections:
        docs = [("연결", sections.get("consol", {})), ("별도", sections.get("separate", {}))]
    else:
        docs = []

    for doc_label, data in docs:
        variance_tables = data.get("variance_tables", {})
        unit = data.get("detected_unit")
        pm = data.get("pm_threshold")
        for stmt in STATEMENT_ORDER:
            stmt_data = variance_tables.get(stmt, {"rows": [], "note": "데이터 없음"})
            sheet_name = f"{doc_label}_{stmt}" if len(docs) > 1 else stmt
            _write_sheet(wb, sheet_name, doc_label, stmt, stmt_data, unit, pm)


def _add_footing_sheets(wb, result: dict) -> None:
    """감사보고서 정밀 풋팅 결과(풋팅요약/풋팅예외/FS풋팅/FS간대사/주석풋팅/FS-주석대사/본문수치대사/
    특수검증/추출표목록) 시트 추가. 연결 vs 별도면 '연결_'/'별도_' 접두어 + 계정별 금액비교 시트."""
    from .rules import audit_footing as af
    sections = result.get("sections", {})
    docs = [(k, lbl) for k, lbl in (("single", result.get("fs_type", "")), ("consol", "연결"), ("separate", "별도"))
            if k in sections and sections[k].get("footing") is not None]
    for key, lbl in docs:
        prefix = f"{lbl}_" if len(docs) > 1 else ""
        af.add_excel_sheets(wb, lbl, sections[key]["footing"], prefix=prefix)
    amt = (sections.get("consol_vs_sep") or {}).get("amount_comparison")
    if amt:
        af.add_consol_sep_sheet(wb, amt)


def export_full_excel(result: dict, path: str) -> None:
    """리뷰 결과 전체(체크리스트/증감분석/합계검증 등)를 하나의 Excel로 저장."""
    import openpyxl
    from openpyxl.styles import Font

    from .report_render import render_text_report

    wb = openpyxl.Workbook()
    ws = wb.active
    if result.get("report_type") == "감사" and not result.get("not_supported"):
        # 감사보고서: 요약 시트는 '개요'(감사의견·KAM·강조사항·내부회계 등 전기 대비 당기)만 남긴다
        _add_audit_overview(wb, result)
        wb.remove(ws)
        _add_footing_sheets(wb, result)
        _add_variance_sheets(wb, result)
        _add_tail_sheets(wb, result)
        if "개요" in wb.sheetnames:
            wb.move_sheet("개요", offset=-wb.sheetnames.index("개요"))
        wb.active = 0
        wb.save(path)
        return
    ws.title = "요약"
    ws.column_dimensions["A"].width = 120

    for line in render_text_report(result).splitlines():
        # '='로 시작하는 구분선이 수식으로 저장되어 #VALUE! 가 나던 문제 수정 - 문자열로 강제
        ws.append([line])
        if line.startswith("="):
            cell = ws.cell(row=ws.max_row, column=1)
            cell.value = line
            cell.data_type = "s"
        stripped = line.strip()
        if stripped.startswith("=") or (stripped.startswith("[") and stripped.endswith("]")):
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True)

    if not result.get("not_supported"):
        _add_footing_sheets(wb, result)
        _add_variance_sheets(wb, result)

    _add_tail_sheets(wb, result)
    wb.save(path)


def _add_audit_overview(wb, result: dict) -> None:
    from .rules import audit_footing as af
    sections = result.get("sections", {})
    docs = []
    for key, lbl in (("single", result.get("fs_type", "")), ("consol", "연결"), ("separate", "별도")):
        d = sections.get(key)
        if not d or not d.get("overview"):
            continue
        prior = d.get("prior") or {}
        docs.append((lbl, d["overview"], prior.get("overview"), prior.get("file")))
        tie = d.get("xbrl_tieout")
        if tie:
            from .rules import xbrl_pdf_tieout as xt
            xt.add_tieout_sheet(wb, f"{lbl}_XBRL대사" if key != "single" else "XBRL대사", tie)
        if prior.get("fs_compare"):
            af.add_prior_sheet(wb, f"{lbl}_전기보고서대사" if key != "single" else "전기보고서대사", prior["fs_compare"])
        if prior.get("note_list") is not None:
            from .rules import prior_note_compare as pnc
            pnc.add_sheets(wb, f"{lbl}_" if key != "single" else "", prior["note_list"], prior.get("note_compare") or [])
    af.add_overview_sheet(wb, docs)


def _add_tail_sheets(wb, result: dict) -> None:
    """(예비) 추가 시트 훅 - Excel 정밀검증/AI 심층리뷰 기능 제거로 현재는 추가 시트 없음."""
    return None
