"""보고서 종류(분반기/감사) 별 리뷰 엔진 디스패처.

옵션1: 보고서 종류 - 분반기 / 감사 (감사는 추후 지원 예정, 현재는 스텁)
옵션2: 재무제표 구분 - 연결 / 별도 / 개별 / 연결 vs 별도
옵션3: 적용 회계처리기준 - KIFRS / 일반기업회계기준
"""
from . import semiannual_engine, audit_engine

REPORT_TYPE_CHOICES = ["분반기", "감사"]
FS_TYPE_CHOICES = semiannual_engine.FS_TYPE_CHOICES
ACCOUNTING_STANDARD_CHOICES = semiannual_engine.ACCOUNTING_STANDARD_CHOICES

_ENGINES = {
    "분반기": semiannual_engine,
    "감사": audit_engine,
}


def run_review(report_type: str, fs_type: str, accounting_standard: str, files: dict, settings: dict,
               pm_consol: float | None = None, pm_separate: float | None = None,
               xbrl_source: str | None = None, progress_cb=None) -> dict:
    """progress_cb(msg: str, percent: float 0~100)."""
    engine = _ENGINES.get(report_type)
    if engine is None:
        raise ValueError(f"지원하지 않는 보고서 종류입니다: {report_type}")
    return engine.run_review(fs_type, accounting_standard, files, settings,
                              pm_consol=pm_consol, pm_separate=pm_separate,
                              xbrl_source=xbrl_source, progress_cb=progress_cb)
