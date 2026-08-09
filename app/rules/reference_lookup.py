"""K-GAAP/KIFRS 로컬 참조폴더(PDF, 하위폴더 포함) 키워드 검색.

성능을 위해 2단계로 캐싱한다:
1) 세션 내 메모리 캐시 (프로그램 실행 중에는 즉시 재사용)
2) 디스크 캐시(app/.ref_cache/*.pkl) - 프로그램을 껐다 켜도 원본 PDF가 바뀌지
   않았다면(mtime 서명 일치) 재파싱 없이 그대로 재사용한다. 최초 1회만 전체 PDF를
   파싱하고, 이후에는 디스크 캐시에서 즉시 로드된다(실측 몇 초 이내).

성능 참고: 초기 구현은 파싱을 스레드풀로 병렬화했으나, pypdf의 텍스트 추출은 대부분
순수 파이썬 연산(GIL 점유)이라 스레드로는 실질적 병렬 이득이 거의 없고 오히려 스레드
전환 비용만 늘어 실측상 더 느려졌다(순차 대비 약 2배). 그래서 순차 처리로 되돌렸다.
최초 1회 파싱 비용은 디스크 캐시로 상쇄되므로(이후 실행은 초 단위) 굳이 멀티프로세싱
(진짜 병렬)까지 도입하지 않았다 - PyInstaller onefile 빌드에서 자식 프로세스 재부팅
이슈 등 안정성 리스크가 크기 때문.
"""
import hashlib
import os
import pickle

from pypdf import PdfReader

from .. import settings as app_settings

_CACHE: dict[str, dict[str, list[str]]] = {}  # {folder: {relative_path: [page_text, ...]}}
_CACHE_SIG: dict[str, tuple] = {}  # {folder: (mtime signature)}


def _walk_pdfs(folder: str) -> list[str]:
    paths = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name.lower().endswith(".pdf"):
                paths.append(os.path.join(root, name))
    return sorted(paths)


def _folder_signature(folder: str) -> tuple:
    sig = []
    for path in _walk_pdfs(folder):
        try:
            sig.append((path, os.path.getmtime(path)))
        except OSError:
            pass
    return tuple(sig)


def _cache_file_path(folder: str) -> str:
    h = hashlib.md5(os.path.abspath(folder).encode("utf-8")).hexdigest()
    return os.path.join(app_settings.cache_dir(), f"{h}.pkl")


def _load_disk_cache(folder: str, sig: tuple) -> dict | None:
    path = _cache_file_path(folder)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            saved_sig, data = pickle.load(f)
        if saved_sig == sig:
            return data
    except Exception:
        return None
    return None


def _save_disk_cache(folder: str, sig: tuple, data: dict) -> None:
    try:
        with open(_cache_file_path(folder), "wb") as f:
            pickle.dump((sig, data), f)
    except Exception:
        pass  # 캐시 저장 실패는 무시 (다음 실행시 다시 파싱하는 것으로 충분)


def _extract_pdf_pages(path: str) -> list[str]:
    try:
        reader = PdfReader(path)
    except Exception:
        return []
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def _load_folder(folder: str, on_file=None) -> dict[str, list[str]]:
    paths = _walk_pdfs(folder)
    total = len(paths)
    result: dict[str, list[str]] = {}
    for i, path in enumerate(paths, start=1):
        rel = os.path.relpath(path, folder)
        result[rel] = _extract_pdf_pages(path)
        if on_file:
            on_file(i, total)
    return result


def get_folder_cache(folder: str, on_file=None) -> dict[str, list[str]]:
    if not folder or not os.path.isdir(folder):
        return {}
    sig = _folder_signature(folder)
    if _CACHE_SIG.get(folder) != sig:
        disk_data = _load_disk_cache(folder, sig)
        if disk_data is not None:
            _CACHE[folder] = disk_data
            _CACHE_SIG[folder] = sig
            if on_file:
                total = len(disk_data) or 1
                on_file(total, total)
        else:
            loaded = _load_folder(folder, on_file=on_file)
            _CACHE[folder] = loaded
            _CACHE_SIG[folder] = sig
            _save_disk_cache(folder, sig, loaded)
    return _CACHE.get(folder, {})


def search_folder(folder: str, keywords: list[str], max_hits_per_keyword: int = 3,
                   context: int = 70) -> dict[str, list[dict]]:
    """returns {keyword: [{"file": relative_path, "page": n, "snippet": str}, ...]}"""
    cache = get_folder_cache(folder)
    results = {kw: [] for kw in keywords}
    if not cache:
        return results
    for fname, pages in cache.items():
        for page_no, text in enumerate(pages, start=1):
            if not text:
                continue
            for kw in keywords:
                if len(results[kw]) >= max_hits_per_keyword:
                    continue
                idx = text.find(kw)
                if idx == -1:
                    continue
                start = max(0, idx - context)
                end = min(len(text), idx + len(kw) + context)
                snippet = text[start:end].replace("\n", " ").strip()
                results[kw].append({"file": fname, "page": page_no, "snippet": snippet})
    return results


def search_sources(sources: list[tuple[str, str]], keywords: list[str], max_hits_per_keyword: int = 3,
                    context: int = 70, progress_cb=None) -> dict[str, list[dict]]:
    """여러 출처(예: 시행중 KIFRS / 조기적용가능 KIFRS / 일반기업회계기준)를 각각 검색하여
    결과에 출처(source_label)를 태깅해서 병합. returns {keyword: [{"source_label", "file", "page", "snippet"}, ...]}

    progress_cb(fraction: float 0~1)가 주어지면, 메모리·디스크 캐시가 모두 없어 새로 파싱해야
    하는 폴더들의 전체 PDF 파일수 대비 처리된 파일수 비율을 실시간으로 보고한다."""
    results: dict[str, list[dict]] = {kw: [] for kw in keywords}
    valid_sources = [(label, folder) for label, folder in sources if folder and os.path.isdir(folder)]

    pending_totals = {}
    for _label, folder in valid_sources:
        sig = _folder_signature(folder)
        if _CACHE_SIG.get(folder) == sig:
            continue  # 이미 메모리에 있음
        if _load_disk_cache(folder, sig) is not None:
            continue  # 디스크 캐시로 즉시 로드 가능 - 진행률 분모에서 제외
        pending_totals[folder] = len(_walk_pdfs(folder))
    grand_total = sum(pending_totals.values())
    done_before = 0

    for label, folder in valid_sources:
        if folder in pending_totals and grand_total > 0 and progress_cb:
            base = done_before

            def on_file(i, _total, _base=base):
                progress_cb(min(1.0, (_base + i) / grand_total))

            get_folder_cache(folder, on_file=on_file)
            done_before += pending_totals[folder]
        else:
            get_folder_cache(folder)

        per_source = search_folder(folder, keywords, max_hits_per_keyword=max_hits_per_keyword, context=context)
        for kw, hits in per_source.items():
            for h in hits:
                results[kw].append({**h, "source_label": label})

    if progress_cb:
        progress_cb(1.0)
    return results


def folder_status(folder: str) -> str:
    if not folder:
        return "미설정"
    if not os.path.isdir(folder):
        return "경로 없음"
    n = len(_walk_pdfs(folder))
    return f"PDF {n}개 인식됨(하위폴더 포함)" if n else "PDF 파일 없음"
