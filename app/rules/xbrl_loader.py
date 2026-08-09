"""XBRL 소스(zip 파일 또는 폴더)에서 구성요소 파일 7종을 찾아준다."""
import os
import tempfile
import zipfile

REQUIRED_KEYS = ("instance", "schema", "presentation", "calculation", "label_ko")


def extract_zip(zip_path: str) -> str:
    """zip을 임시 폴더에 압축 해제하고 그 폴더 경로를 반환."""
    extract_dir = tempfile.mkdtemp(prefix="xbrl_")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
    return extract_dir


def find_xbrl_files(folder: str) -> dict:
    """폴더(하위폴더 포함)에서 XBRL 구성요소 파일을 찾는다.
    returns {"instance":, "schema":, "presentation":, "calculation":, "label_ko":, "label_en":, "definition":}"""
    found: dict[str, str] = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            lower = name.lower()
            path = os.path.join(root, name)
            if lower.endswith("_pre.xml"):
                found["presentation"] = path
            elif lower.endswith("_cal.xml"):
                found["calculation"] = path
            elif lower.endswith("_def.xml"):
                found["definition"] = path
            elif lower.endswith("_lab-ko.xml"):
                found["label_ko"] = path
            elif lower.endswith("_lab-en.xml"):
                found["label_en"] = path
            elif lower.endswith(".xsd"):
                found["schema"] = path
            elif lower.endswith(".xbrl"):
                found["instance"] = path
    return found


def resolve_xbrl_source(path: str) -> dict:
    """path가 .zip 파일이면 압축 해제 후, 폴더면 그대로 XBRL 파일 목록을 찾아 반환."""
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        folder = extract_zip(path)
    else:
        folder = path
    return find_xbrl_files(folder)


def validate_xbrl_files(files: dict) -> str | None:
    """필수 파일이 빠졌으면 에러 메시지를, 문제 없으면 None을 반환."""
    missing = [k for k in REQUIRED_KEYS if k not in files]
    if missing:
        return f"필수 XBRL 파일을 찾지 못했습니다: {', '.join(missing)} (instance=.xbrl, schema=.xsd, presentation=_pre.xml, calculation=_cal.xml, label_ko=_lab-ko.xml)"
    return None
