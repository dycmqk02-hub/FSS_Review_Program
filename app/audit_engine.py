"""감사보고서 리뷰 엔진.

분·반기 엔진(semiannual_engine.py)과 동일한 인터페이스/결과 포맷을 사용하므로 기존 UI 탭이 그대로
렌더링된다. 감사보고서 전용으로 아래를 교체·추가했다.
  - 체크리스트: 회계감사기준서 700/701/570/706 + 외감법 (rules/audit_checklist.py)
  - 감사의견: 감사보고서 표준문구 기반 의견유형 + KAM/계속기업/내부회계 (rules/audit_opinion.py)
  - 풋팅: 좌표 기반 정밀 풋팅 엔진 (rules/audit_footing.py) 결과를 합계검증/FS간 교차검증/주석대사/
    숫자 스크리닝/증감분석 탭의 'PDF' 출처로 공급. 기존 휴리스틱 결과는 'legacy' 키에 보존.
  - 연결 vs 별도: 기존 키워드 비교 + 재무제표 본문 계정별 금액 비교
"""
import re

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
from .rules import prior_note_compare as pnc
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


def report_period_key(path: str) -> tuple:
    """보고서의 '나중 정도' 비교 키: (기수, 회계기간 종료일 yyyymmdd, 파일명 속 연도).
    본문 앞쪽에서 '제 42 (당) 기 … 2025년 12월 31일까지' 를 찾고, 없으면 파일명의 연도(2026 / 26년)를 쓴다."""
    import os
    term, end, fyear = 0, 0, 0
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        text = '\n'.join((r.pages[i].extract_text() or '') for i in range(min(12, len(r.pages))))
        m = re.search(r'제\s*(\d+)\s*\(?\s*당\s*\)?\s*기', text) or re.search(r'제\s*(\d+)\s*기', text)
        if m:
            term = int(m.group(1))
        ends = [int(f'{y}{int(mo):02d}{int(d):02d}') for y, mo, d in
                re.findall(r'(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*(?:까지|현재)', text)]
        end = max(ends) if ends else 0
    except Exception:  # noqa: BLE001
        pass
    name = os.path.basename(path)
    ys = [int(y) for y in re.findall(r'(?<!\d)(20\d{2})(?!\d)', name)]
    ys += [2000 + int(y) for y in re.findall(r'(?<!\d)(\d{2})\s*년', name)]
    fyear = max(ys) if ys else 0
    return term, end, fyear


def order_current_prior(cur: str | None, prior: str | None) -> tuple:
    """당기·전기 파일이 바뀌어 들어와도 기수(→ 종료일 → 파일명 연도)가 큰 쪽을 당기로. (당기, 전기, 교체여부)"""
    if not cur or not prior:
        return cur, prior, False
    kc, kp = report_period_key(cur), report_period_key(prior)
    for a, b in zip(kc, kp):   # 둘 다 읽힌 첫 기준으로 비교
        if a and b and a != b:
            return (prior, cur, True) if b > a else (cur, prior, False)
    return cur, prior, False


def _prior_review(prior_path: str | None, rep, label: str) -> dict | None:
    """전기 감사보고서 PDF(선택): 개요 비교 + 당기보고서 전기열 ↔ 전기보고서 당기열 대사."""
    if not prior_path:
        return None
    import os
    try:
        pdoc = pdf_utils.load_pdf(prior_path, extract_tables=False)
        prep = _footing(prior_path, f"{label}(전기)")
        fs_cmp = af.compare_prior_fs(rep, prep)
        note_list = pnc.compare_note_lists(rep, prep)
        note_nums = pnc.compare_note_numbers(rep, prep, note_list)
        return {"file": os.path.basename(prior_path), "overview": build_overview(pdoc.full_text, prep),
                "fs_compare": fs_cmp, "note_list": note_list, "note_compare": note_nums,
                "summary": pnc.summary(note_list, note_nums, fs_cmp), "footing": prep}
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

    # 당기·전기 파일을 반대로 올려도 기수(17기>16기)·종료일·파일명 연도(2026>2025)가 큰 쪽을 당기로 처리
    files = dict(files)
    swapped = []
    for ck, pk, lbl in (("consol", "prior_consol", "연결"), ("separate", "prior_separate", "별도"), ("main", "prior_main", fs_type)):
        c, p, sw = order_current_prior(files.get(ck), files.get(pk))
        if sw:
            files[ck], files[pk] = c, p
            swapped.append(lbl)
    result["order_swapped"] = swapped

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
    # 당기·전기를 바꿔 처리한 경우 개요 시트의 '전기:' 파일명 옆에 표시
    for key, lbl in (("consol", "연결"), ("separate", "별도"), ("single", fs_type)):
        pr = (result["sections"].get(key) or {}).get("prior")
        if pr and lbl in swapped:
            pr["file"] = f"{pr['file']} ※ 업로드 순서와 반대 → 기수·기간이 큰 파일을 당기로 처리"

    kw_set = {f["keyword"] for d in docs for f in d["accounting_changes"]}
    if kw_set and any(f for _l, f in ref_sources):
        report("참조자료 검색 중...", 85)
        result["sections"]["reference_matches"] = search_sources(
            ref_sources, sorted(kw_set)[:15], progress_cb=lambda fr: report("참조자료 인덱싱 중...", 85 + fr * 14))
    else:
        result["sections"]["reference_matches"] = {}
    report("완료", 100)
    return result
