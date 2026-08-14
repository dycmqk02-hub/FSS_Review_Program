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


def export_full_excel(result: dict, path: str) -> None:
    """리뷰 결과 전체(체크리스트/증감분석/합계검증 등)를 하나의 Excel로 저장."""
    import openpyxl
    from openpyxl.styles import Font

    from .report_render import render_text_report

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "요약"
    ws.column_dimensions["A"].width = 120

    for line in render_text_report(result).splitlines():
        ws.append([line])
        stripped = line.strip()
        if stripped.startswith("=") or (stripped.startswith("[") and stripped.endswith("]")):
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True)

    if not result.get("not_supported"):
        _add_variance_sheets(wb, result)

    excel_data = result.get("excel_verify_data")
    if excel_data:
        from .rules import excel_review_engine as xlengine
        xlengine.add_verification_sheets(
            wb, excel_data["sum_results"], excel_data["recon_results"], excel_data["compare_results"],
            source_wb=excel_data["wb"], source_path=excel_data["path"])
        wb.active = 0

    for label, text in (result.get("ai_reviews") or {}).items():
        ai_ws = wb.create_sheet(f"AI심층분석_{label}"[:31])
        ai_ws.column_dimensions["A"].width = 120
        for line in text.splitlines():
            ai_ws.append([line])

    wb.save(path)
