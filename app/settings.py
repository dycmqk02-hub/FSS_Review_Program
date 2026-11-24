"""프로그램 설정(참조자료 폴더 경로 등) 저장/로드."""
import json
import os
import sys

APP_NAME = "FSS_ReviewProgram"


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CONFIG_PATH = os.path.join(_base_dir(), "config.json")


def cache_dir() -> str:
    """참조자료 폴더의 PDF 텍스트 추출 결과를 저장해 두는 디스크 캐시 디렉토리
    (프로그램 재실행 시 원본 PDF가 그대로면 재파싱 없이 즉시 재사용)."""
    path = os.path.join(_base_dir(), ".ref_cache")
    os.makedirs(path, exist_ok=True)
    return path

# 사용자가 준칙/기준서 PDF를 미리 받아둔 폴더. 각 폴더는 하위폴더까지 재귀 검색됨.
# - kgaap_folder: 일반기업회계기준 PDF 전용 폴더 (KIFRS 폴더와 분리되어 있어야 교차 매칭 방지됨)
# - kifrs_folder: 현재 "시행중"인 K-IFRS 기준서 폴더
# - kifrs_early_folder: 필수는 아니지만 "조기적용 가능"한 K-IFRS 기준서 폴더
_DEFAULT_STANDARDS_ROOT = r"C:\Users\seo\1st Review프로그램\기준서"

DEFAULTS = {
    "kgaap_folder": _DEFAULT_STANDARDS_ROOT + r"\일반기업회계기준",
    "kifrs_folder": _DEFAULT_STANDARDS_ROOT + r"\KIFRS",
    "kifrs_early_folder": _DEFAULT_STANDARDS_ROOT + r"\KIFRS_조기적용가능",
    "last_report_type": "분반기",
    "last_fs_type": "연결",
    "last_accounting_standard": "KIFRS",
    "export_folder": "",
}


def load_settings() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULTS)
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)


def save_settings(settings: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
