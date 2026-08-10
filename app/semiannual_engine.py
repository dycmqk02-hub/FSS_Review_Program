"""분·반기재무제표 검토보고서 리뷰 엔진.
재무제표구분(연결/별도/개별/연결 vs 별도) x 적용회계처리기준(KIFRS/일반기업회계기준) 조합 파이프라인."""
from . import pdf_utils
from .rules.checklist_46 import evaluate_checklist
from .rules.opinion_detect import detect_opinion
from .rules.comparative_check import check_comparative
from .rules.accounting_change import detect_accounting_changes
from .rules.sum_check import check_table_sums, cross_check_labels
from .rules.reference_lookup import search_sources, folder_status
from .rules.consol_vs_sep import compare_consol_separate
from .rules.custom_checklist import load_custom_checklist
from .rules.variance_analysis import build_variance_tables, apply_flags, detect_unit
from .rules.xbrl_variance import build_variance_tables_from_xbrl
from .rules.xbrl_calc_check import check_xbrl_calculations
from .rules.xbrl_cross_check import check_cross_statement_xbrl
from .rules.pdf_hierarchy_check import check_pdf_calculations
from .rules.pdf_cross_check import check_cross_statement_pdf
from .rules.xbrl_note_check import check_note_cross_reference, check_note_calc_hierarchy
from .rules.pdf_note_check import check_note_amount_tracing, check_note_tables_hierarchy

FS_TYPE_CHOICES = ["연결", "별도", "개별", "연결 vs 별도"]
ACCOUNTING_STANDARD_CHOICES = ["KIFRS", "일반기업회계기준"]

# 재무제표구분(옵션2) -> XBRL 연결/별도 축 member 매핑. 개별재무제표는 DART XBRL
# 택소노미상 별도 전용 role만 존재하는 경우가 일반적이라 별도(separate)로 취급한다.
FS_TYPE_TO_XBRL_KIND = {"연결": "consolidated", "별도": "separate", "개별": "separate"}


def _ref_sources(accounting_standard: str, settings: dict) -> list[tuple[str, str]]:
    """옵션3(적용회계처리기준)에 따라 검색할 참조자료 출처 목록.
    KIFRS 선택 시 '시행중'과 '조기적용가능'을 모두 검색하여 리뷰결과에서 색상으로 구분 표시한다."""
    if accounting_standard == "KIFRS":
        return [
            ("시행중 KIFRS", settings.get("kifrs_folder", "")),
            ("조기적용가능 KIFRS", settings.get("kifrs_early_folder", "")),
        ]
    return [("일반기업회계기준(K-GAAP)", settings.get("kgaap_folder", ""))]


def _resolve_pm(fs_type: str, pm_consol: float | None, pm_separate: float | None) -> float | None:
    """옵션4(연결PM)/옵션5(별도PM) 중 재무제표구분에 맞는 PM값 선택.
    개별재무제표는 별도의 PM 입력칸이 없으므로 연결PM(옵션4) 값을 재사용한다."""
    if fs_type in ("연결", "개별"):
        return pm_consol
    if fs_type == "별도":
        return pm_separate
    return None


def _variance_tables(doc: pdf_utils.PdfDocument, pm_threshold: float | None,
                      xbrl_source: str | None, xbrl_kind: str | None) -> tuple[dict, str]:
    """XBRL이 제공되면 정밀 추출을 우선 사용하고, 실패하거나 없으면 PDF 표 휴리스틱으로 폴백."""
    if xbrl_source and xbrl_kind:
        tables, err = build_variance_tables_from_xbrl(xbrl_source, xbrl_kind)
        if err is None:
            return apply_flags(tables, pm_threshold), "XBRL(정밀 매칭)"
        source_label = f"PDF 표 휴리스틱 (XBRL 사용 실패: {err})"
        return apply_flags(build_variance_tables(doc), pm_threshold), source_label
    return apply_flags(build_variance_tables(doc), pm_threshold), "PDF 표 휴리스틱"


def _calc_check(doc: pdf_utils.PdfDocument, xbrl_source: str | None, xbrl_kind: str | None) -> dict:
    """재무제표 계층별 합계검증(leaf 합계 -> 소계 -> 최상위 총계까지 전 레벨). PDF 기반은
    항상 수행하고, XBRL이 추가로 제공되면 Calculation Linkbase 기반 정밀 검증도 함께 수행한다."""
    result: dict = {"xbrl": None, "pdf": None}
    if xbrl_source and xbrl_kind:
        xbrl_result, err = check_xbrl_calculations(xbrl_source, xbrl_kind)
        if not err:
            result["xbrl"] = xbrl_result
    try:
        result["pdf"] = check_pdf_calculations(doc)
    except Exception:  # noqa: BLE001
        result["pdf"] = None
    return result


def _cross_check_fs(doc: pdf_utils.PdfDocument, xbrl_source: str | None, xbrl_kind: str | None) -> dict:
    """FS간 교차검증(동일 계정과목이 여러 재무제표에 등장할 때 서로 일치하는지 대사).
    PDF 기반은 항상 수행하고, XBRL이 추가로 제공되면 함께 수행한다."""
    result: dict = {"xbrl": None, "pdf": None}
    if xbrl_source and xbrl_kind:
        xbrl_findings, err = check_cross_statement_xbrl(xbrl_source, xbrl_kind)
        if not err:
            result["xbrl"] = xbrl_findings
    try:
        result["pdf"] = check_cross_statement_pdf(doc)
    except Exception:  # noqa: BLE001
        result["pdf"] = None
    return result


def _note_check(doc: pdf_utils.PdfDocument, xbrl_source: str | None, xbrl_kind: str | None) -> dict:
    """주석(note) 대사: (1) 재무제표 계정과 주석에 공시된 금액이 일치하는지 (2) 주석 내부에도
    합계검증 대상(소계/총계 구조)이 있으면 함께 검증. PDF는 항상 수행하고, XBRL이 추가로
    제공되면 Calculation Linkbase/요소 재사용 기반 정밀 검증도 함께 수행한다."""
    result: dict = {
        "xbrl": None,
        "pdf": {"amount_tracing": {"confirmed": 0, "unmatched": []}, "table_hierarchy": []},
    }
    if xbrl_source and xbrl_kind:
        cross_ref, err1 = check_note_cross_reference(xbrl_source, xbrl_kind)
        calc_hier, err2 = check_note_calc_hierarchy(xbrl_source, xbrl_kind)
        if not err1 and not err2:
            result["xbrl"] = {"cross_reference": cross_ref, "calc_hierarchy": calc_hier}
    try:
        result["pdf"] = {
            "amount_tracing": check_note_amount_tracing(doc),
            "table_hierarchy": check_note_tables_hierarchy(doc),
        }
    except Exception:  # noqa: BLE001
        pass
    return result


def _single_doc_review(doc: pdf_utils.PdfDocument, custom_items: list[dict], pm_threshold: float | None,
                        xbrl_source: str | None = None, xbrl_kind: str | None = None) -> dict:
    variance_tables, variance_source = _variance_tables(doc, pm_threshold, xbrl_source, xbrl_kind)
    return {
        "checklist": evaluate_checklist(doc.full_text, custom_items),
        "opinion": detect_opinion(doc.full_text),
        "comparative": check_comparative(doc.full_text),
        "accounting_changes": detect_accounting_changes(doc.pages),
        "sum_check": check_table_sums(doc.tables),
        "cross_check": cross_check_labels(doc.pages),
        "variance_tables": variance_tables,
        "variance_source": variance_source,
        "calc_check": _calc_check(doc, xbrl_source, xbrl_kind),
        "cross_check_fs": _cross_check_fs(doc, xbrl_source, xbrl_kind),
        "note_check": _note_check(doc, xbrl_source, xbrl_kind),
        "detected_unit": detect_unit(doc.full_text),
        "pm_threshold": pm_threshold,
        "page_count": doc.page_count(),
    }


def run_review(fs_type: str, accounting_standard: str, files: dict, settings: dict,
               pm_consol: float | None = None, pm_separate: float | None = None,
               xbrl_source: str | None = None, progress_cb=None) -> dict:
    """files: {'main': path} 또는 (연결 vs 별도) {'consol': path, 'separate': path}
    xbrl_source: XBRL zip 파일 또는 폴더 경로(선택). 제공되면 증감분석 시 PDF 표 휴리스틱 대신
    XBRL 인스턴스 문서에서 정밀 추출한 당기/전기 값을 사용한다(연결·별도 모두 같은 XBRL
    인스턴스 하나에 들어있으므로 업로드는 1회면 충분).
    progress_cb(msg: str, percent: float 0~100)가 주어지면 진행상황을 보고한다."""

    def report(msg, pct):
        if progress_cb:
            progress_cb(msg, pct)

    custom_items = load_custom_checklist(settings.get("custom_checklist_path", ""))
    ref_sources = _ref_sources(accounting_standard, settings)
    ref_sources_status = [{"label": label, "status": folder_status(folder)} for label, folder in ref_sources]
    ref_source_labels = " / ".join(label for label, _ in ref_sources)

    result = {
        "report_type": "분반기",
        "fs_type": fs_type,
        "accounting_standard": accounting_standard,
        "ref_sources": ref_sources_status,
        "not_supported": False,
        "sections": {},
    }

    if fs_type == "연결 vs 별도":
        report("연결재무제표 PDF 분석 중...", 4)
        consol_doc = pdf_utils.load_pdf(files["consol"])
        report("별도재무제표 PDF 분석 중...", 12)
        separate_doc = pdf_utils.load_pdf(files["separate"])

        report("연결 검토보고서 체크리스트/의견/증감분석 스크리닝 중...", 18)
        result["sections"]["consol"] = _single_doc_review(
            consol_doc, custom_items, pm_consol, xbrl_source, "consolidated")
        report("별도 검토보고서 체크리스트/의견/증감분석 스크리닝 중...", 26)
        result["sections"]["separate"] = _single_doc_review(
            separate_doc, custom_items, pm_separate, xbrl_source, "separate")

        report("연결 vs 별도 특수관계자/내부거래 비교 중...", 32)
        result["sections"]["consol_vs_sep"] = compare_consol_separate(consol_doc.pages, separate_doc.pages)

        kw_set = {f["keyword"] for f in result["sections"]["consol"]["accounting_changes"]}
        kw_set |= {f["keyword"] for f in result["sections"]["separate"]["accounting_changes"]}
        if kw_set:
            report(f"{ref_source_labels} 참조자료 인덱싱/검색 준비 중...", 34)

            def ref_progress(frac):
                report(f"{ref_source_labels} 참조자료 인덱싱 중... ({int(frac * 100)}%)", 34 + frac * 63)

            result["sections"]["reference_matches"] = search_sources(
                ref_sources, sorted(kw_set)[:15], progress_cb=ref_progress)
        else:
            report("참조자료 매칭 대상 키워드 없음", 95)
            result["sections"]["reference_matches"] = {}
    else:
        report(f"{fs_type} 검토보고서 PDF 분석 중...", 8)
        doc = pdf_utils.load_pdf(files["main"])
        pm = _resolve_pm(fs_type, pm_consol, pm_separate)
        xbrl_kind = FS_TYPE_TO_XBRL_KIND.get(fs_type)
        report("체크리스트/의견유형/비교표시/회계처리변경/증감분석 스크리닝 중...", 18)
        result["sections"]["single"] = _single_doc_review(doc, custom_items, pm, xbrl_source, xbrl_kind)

        kw_set = {f["keyword"] for f in result["sections"]["single"]["accounting_changes"]}
        if kw_set:
            report(f"{ref_source_labels} 참조자료 인덱싱/검색 준비 중...", 22)

            def ref_progress(frac):
                report(f"{ref_source_labels} 참조자료 인덱싱 중... ({int(frac * 100)}%)", 22 + frac * 73)

            result["sections"]["reference_matches"] = search_sources(
                ref_sources, sorted(kw_set)[:15], progress_cb=ref_progress)
        else:
            report("참조자료 매칭 대상 키워드 없음", 95)
            result["sections"]["reference_matches"] = {}

    report("완료", 100)
    return result
