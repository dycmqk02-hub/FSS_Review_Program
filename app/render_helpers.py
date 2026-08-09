"""결과 데이터를 CustomTkinter 카드/배지 위젯으로 렌더링하는 재사용 헬퍼."""
import customtkinter as ctk

from . import theme


def clear(frame):
    for w in frame.winfo_children():
        w.destroy()


def badge(parent, text, bg, fg=None):
    return ctk.CTkLabel(parent, text=text, fg_color=bg, text_color=fg or theme.TEXT_MAIN,
                         corner_radius=12, font=theme.FONT_SMALL, padx=10, pady=3)


def section_title(parent, text):
    ctk.CTkLabel(parent, text=text, font=theme.FONT_SUBTITLE, text_color=theme.TEXT_MAIN,
                 anchor="w").pack(fill="x", padx=6, pady=(16, 6))


def doc_label_title(parent, text):
    ctk.CTkLabel(parent, text=text, font=theme.FONT_TITLE, text_color=theme.ACCENT_PRIMARY_HOVER,
                 anchor="w").pack(fill="x", padx=4, pady=(18, 4))


def card(parent):
    f = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=10,
                      border_width=1, border_color=theme.BORDER_SOFT)
    f.pack(fill="x", pady=4, padx=4)
    return f


def empty_note(parent, text):
    ctk.CTkLabel(parent, text=text, font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
                 anchor="w").pack(fill="x", padx=8, pady=8)


def render_checklist(container, items):
    section_title(container, "필수 기재사항 체크리스트 (문단46 등)")
    found_n = sum(1 for i in items if i["found"])
    req_missing = [i for i in items if i.get("required") and not i["found"]]
    stat_row = ctk.CTkFrame(container, fg_color="transparent")
    stat_row.pack(fill="x", padx=4, pady=(0, 6))
    badge(stat_row, f"확인 {found_n}/{len(items)}", theme.ACCENT_SKY).pack(side="left", padx=4)
    if req_missing:
        badge(stat_row, f"필수 미확인 {len(req_missing)}건", theme.ACCENT_CORAL).pack(side="left", padx=4)
    else:
        badge(stat_row, "필수 항목 모두 확인됨", theme.ACCENT_MINT).pack(side="left", padx=4)

    for item in items:
        if item["found"]:
            color, label = theme.ACCENT_MINT, "확인됨"
        elif item.get("required"):
            color, label = theme.ACCENT_CORAL, "필수 미확인"
        else:
            color, label = theme.ACCENT_PEACH, "해당시 확인"
        row = card(container)
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 2))
        badge(top, label, color).pack(side="left")
        ctk.CTkLabel(top, text=f"  {item.get('para', '')}  ·  {item.get('category', '')}",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(row, text=item["title"], font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
                     anchor="w", justify="left", wraplength=780).pack(fill="x", padx=12, pady=(0, 8))
        if item["found"] and item.get("matched"):
            ctk.CTkLabel(row, text=f"매칭 문구: “{item['matched']}”", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SUB, anchor="w").pack(fill="x", padx=12, pady=(0, 8))


def render_opinion(container, opinion_data):
    section_title(container, "검토의견 유형 판단")
    op_type = opinion_data["opinion_type"]
    color_map = {
        "적정(변형 없음)": theme.ACCENT_MINT,
        "한정의견": theme.ACCENT_PEACH,
        "부적정의견": theme.ACCENT_CORAL,
        "의견거절": theme.ACCENT_CORAL,
    }
    color = color_map.get(op_type, theme.ACCENT_SKY)
    row = card(container)
    inner = ctk.CTkFrame(row, fg_color="transparent")
    inner.pack(fill="x", padx=12, pady=10)
    badge(inner, op_type, color).pack(side="left")
    for c in opinion_data["checks"]:
        crow = card(container)
        top = ctk.CTkFrame(crow, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=8)
        mark_color = theme.ACCENT_MINT if c["ok"] else (theme.ACCENT_SKY if c["ok"] is None else theme.ACCENT_CORAL)
        mark_text = "OK" if c["ok"] else ("확인필요" if c["ok"] is None else "미확인")
        badge(top, mark_text, mark_color).pack(side="left")
        ctk.CTkLabel(top, text=c["item"], font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
                     anchor="w", justify="left", wraplength=680).pack(side="left", padx=8)


def render_comparative(container, checks):
    section_title(container, "비교표시 재무정보 체크 (문단47~48)")
    for c in checks:
        row = card(container)
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=8)
        color = theme.ACCENT_MINT if c["ok"] else theme.ACCENT_PEACH
        badge(top, "확인됨" if c["ok"] else "해당시 확인", color).pack(side="left")
        ctk.CTkLabel(top, text=c["item"], font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
                     anchor="w", justify="left", wraplength=680).pack(side="left", padx=8)


def render_accounting_changes(container, changes):
    section_title(container, "전기말 대비 당반기중 회계처리 변경 관련 키워드 탐지")
    if not changes:
        empty_note(container, "탐지된 항목이 없습니다.")
        return
    badge(container, f"탐지 {len(changes)}건", theme.ACCENT_SKY).pack(anchor="w", padx=4, pady=(0, 6))
    for f in changes[:60]:
        row = card(container)
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 2))
        badge(top, f"p.{f['page']}", theme.ACCENT_SKY).pack(side="left")
        ctk.CTkLabel(top, text=f"  [{f['keyword']}]", font=theme.FONT_SMALL,
                     text_color=theme.ACCENT_PRIMARY_HOVER).pack(side="left")
        ctk.CTkLabel(row, text=f"...{f['snippet']}...", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w", justify="left", wraplength=780).pack(fill="x", padx=12, pady=(0, 8))
    if len(changes) > 60:
        empty_note(container, f"외 {len(changes) - 60}건 더 있습니다 (TXT/DOCX 내보내기에서 전체 확인).")


def render_sum_check(container, findings):
    section_title(container, "표 소계·합계 검산 (휴리스틱 - 오탐 가능)")
    if not findings:
        empty_note(container, "불일치 후보가 없습니다 (또는 표 구조상 자동 검산이 불가하여 육안 확인이 필요합니다).")
        return
    badge(container, f"불일치 후보 {len(findings)}건", theme.ACCENT_CORAL).pack(anchor="w", padx=4, pady=(0, 6))
    for f in findings[:60]:
        row = card(container)
        ctk.CTkLabel(
            row,
            text=(f"p.{f['page']}  '{f['row_label']}' {f['column']}번째 숫자열 : "
                  f"기재값 {f['stated']:,.0f}  vs  항목합계 {f['computed']:,.0f}  "
                  f"(차이 {f['diff']:,.0f}, 합산항목수 {f['n_items']})"),
            font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN, anchor="w", justify="left", wraplength=780,
        ).pack(fill="x", padx=12, pady=8)


def render_cross_check(container, findings):
    section_title(container, "동일 라벨 금액 교차대사 후보 (휴리스틱, 상위 항목만 표시)")
    if not findings:
        empty_note(container, "탐지된 항목이 없습니다.")
        return
    for f in findings[:40]:
        occ = ", ".join(f"{v:,.0f}(p.{p})" for v, p in f["occurrences"][:8])
        row = card(container)
        ctk.CTkLabel(row, text=f"'{f['label']}'  →  {occ}", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MAIN, anchor="w", justify="left", wraplength=780)\
            .pack(fill="x", padx=12, pady=8)


def render_reference(container, ref_matches, ref_sources):
    section_title(container, "참조자료 자동 매칭 결과")
    status_row = ctk.CTkFrame(container, fg_color="transparent")
    status_row.pack(fill="x", padx=4, pady=(0, 6))
    for src in ref_sources or []:
        color = theme.ref_source_color(src["label"])
        badge(status_row, f"{src['label']}: {src['status']}", color).pack(side="left", padx=(0, 6))

    hits_found = any(hits for hits in (ref_matches or {}).values())
    if not hits_found:
        empty_note(container, "탐지된 회계처리 변경 키워드가 없거나 참조폴더가 설정되지 않아 매칭 결과가 없습니다. "
                               "사이드바 '설정'에서 참조자료 폴더를 지정하십시오.")
        return
    for kw, hits in ref_matches.items():
        if not hits:
            continue
        section_title(container, f"키워드: {kw}")
        for h in hits:
            row = card(container)
            top = ctk.CTkFrame(row, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(8, 2))
            badge(top, h.get("source_label", "참조자료"), theme.ref_source_color(h.get("source_label", ""))).pack(side="left")
            badge(top, f"{h['file']} p.{h['page']}", theme.BG_SIDEBAR).pack(side="left", padx=(6, 0))
            ctk.CTkLabel(row, text=f"...{h['snippet']}...", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                         anchor="w", justify="left", wraplength=780).pack(fill="x", padx=12, pady=(0, 8))


def render_variance_tables(container, variance_tables, detected_unit, pm_threshold, variance_source=None):
    section_title(container, "재무제표 증감분석 (당기 vs 전기)")
    info = ctk.CTkFrame(container, fg_color="transparent")
    info.pack(fill="x", padx=4, pady=(0, 8))
    if variance_source:
        src_color = theme.ACCENT_MINT if "XBRL" in variance_source else theme.ACCENT_PEACH
        badge(info, f"산출방식: {variance_source}", src_color).pack(side="left", padx=(0, 6))
    if detected_unit:
        badge(info, f"감지된 단위: {detected_unit}", theme.ACCENT_SKY).pack(side="left", padx=(0, 6))
    if pm_threshold:
        badge(info, f"금액차이 기준(PM): {pm_threshold:,.0f}", theme.VARIANCE_AMOUNT_COLOR).pack(side="left", padx=(0, 6))
    else:
        badge(info, "PM 미입력 - 금액차이 음영 비활성", theme.BG_SIDEBAR).pack(side="left", padx=(0, 6))
    badge(info, "증감률 5%↑ 음영 항상 적용", theme.VARIANCE_PCT_COLOR).pack(side="left", padx=(0, 6))
    badge(info, "두 조건 모두 해당", theme.VARIANCE_BOTH_COLOR).pack(side="left", padx=(0, 6))

    order = ["재무상태표", "손익계산서", "자본변동표", "현금흐름표"]
    for stmt in order:
        data = variance_tables.get(stmt, {"rows": [], "note": "데이터 없음"})
        _render_variance_stmt(container, stmt, data)


def _render_variance_stmt(container, stmt_name, data):
    section_title(container, stmt_name)
    note = data.get("note")
    if note:
        empty_note(container, note)
    rows = data.get("rows", [])
    if not rows:
        return

    table = ctk.CTkFrame(container, fg_color=theme.BG_CARD, corner_radius=10,
                          border_width=1, border_color=theme.BORDER_SOFT)
    table.pack(fill="x", pady=4, padx=4)
    headers = ["계정과목", "구분", "당기금액", "전기금액", "금액차이", "증감률"]
    for c, h in enumerate(headers):
        ctk.CTkLabel(table, text=h, font=theme.FONT_SUBTITLE, text_color=theme.TEXT_MAIN,
                     anchor="w").grid(row=0, column=c, sticky="w", padx=8, pady=(8, 4))

    for r, row in enumerate(rows, start=1):
        if row.get("amount_flag") and row.get("pct_flag"):
            bg = theme.VARIANCE_BOTH_COLOR
        elif row.get("amount_flag"):
            bg = theme.VARIANCE_AMOUNT_COLOR
        elif row.get("pct_flag"):
            bg = theme.VARIANCE_PCT_COLOR
        else:
            bg = theme.BG_MAIN
        pct_text = f"{row['pct'] * 100:,.1f}%" if row["pct"] is not None else "N/A"
        values = [
            row["label"], row.get("segment") or "-",
            f"{row['current']:,.0f}", f"{row['prior']:,.0f}", f"{row['diff']:,.0f}", pct_text,
        ]
        for c, v in enumerate(values):
            ctk.CTkLabel(table, text=v, font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                         fg_color=bg, corner_radius=4, anchor="w" if c == 0 else "e")\
                .grid(row=r, column=c, sticky="ew", padx=2, pady=1, ipady=3, ipadx=4)

    table.grid_columnconfigure(0, weight=3)
    for c in range(1, len(headers)):
        table.grid_columnconfigure(c, weight=1)


def render_consol_vs_sep(container, data):
    section_title(container, "연결 vs 별도 핵심 키워드 존재 여부 비교")
    for c in data["keyword_comparison"]:
        row = card(container)
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(top, text=c["keyword"], font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
                     width=160, anchor="w").pack(side="left")
        badge(top, "연결 O" if c["in_consol"] else "연결 X",
              theme.ACCENT_MINT if c["in_consol"] else theme.ACCENT_CORAL).pack(side="left", padx=4)
        badge(top, "별도 O" if c["in_separate"] else "별도 X",
              theme.ACCENT_MINT if c["in_separate"] else theme.ACCENT_CORAL).pack(side="left", padx=4)

    section_title(container, "실무 참고 체크리스트 (준칙 명문조항은 아님)")
    for item in data["practice_checklist"]:
        row = card(container)
        ctk.CTkLabel(row, text=item["item"], font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
                     anchor="w", justify="left", wraplength=780).pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(row, text=f"→ {item['note']}", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w", justify="left", wraplength=780).pack(fill="x", padx=12, pady=(0, 8))
