"""향후 추가할 반기검토체크리스트 파일(CSV/XLSX) 로더 - 확장 포인트.

사용법(설정 화면에서 파일 경로 지정):
  CSV/XLSX 컬럼 구성 - 구분 | 문단/항목 | 설명 | 키워드 | 필수여부
  - 구분: 체크리스트 결과 화면에 표시될 카테고리명 (예: "특수관계자 공시")
  - 문단/항목: 근거 조항/체크리스트 항목 번호 (예: "II-3-가")
  - 설명: 점검 내용 설명
  - 키워드: 보고서 본문에서 존재 여부를 확인할 키워드(쉼표로 여러 개 구분, OR 조건)
  - 필수여부: "필수" 또는 "Y" 입력 시 필수 항목으로 표시, 그 외는 참고 항목
"""
import csv
import os


def load_custom_checklist(path: str) -> list[dict]:
    if not path or not os.path.exists(path):
        return []
    ext = os.path.splitext(path)[1].lower()

    rows: list[dict] = []
    if ext == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    elif ext in (".xlsx", ".xls"):
        try:
            import openpyxl
        except ImportError:
            return []
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        header_row = next(ws.iter_rows(min_row=1, max_row=1))
        headers = [str(c.value).strip() if c.value is not None else "" for c in header_row]
        for row in ws.iter_rows(min_row=2):
            values = [c.value for c in row]
            rows.append(dict(zip(headers, values)))
    else:
        return []

    items = []
    for r in rows:
        keywords_raw = str(r.get("키워드", "") or "")
        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        if not keywords:
            continue
        required_raw = str(r.get("필수여부", "") or "").strip()
        items.append({
            "id": f"custom-{len(items) + 1}",
            "category": (r.get("구분") or "커스텀 체크리스트").strip() if isinstance(r.get("구분"), str) else (r.get("구분") or "커스텀 체크리스트"),
            "para": r.get("문단/항목", "") or "",
            "title": r.get("설명", "") or "",
            "any_of": keywords,
            "required": required_raw in ("필수", "Y", "y", "TRUE", "True", "1"),
        })
    return items
