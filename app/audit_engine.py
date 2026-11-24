"""감사보고서 리뷰 엔진.

분·반기 엔진(semiannual_engine.py)과 동일한 인터페이스/결과 포맷을 사용하므로 기존 UI 탭이 그대로
렌더링된다. 감사보고서 전용으로 아래를 교체·추가했다.
  - 체크리스트: 회계감사기준서 700/701/570/706 + 외감법 (rules/audit_checklist.py)
  - 감사의견: 감사보고서 표준문구 기반 의견유형 + KAM/계속기업/내부회계 (rules/audit_opinion.py)
  - 풋팅: 좌표 기반 정밀 풋팅 엔진 (rules/audit_footing.py) 결과를 합계검증/FS간 교차검증/주석대사/
    숫자 스크리닝/증감분석 탭의 'PDF' 출처로 공급. 기존 휴리스틱 결과는 'legacy' 키에 보존.
  - 연결 vs 별도: 기존 키워드 비교 + 재무제표 본문 계정별 금액 비교
"""
from . import pdf_utils
from .rules.audit_checklist import evaluate_audit_checklist
from .rules.audit_opinion import detect_audit_opinion, build_overview
from .rules.comparative_check import check_comparative
from .rules.accounting_change import detect_accounting_changes
from .rules.sum_check import check_table_sums
from .rules.reference_lookup import search_sources, folder_status
from .rules.consol_vs_sep import compare_consol_separate
from .rules.variance_analysis import apply_flags, detect_unit
from .rules import audit_footing as af
from .rules import xbrl_pdf_tieout as xt
from . import semiannual_engine as se

FS_TYPE_CHOICES = ["연결", "별도", "개별", "연결 vs 별도"]
ACCOUNTING_STANDARD_CHOICES = ["KIFRS", "일반기업회계기준"]


def _footing(path: str, label: str):
    try:
        return af.Report(path, label).run()
    except Exception as e:  # noqa: BLE001
        rep = af.Report([], label)
        rep.errors = [f"풋팅 엔진 실행 실패: {type(e).__name__}: {e}"]
        rep.sections, rep.special, rep.page_map = {}, [], {}
        rep.sce = {'cols': [], 'names': [], 'rows': []}
        return rep


def _prior_review(prior_path: str | None, rep, label: str) -> dict | None:
    """전기 감사보고서 PDF(선택): 개요 비교 + 당기보고서 전기열 ↔ 전기보고서 당기열 대사."""
    if not prior_path:
        return None
    import os
    try:
        pdoc = pdf_utils.load_pdf(prior_path, extract_tables=False)
        prep = _footing(prior_path, f"{label}(전기)")
        return {"file": os.path.basename(prior_path), "overview": build_overview(pdoc.full_text, prep),
                "fs_compare": af.compare_prior_fs(rep, prep), "footing": prep}
    except Exception as e:  # noqa: BLE001
        return {"file": os.path.basename(prior_path), "overview": None, "fs_compare": [], "error": str(e)}


def _single_doc_review(path: str, label: str, pm_threshold, xbrl_source, xbrl_kind,
                        report=None, prior_path: str | None = None) -> dict:
    doc = pdf_utils.load_pdf(path)
    if report:
        report(f"{label} 정밀 풋팅(재무제표·주석 표 좌표 분석) 중...", None)
    rep = _footing(path, label)

    calc = {"xbrl": None, "pdf": af.to_calc_check(rep), "excel": None}
    cross = {"xbrl": None, "pdf": af.to_cross_check_fs(rep), "excel": None}
    note = {"xbrl": None, "pdf": af.to_note_check(rep)}
    if xbrl_source and xbrl_kind:  # XBRL 정밀검증은 기존 모듈 그대로 병행
        calc["xbrl"] = se._calc_check(doc, xbrl_source, xbrl_kind, None, None).get("xbrl")
        cross["xbrl"] = se._cross_check_fs(doc, xbrl_source, xbrl_kind, None, None).get("xbrl")
        note["xbrl"] = se._note_check(doc, xbrl_source, xbrl_kind).get("xbrl")
    tie = None
    if xbrl_source and xbrl_kind:   # PDF 재무제표 ↔ XBRL 계정별 대사 (+ 전전기말 연속성)
        try:
            tie = xt.tieout(rep, xbrl_source, xbrl_kind)
        except Exception as e:  # noqa: BLE001
            tie = {"rows": [], "continuity": [], "error": f"{type(e).__name__}: {e}"}

    variance = af.to_variance_tables(rep)
    variance_source = "PDF 재무제표 본문(정밀 풋팅 엔진)"
    if xbrl_source and xbrl_kind:
        v2, src = se._variance_tables(doc, pm_threshold, xbrl_source, xbrl_kind)
        if src.startswith("XBRL"):
            variance, variance_source = v2, src

    try:
        legacy_sum = check_table_sums(doc.tables)
    except Exception:  # noqa: BLE001
        legacy_sum = []

    return {
        "overview": build_overview(doc.full_text, rep),
        "prior": _prior_review(prior_path, rep, label),
        "checklist": evaluate_audit_checklist(doc.full_text),
        "opinion": detect_audit_opinion(doc.full_text),
        "comparative": check_comparative(doc.full_text),
        "accounting_changes": detect_accounting_changes(doc.pages),
        "sum_check": af.to_sum_check(rep),
        "cross_check": [],
        "variance_tables": apply_flags(variance, pm_threshold),
        "variance_source": variance_source,
        "calc_check": calc,
        "cross_check_fs": cross,
        "note_check": note,
        "detected_unit": detect_unit(doc.full_text),
        "pm_threshold": pm_threshold,
        "page_count": doc.page_count(),
        "footing": rep,
        "footing_summary": af.summary_counts(rep) + ([xt.summary(tie)] if tie and not tie.get("error") else []),
        "xbrl_tieout": tie,
        "footing_errors": getattr(rep, "errors", []),
        "legacy": {"sum_check": legacy_sum},
    }


def run_review(fs_type: str, accounting_standard: str, files: dict, settings: dict,
               pm_consol: float | None = None, pm_separate: float | None = None,
               xbrl_source: str | None = None, progress_cb=None) -> dict:
    def report(msg, pct):
        if progress_cb and pct is not None:
            progress_cb(msg, pct)

    ref_sources = se._ref_sources(accounting_standard, settings)
    result = {
        "report_type": "감사",
        "fs_type": fs_type,
        "accounting_standard": accounting_standard,
        "ref_sources": [{"label": l, "status": folder_status(f)} for l, f in ref_sources],
        "not_supported": False,
        "sections": {},
    }

    if fs_type == "연결 vs 별도":
        report("연결 감사보고서 분석/풋팅 중...", 5)
        result["sections"]["consol"] = _single_doc_review(files["consol"], "연결", pm_consol, xbrl_source,
                                                           "consolidated", prior_path=files.get("prior_consol"))
        report("별도 감사보고서 분석/풋팅 중...", 40)
        result["sections"]["separate"] = _single_doc_review(files["separate"], "별도", pm_separate,
                                                             xbrl_source, "separate", prior_path=files.get("prior_separate"))
        report("연결 vs 별도 비교 중...", 75)
        cdoc = pdf_utils.load_pdf(files["consol"], extract_tables=False)
        sdoc = pdf_utils.load_pdf(files["separate"], extract_tables=False)
        cvs = compare_consol_separate(cdoc.pages, sdoc.pages)
        cvs["amount_comparison"] = af.compare_consol_separate_amounts(result["sections"]["consol"]["footing"],
                                                                      result["sections"]["separate"]["footing"])
        result["sections"]["consol_vs_sep"] = cvs
        docs = [result["sections"]["consol"], result["sections"]["separate"]]
    else:
        report(f"{fs_type} 감사보고서 분석/풋팅 중...", 10)
        pm = se._resolve_pm(fs_type, pm_consol, pm_separate)
        result["sections"]["single"] = _single_doc_review(files["main"], fs_type, pm, xbrl_source,
                                                          se.FS_TYPE_TO_XBRL_KIND.get(fs_type),
                                                          prior_path=files.get("prior_main"))
        docs = [result["sections"]["single"]]

    kw_set = {f["keyword"] for d in docs for f in d["accounting_changes"]}
    if kw_set and any(f for _l, f in ref_sources):
        report("참조자료 검색 중...", 85)
        result["sections"]["reference_matches"] = search_sources(
            ref_sources, sorted(kw_set)[:15], progress_cb=lambda fr: report("참조자료 인덱싱 중...", 85 + fr * 14))
    else:
        result["sections"]["reference_matches"] = {}
    report("완료", 100)
    return result
