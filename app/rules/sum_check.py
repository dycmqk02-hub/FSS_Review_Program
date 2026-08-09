"""표 내 소계/합계 검산 및 동일 라벨 금액 교차대사 (휴리스틱 - 오탐 가능)."""
from .. import pdf_utils


def _is_sum_label(label: str) -> bool:
    s = (label or "").replace(" ", "")
    return s.endswith("합계") or s.endswith("소계") or s.endswith("총계") or s == "계"


def check_table_sums(tables: list[tuple[int, list[list[str]]]], tolerance_ratio: float = 0.001) -> list[dict]:
    """표(pdfplumber 추출)에서 '소계/합계' 행의 값이 바로 위 항목행들의 합과 일치하는지 검산."""
    findings = []
    for page_no, rows in tables:
        if len(rows) < 2:
            continue
        ncols = max(len(r) for r in rows)
        norm_rows = [r + [""] * (ncols - len(r)) for r in rows]
        boundary = 0
        for ridx, row in enumerate(norm_rows):
            label = row[0] or ""
            if not _is_sum_label(label):
                continue
            for cidx in range(1, ncols):
                target = pdf_utils.parse_number(row[cidx])
                if target is None:
                    continue
                candidates = [
                    v for i in range(boundary, ridx)
                    if (v := pdf_utils.parse_number(norm_rows[i][cidx])) is not None
                ]
                if len(candidates) < 2:
                    continue
                total = sum(candidates)
                tolerance = max(2.0, abs(target) * tolerance_ratio)
                if abs(total - target) > tolerance:
                    findings.append({
                        "page": page_no,
                        "row_label": label.strip(),
                        "column": cidx,
                        "stated": target,
                        "computed": total,
                        "diff": total - target,
                        "n_items": len(candidates),
                    })
            boundary = ridx
    return findings


def cross_check_labels(pages: list[str]) -> list[dict]:
    """동일 라벨('계정과목 금액' 형태 줄)이 문서 내 여러 페이지에서 다른 금액으로 나타나는지 스크리닝
    (재무제표 본문 vs 주석 간 대사 불일치 후보 탐지용, 위양성 다수 가능)."""
    index = pdf_utils.build_label_value_index(pages)
    findings = []
    for label, occurrences in index.items():
        if len(occurrences) < 2:
            continue
        values = {v for v, _ in occurrences}
        if len(values) > 1:
            findings.append({
                "label": label,
                "occurrences": occurrences,
            })
    findings.sort(key=lambda f: -len(f["occurrences"]))
    return findings[:80]  # 상위 80건만 표시 (과도한 노이즈 방지)
