"""결과 데이터를 CustomTkinter 카드/배지 위젯으로 렌더링하는 재사용 헬퍼."""
import tkinter.font as tkfont

import customtkinter as ctk

from . import theme


def clear(frame):
    for w in frame.winfo_children():
        w.destroy()


class WrappingTabBar(ctk.CTkFrame):
    """CTkTabview의 세그먼트 버튼은 창이 좁아지면 글자를 그냥 잘라버린다. 이 위젯은
    버튼들을 place()로 직접 배치해, 폭이 부족하면 자동으로 다음 줄로 넘겨(줄바꿈)
    항상 전체 글자가 보이게 한다."""

    def __init__(self, master, tab_names, on_select, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.tab_names = list(tab_names)
        self._on_select_cb = on_select
        self.active = self.tab_names[0]
        self.buttons = {}
        measure_font = tkfont.Font(family=theme.FONT_BODY[0], size=theme.FONT_BODY[1])
        for name in self.tab_names:
            btn_w = measure_font.measure(name) + 32
            btn = ctk.CTkButton(
                self, text=name, corner_radius=10, height=32, width=btn_w, font=theme.FONT_BODY,
                command=lambda n=name: self.select(n),
            )
            self.buttons[name] = btn
        self._relayout_after_id = None
        # 위젯 자신뿐 아니라 최상위 창의 <Configure>도 함께 구독한다. CTkButton은 생성 직후
        # winfo_reqwidth()가 아직 DPI 스케일링이 100% 반영되지 않은 값을 돌려줄 수 있어,
        # 첫 배치 이후에도 한 번 더 재계산해 최종 크기로 맞춘다(캐시 없이 매번 재계산).
        self.bind("<Configure>", self._schedule_relayout)
        self.winfo_toplevel().bind("<Configure>", self._schedule_relayout, add="+")
        self.select(self.tab_names[0], notify=False)
        self._schedule_relayout()
        self.after(250, self._schedule_relayout)

    def select(self, name, notify=True):
        self.active = name
        for n, b in self.buttons.items():
            selected = n == name
            b.configure(
                fg_color=theme.ACCENT_PRIMARY if selected else theme.BG_SIDEBAR,
                text_color=theme.TEXT_ON_ACCENT if selected else theme.TEXT_MAIN,
                hover_color=theme.ACCENT_PRIMARY_HOVER if selected else theme.BORDER_SOFT,
            )
        if notify:
            self._on_select_cb(name)

    def _schedule_relayout(self, event=None):
        if self._relayout_after_id is not None:
            self.after_cancel(self._relayout_after_id)
        self._relayout_after_id = self.after(20, self._relayout_now)

    def _relayout_now(self):
        self._relayout_after_id = None
        self.update_idletasks()
        self._relayout(self.winfo_width())

    def _relayout(self, width):
        if width <= 1:
            return
        # CTk의 place()는 x/y를 위젯 스케일링(DPI) 비율만큼 다시 곱해서 넘긴다. winfo_reqwidth()는
        # 이미 스케일이 적용된 실제 픽셀값이므로, 그대로 누적해 place(x=..)에 넘기면 이중으로
        # 배율이 걸려 오른쪽으로 갈수록 어긋난다 - 전부 스케일 적용 전(논리) 단위로 계산한다.
        scaling = self._get_widget_scaling()
        logical_width = width / scaling
        x = y = 0
        pad_x, pad_y = 6, 6
        row_h = 0
        for name in self.tab_names:
            btn = self.buttons[name]
            req_w = btn.winfo_reqwidth() / scaling
            req_h = btn.winfo_reqheight() / scaling
            if x + req_w > logical_width and x > 0:
                x = 0
                y += row_h + pad_y
                row_h = 0
            btn.place(x=x, y=y)
            x += req_w + pad_x
            row_h = max(row_h, req_h)
        self.configure(height=y + row_h)


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
    section_title(container, "필수 기재사항 체크리스트 (검토: 준칙 문단46 / 감사: 감사기준서 700·701·570 등)")
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
    section_title(container, "의견 유형 판단 (검토의견 / 감사의견)")
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


_CALC_CHECK_STMT_ORDER = ["재무상태표", "손익계산서", "자본변동표", "현금흐름표"]


def _mismatch_table(container, mismatches):
    table = ctk.CTkFrame(container, fg_color=theme.BG_CARD, corner_radius=10,
                          border_width=1, border_color=theme.BORDER_SOFT)
    table.pack(fill="x", pady=4, padx=4)
    headers = ["구분", "대상", "기재값", "계산값", "차이", "하위항목"]
    for c, h in enumerate(headers):
        ctk.CTkLabel(table, text=h, font=theme.FONT_SUBTITLE, text_color=theme.TEXT_MAIN,
                     anchor="w").grid(row=0, column=c, sticky="w", padx=8, pady=(8, 4))
    for r, m in enumerate(mismatches[:40], start=1):
        children_txt = ", ".join(m.get("children", [])[:6])
        values = [m.get("period") or "-", m["parent"], f"{m['stated']:,.0f}",
                  f"{m['computed']:,.0f}", f"{m['diff']:,.0f}", children_txt]
        for c, v in enumerate(values):
            ctk.CTkLabel(table, text=v, font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                         fg_color=theme.ACCENT_CORAL, corner_radius=4,
                         anchor="w" if c in (1, 5) else "e")\
                .grid(row=r, column=c, sticky="ew", padx=2, pady=1, ipady=3, ipadx=4)
    table.grid_columnconfigure(1, weight=3)
    table.grid_columnconfigure(5, weight=3)
    for c in (0, 2, 3, 4):
        table.grid_columnconfigure(c, weight=1)
    if len(mismatches) > 40:
        empty_note(container, f"외 {len(mismatches) - 40}건 더 있습니다.")


def render_calc_check(container, calc_check):
    """calc_check: {"xbrl": {stmt:{"mismatches","skipped","note"}}|None, "pdf": {...}}
    (XBRL은 업로드된 경우에만, PDF는 항상 존재)."""
    section_title(container, "재무제표 계층별 합계검증 (leaf 합계 → 소계 → 최상위 총계, 전 레벨)")
    sources = []
    if calc_check.get("xbrl"):
        sources.append(("XBRL(정밀 매칭)", calc_check["xbrl"], theme.ACCENT_MINT))
    if calc_check.get("pdf"):
        sources.append(("PDF 표(휴리스틱, 오탐 가능)", calc_check["pdf"], theme.ACCENT_PEACH))
    if calc_check.get("excel"):
        sources.append(("Excel(직접 검토, 가장 신뢰도 높음)", calc_check["excel"], theme.ACCENT_SKY))
    if not sources:
        empty_note(container, "검증 결과가 없습니다.")
        return

    total = sum(len(data.get(s, {}).get("mismatches", [])) for _l, data, _c in sources for s in _CALC_CHECK_STMT_ORDER)
    badge(container, f"불일치 {total}건" if total else "전 재무제표 합계 일치",
          theme.ACCENT_CORAL if total else theme.ACCENT_MINT).pack(anchor="w", padx=4, pady=(0, 6))

    for stmt in _CALC_CHECK_STMT_ORDER:
        if not any(data.get(stmt) for _l, data, _c in sources):
            continue
        section_title(container, stmt)
        for src_label, data, src_color in sources:
            stmt_data = data.get(stmt)
            if not stmt_data:
                continue
            badge(container, src_label, src_color).pack(anchor="w", padx=4, pady=(2, 2))
            note = stmt_data.get("note")
            if note:
                empty_note(container, note)
                continue
            mismatches = stmt_data.get("mismatches", [])
            if not mismatches:
                empty_note(container, "불일치 없음")
            else:
                _mismatch_table(container, mismatches)
            skipped = stmt_data.get("skipped", [])
            if skipped:
                empty_note(container, f"하위 요소 값 누락으로 검증 불가 {len(skipped)}건 "
                                       f"(일부 하위 요소를 원문에서 찾지 못함 - 주석 전용 요소일 수 있음)")


def render_cross_check_fs(container, cross_check):
    """cross_check: {"xbrl": [...]|None, "pdf": [...]}. 각 항목: {"item","values":[{"source",
    "label","value"},...],"diff"}. 불일치 항목만 포함되어 있음(일치 항목은 이미 제외됨)."""
    section_title(container, "FS간 교차검증 (동일 계정과목의 재무제표간 대사)")
    sources = []
    if cross_check.get("xbrl") is not None:
        sources.append(("XBRL(정밀 매칭)", cross_check["xbrl"], theme.ACCENT_MINT))
    if cross_check.get("pdf") is not None:
        sources.append(("PDF 표(휴리스틱, 오탐 가능)", cross_check["pdf"], theme.ACCENT_PEACH))
    if cross_check.get("excel") is not None:
        sources.append(("Excel(직접 검토 - 재무제표간/재무제표-주석간/주석간 모두 포함)",
                          cross_check["excel"], theme.ACCENT_SKY))
    if not sources:
        empty_note(container, "검증 결과가 없습니다.")
        return

    total = sum(len(findings) for _l, findings, _c in sources)
    badge(container, f"불일치 {total}건" if total else "교차검증 항목 모두 일치",
          theme.ACCENT_CORAL if total else theme.ACCENT_MINT).pack(anchor="w", padx=4, pady=(0, 6))

    for src_label, findings, src_color in sources:
        badge(container, src_label, src_color).pack(anchor="w", padx=4, pady=(4, 2))
        if not findings:
            empty_note(container, "불일치 없음")
            continue
        for f in findings[:30]:
            section_title(container, f["item"])
            table = ctk.CTkFrame(container, fg_color=theme.BG_CARD, corner_radius=10,
                                  border_width=1, border_color=theme.BORDER_SOFT)
            table.pack(fill="x", pady=4, padx=4)
            headers = ["출처", "라벨", "값"]
            for c, h in enumerate(headers):
                ctk.CTkLabel(table, text=h, font=theme.FONT_SUBTITLE, text_color=theme.TEXT_MAIN,
                             anchor="w").grid(row=0, column=c, sticky="w", padx=8, pady=(8, 4))
            for r, v in enumerate(f["values"], start=1):
                cells = [v["source"], v["label"], f"{v['value']:,.0f}"]
                for c, cell_v in enumerate(cells):
                    ctk.CTkLabel(table, text=cell_v, font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                                 fg_color=theme.ACCENT_CORAL, corner_radius=4, anchor="w" if c < 2 else "e")\
                        .grid(row=r, column=c, sticky="ew", padx=2, pady=1, ipady=3, ipadx=4)
            table.grid_columnconfigure(0, weight=2)
            table.grid_columnconfigure(1, weight=2)
            table.grid_columnconfigure(2, weight=1)
        if len(findings) > 30:
            empty_note(container, f"외 {len(findings) - 30}건 더 있습니다 (자동 저장된 Excel에서 전체 확인 가능).")


def render_disclosure_check(container, disclosure_check):
    """disclosure_check: {"items":[{"section","reference","text","keywords","hits","found"}],
    "path","error"}. 감사조서서식 8400 공시사항점검표(KIFRS/일반기준)와 보고서 본문을 키워드
    기반으로 대사한 결과."""
    section_title(container, "공시사항점검표 대사 (감사조서서식 8400)")
    empty_note(container, "⚠️ 형태소 분석 없는 키워드 매칭 휴리스틱입니다 - 요구사항 문장이 "
                           "추상적인 경우 오탐(실제로는 있는데 '미확인'으로 표시)이 있을 수 있습니다. "
                           "반드시 '미확인' 항목을 원문·주석과 직접 대조하십시오.")
    err = disclosure_check.get("error")
    path = disclosure_check.get("path")
    if err:
        empty_note(container, f"{err}\n(⚙ 참조자료 폴더 설정에서 경로를 확인하세요)")
        return
    items = disclosure_check.get("items", [])
    if not items:
        empty_note(container, "대사할 공시사항점검표 항목이 없습니다.")
        return

    n_found = sum(1 for i in items if i["found"])
    n_missing = len(items) - n_found
    badge(container, f"확인 {n_found} / 미확인 {n_missing} (총 {len(items)}건)",
          theme.ACCENT_CORAL if n_missing else theme.ACCENT_MINT).pack(anchor="w", padx=4, pady=(0, 4))
    if path:
        empty_note(container, f"점검표 파일: {path}")

    missing = [i for i in items if not i["found"]]
    by_section: dict[str, list] = {}
    for i in missing:
        by_section.setdefault(i.get("section") or "(섹션 미상)", []).append(i)

    for sec, sec_items in by_section.items():
        section_title(container, f"{sec} - 미확인 {len(sec_items)}건")
        for i in sec_items[:25]:
            row = card(container)
            ctk.CTkLabel(row, text=f"[{i['reference']}]", font=theme.FONT_SMALL,
                         text_color=theme.ACCENT_PRIMARY_HOVER, anchor="w").pack(fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(row, text=i["text"], font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                         anchor="w", justify="left", wraplength=780).pack(fill="x", padx=12, pady=(2, 4))
            ctk.CTkLabel(row, text=f"검색 키워드: {', '.join(i['keywords'])}", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SUB, anchor="w").pack(fill="x", padx=12, pady=(0, 8))
        if len(sec_items) > 25:
            empty_note(container, f"외 {len(sec_items) - 25}건 더 있습니다.")


def render_note_check(container, note_check):
    """note_check: {"xbrl": {"cross_reference":{"confirmed","unmatched"},"calc_hierarchy":[...]}
    |None, "pdf": {"amount_tracing":{"confirmed","unmatched"},"table_hierarchy":[...]}}."""
    section_title(container, "주석(Note) 공시 대사")

    xbrl = note_check.get("xbrl")
    pdf = note_check.get("pdf") or {}

    if xbrl:
        badge(container, "XBRL(정밀 매칭)", theme.ACCENT_MINT).pack(anchor="w", padx=4, pady=(2, 2))
        cr = xbrl.get("cross_reference") or {}
        empty_note(container, f"확인됨 {cr.get('confirmed', 0)}건 (재무제표 계정과 동일 요소가 주석에도 "
                               f"태깅됨) / 주석 미확인 {len(cr.get('unmatched', []))}건 "
                               f"(주석에 해당 요소가 태깅되지 않음 - 서술식 설명만 있을 수 있어 반드시 누락은 아님)")
        for u in cr.get("unmatched", [])[:30]:
            row = card(container)
            ctk.CTkLabel(row, text=f"[{u['stmt']}] {u['label']} ({u['element']}) = {u['value']:,.0f}",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN, anchor="w", justify="left",
                         wraplength=780).pack(fill="x", padx=12, pady=6)
        calc_hier = xbrl.get("calc_hierarchy") or []
        section_title(container, "주석 내 계층별 합계검증 (Calculation Linkbase)")
        if not calc_hier:
            empty_note(container, "불일치 없음 (계산관계가 정의된 주석 role이 없거나 전부 일치).")
        else:
            _mismatch_table(container, [{**m, "parent": f"[{m['note']}] {m['parent']}"} for m in calc_hier])

    badge(container, "PDF 표(휴리스틱, 오탐 가능)", theme.ACCENT_PEACH).pack(anchor="w", padx=4, pady=(6, 2))
    at = pdf.get("amount_tracing") or {}
    empty_note(container, f"확인됨 {at.get('confirmed', 0)}건 (재무제표 금액이 참조 주석 본문에 실제로 등장) / "
                           f"주석 미확인 {len(at.get('unmatched', []))}건")
    for u in at.get("unmatched", [])[:30]:
        row = card(container)
        ctk.CTkLabel(row, text=f"[{u['stmt']}] {u['label']} = {u['value']:,.0f}  (참조 주석: {', '.join(u['notes'])})",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN, anchor="w", justify="left",
                     wraplength=780).pack(fill="x", padx=12, pady=6)
    table_hier = pdf.get("table_hierarchy") or []
    section_title(container, "주석 표 내 계층별 합계검증 (로마자/괄호숫자/총계류)")
    if not table_hier:
        empty_note(container, "불일치 없음 (또는 검증 가능한 로마자/괄호숫자 계층 구조가 있는 표가 없음).")
    else:
        _mismatch_table(container, [{**m, "parent": f"[{m['note']}] {m['parent']}"} for m in table_hier])


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
        for h in hits[:30]:
            row = card(container)
            top = ctk.CTkFrame(row, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(8, 2))
            badge(top, h.get("source_label", "참조자료"), theme.ref_source_color(h.get("source_label", ""))).pack(side="left")
            badge(top, f"{h['file']} p.{h['page']}", theme.BG_SIDEBAR).pack(side="left", padx=(6, 0))
            ctk.CTkLabel(row, text=f"...{h['snippet']}...", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                         anchor="w", justify="left", wraplength=780).pack(fill="x", padx=12, pady=(0, 8))
        if len(hits) > 30:
            empty_note(container, f"외 {len(hits) - 30}건 더 있습니다.")


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
        bg = theme.VARIANCE_AMOUNT_COLOR if row.get("amount_flag") else theme.BG_MAIN
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

    amt = data.get("amount_comparison") or []
    if amt:
        section_title(container, "연결 vs 별도 재무제표 계정별 금액 비교 (차이 = 검토포인트, 오류 아님)")
        diff_rows = [r for r in amt if r["status"] != "동일"]
        badge(container, f"비교 {len(amt)}계정 / 동일 {len(amt) - len(diff_rows)} / 차이·한쪽만 {len(diff_rows)}",
              theme.ACCENT_SKY).pack(anchor="w", padx=4, pady=(0, 6))
        _simple_table(container, ["재무제표", "계정과목", "연결 당기", "별도 당기", "차이(당기)", "상태"],
                      [[r["stmt"], r["label"], _fmt(r["consol_cy"]), _fmt(r["sep_cy"]), _fmt(r["diff_cy"]), r["status"]]
                       for r in diff_rows[:60]])

    section_title(container, "실무 참고 체크리스트 (준칙 명문조항은 아님)")
    for item in data["practice_checklist"]:
        row = card(container)
        ctk.CTkLabel(row, text=item["item"], font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
                     anchor="w", justify="left", wraplength=780).pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(row, text=f"→ {item['note']}", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w", justify="left", wraplength=780).pack(fill="x", padx=12, pady=(0, 8))


def render_excel_compare(container, compare_results):
    """Excel 정밀검증(사이드바 ⑧)의 계정과목 단위 연결-별도 비교. compare_results 각 행:
    {"구분표","계정과목","기간","별도","연결","차이"}."""
    section_title(container, "연결-별도 비교 (Excel 정밀검증, 계정과목 단위)")
    if not compare_results:
        empty_note(container, "Excel 정밀검증 파일이 준비되지 않았습니다(사이드바 ⑧에서 PDF로 초안을 "
                               "생성하거나 템플릿을 채운 뒤 파일을 지정하면 계정과목 단위로 별도/연결 금액과 "
                               "차이를 비교합니다).")
        return
    n_diff = sum(1 for r in compare_results if (r.get("차이") or 0) != 0)
    badge(container, f"비교 {len(compare_results)}건 · 차이 존재 {n_diff}건",
          theme.ACCENT_PEACH if n_diff else theme.ACCENT_MINT).pack(anchor="w", padx=4, pady=(0, 6))
    empty_note(container, "차이가 있다고 오류는 아닙니다(종속기업 실적 반영·내부거래 제거 등으로 정상적으로 "
                           "차이가 남) - 연결조정 내역으로 설명되는지 확인할 검토포인트 후보 목록입니다.")

    table = ctk.CTkFrame(container, fg_color=theme.BG_CARD, corner_radius=10,
                          border_width=1, border_color=theme.BORDER_SOFT)
    table.pack(fill="x", pady=4, padx=4)
    headers = ["구분표", "계정과목", "기간", "별도", "연결", "차이"]
    for c, h in enumerate(headers):
        ctk.CTkLabel(table, text=h, font=theme.FONT_SUBTITLE, text_color=theme.TEXT_MAIN,
                     anchor="w").grid(row=0, column=c, sticky="w", padx=8, pady=(8, 4))
    for r, row in enumerate(compare_results[:100], start=1):
        diff = row.get("차이")
        bg = theme.ACCENT_PEACH if (diff not in (None, 0)) else theme.BG_MAIN
        values = [row["구분표"], row["계정과목"], row["기간"],
                  f"{row['별도']:,.0f}" if row.get("별도") is not None else "",
                  f"{row['연결']:,.0f}" if row.get("연결") is not None else "",
                  f"{diff:,.0f}" if diff is not None else ""]
        for c, v in enumerate(values):
            ctk.CTkLabel(table, text=v, font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                         fg_color=bg, corner_radius=4, anchor="w" if c in (0, 1) else "e")\
                .grid(row=r, column=c, sticky="ew", padx=2, pady=1, ipady=3, ipadx=4)
    table.grid_columnconfigure(1, weight=3)
    for c in (0, 2, 3, 4, 5):
        table.grid_columnconfigure(c, weight=1)
    if len(compare_results) > 100:
        empty_note(container, f"외 {len(compare_results) - 100}건 더 있습니다 (자동 저장된 Excel에서 전체 확인 가능).")


def _fmt(v):
    return "-" if v is None else f"{v:,.0f}"


def _simple_table(container, headers, rows, highlight_col=None):
    table = ctk.CTkFrame(container, fg_color=theme.BG_CARD, corner_radius=10,
                          border_width=1, border_color=theme.BORDER_SOFT)
    table.pack(fill="x", pady=4, padx=4)
    for c, h in enumerate(headers):
        ctk.CTkLabel(table, text=h, font=theme.FONT_SUBTITLE, text_color=theme.TEXT_MAIN,
                     anchor="w").grid(row=0, column=c, sticky="w", padx=8, pady=(8, 4))
    for r, vals in enumerate(rows, start=1):
        bg = theme.BG_MAIN
        if highlight_col is not None:
            v = str(vals[highlight_col])
            bg = theme.ACCENT_MINT if v.startswith("일치") else (theme.ACCENT_CORAL if v == "불일치" else theme.ACCENT_PEACH)
        for c, v in enumerate(vals):
            ctk.CTkLabel(table, text=str(v), font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN, fg_color=bg,
                         corner_radius=4, anchor="e" if isinstance(v, str) and v[:1].isdigit() or str(v)[:1] in "(-" else "w",
                         wraplength=320).grid(row=r, column=c, sticky="ew", padx=2, pady=1, ipady=3, ipadx=4)
    for c in range(len(headers)):
        table.grid_columnconfigure(c, weight=1)


def render_footing(container, data):
    """감사보고서 정밀 풋팅 결과 - 영역별 요약 + 예외 목록 (전체 내역은 Excel 시트)."""
    summary = data.get("footing_summary")
    rep = data.get("footing")
    if not summary or rep is None:
        empty_note(container, "정밀 풋팅 결과가 없습니다 (보고서종류 '감사'에서 수행).")
        return
    from .rules.audit_footing import exceptions
    section_title(container, "정밀 풋팅 요약 (재무제표 본문 / 재무제표간 / 주석 표 / 재무제표↔주석 / 본문 서술금액 / 특수검증)")
    tot = sum(a["total"] for a in summary)
    bad = sum(a["mismatch"] for a in summary)
    other = sum(a["rounding"] + a["other"] for a in summary)
    row = ctk.CTkFrame(container, fg_color="transparent")
    row.pack(fill="x", padx=4, pady=(0, 6))
    badge(row, f"검증 {tot:,}건", theme.ACCENT_SKY).pack(side="left", padx=4)
    badge(row, f"불일치 {bad}건", theme.ACCENT_CORAL if bad else theme.ACCENT_MINT).pack(side="left", padx=4)
    badge(row, f"단수차이·확인필요 {other}건", theme.ACCENT_PEACH).pack(side="left", padx=4)
    _simple_table(container, ["검증영역", "건수", "일치", "단수차이", "불일치", "기타"],
                  [[a["area"], a["total"], a["ok"], a["rounding"], a["mismatch"], a["other"]] for a in summary])
    for e in data.get("footing_errors") or []:
        empty_note(container, f"[엔진 오류] {e}")
    ex = exceptions(rep)
    section_title(container, f"예외 목록 {len(ex)}건 (불일치·단수차이·부호/표기 확인·미발견)")
    if not ex:
        empty_note(container, "예외 없음 - 모든 검증 항목이 일치합니다.")
        return
    _simple_table(container, ["결과", "영역", "주석/재무제표", "p.", "항목", "보고", "비교"],
                  [[e[7], e[0], e[1], e[2], e[3], _fmt(e[5]) if isinstance(e[5], (int, float)) else "-",
                    _fmt(e[6]) if isinstance(e[6], (int, float)) else "-"] for e in ex[:80]], highlight_col=0)
    if len(ex) > 80:
        empty_note(container, f"외 {len(ex) - 80}건 - 자동 저장 Excel의 '풋팅예외' 시트에서 전체 확인")
