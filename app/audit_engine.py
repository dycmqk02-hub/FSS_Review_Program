"""감사보고서 리뷰 엔진 - 추후 구현 예정 스텁.

현재는 회계감사기준(240/315/330/700 등) 기반 감사보고서 체크리스트가 구현되어 있지 않습니다.
분·반기 검토보고서 엔진(semiannual_engine.py)과 동일한 인터페이스(run_review(fs_type,
accounting_standard, files, settings, progress_cb))로 맞춰 두었으므로, 추후 감사보고서
전용 rules 모듈(예: rules/audit_checklist.py, rules/audit_opinion.py 등)을 추가하고
이 파일에서 semiannual_engine._single_doc_review()에 준하는 로직을 구현하면 됩니다.
"""
from . import pdf_utils

FS_TYPE_CHOICES = ["연결", "별도", "개별", "연결 vs 별도"]
ACCOUNTING_STANDARD_CHOICES = ["KIFRS", "일반기업회계기준"]

NOT_SUPPORTED_NOTE = (
    "감사보고서 리뷰 기능은 아직 구현되지 않았습니다.\n"
    "현재는 「분·반기재무제표 검토준칙」 기반의 반기·분기 검토보고서 리뷰만 지원하며,\n"
    "추후 회계감사기준(240 부정, 315 위험식별, 330 위험대응, 700 감사보고서 등)을 기반으로 한\n"
    "감사보고서 체크리스트로 확장할 예정입니다. 업로드하신 PDF는 페이지 수만 확인했습니다."
)


def run_review(fs_type: str, accounting_standard: str, files: dict, settings: dict,
               pm_consol: float | None = None, pm_separate: float | None = None,
               xbrl_source: str | None = None, excel_path: str | None = None,
               company_name: str | None = None, period: str | None = None, progress_cb=None) -> dict:
    def report(msg, pct):
        if progress_cb:
            progress_cb(msg, pct)

    report("감사보고서 리뷰는 준비 중입니다...", 20)

    page_counts = {}
    for key, path in files.items():
        try:
            doc = pdf_utils.load_pdf(path, extract_tables=False)
            page_counts[key] = doc.page_count()
        except Exception:
            page_counts[key] = None

    result = {
        "report_type": "감사",
        "fs_type": fs_type,
        "accounting_standard": accounting_standard,
        "ref_sources": [{"label": "KIFRS" if accounting_standard == "KIFRS" else "일반기업회계기준(K-GAAP)",
                          "status": "감사보고서 리뷰 미지원"}],
        "not_supported": True,
        "not_supported_note": NOT_SUPPORTED_NOTE,
        "page_counts": page_counts,
        "sections": {},
    }

    report("완료 (감사보고서 리뷰는 추후 지원 예정)", 100)
    return result
