"""Excel 기반 정밀 검증 패널 - fin-review-toolkit(dycmqk02-hub/fin-review-toolkit)의
GUI를 FSS_Review_Program 메인 탭 하나로 이식한 것. 합계·소계·총계 검증 / 대사검증
(재무제표간·주석간) / 연결-별도 비교를 Excel 템플릿 기반으로 수행한다.

원본과 달리:
- "파일 열기" 버튼을 없애고 [검증 실행]이 필요 시 자동으로 파일을 불러오도록 통합했다
  (아직 불러온 파일이 없으면 검증 실행 시 선택창이 뜨고, 이미 불러온 상태라면 매번
  디스크에서 새로 읽어들여 Excel에서 방금 수정한 내용을 그대로 반영한다).
- "검토 결과 내보내기" 버튼을 없애고, [검증 실행] 직후 회사명+기준년월로 자동 생성한
  파일명으로 다운로드 폴더에 곧바로 저장한다(저장 위치를 묻지 않음).
"""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import openpyxl

from . import theme
from . import render_helpers as rh
from .rules import excel_review_engine as engine

_TAB_DESCRIPTIONS = {
    "합계검증": (
        "각 시트(별도/연결 × BS/IS/CF/SOCE/주석)에서 '세부' 항목의 합이 '소계'와, "
        "'소계'(+누적된 이전 소계)의 합이 '합계'와 실제로 일치하는지 재계산합니다. "
        "재무제표 본문 안에서 완결되는 산술 검증입니다."
    ),
    "대사검증": (
        "Excel '대사규칙' 시트에 등록한 규칙대로, 서로 다른 시트에 있지만 값이 같아야 하는 "
        "두 항목을 비교합니다. 재무제표간 대사(예: 현금흐름표 기말현금 = 재무상태표 "
        "현금및현금성자산, 자본변동표 반기순이익 = 손익계산서 반기순이익)와 주석간 대사"
        "(예: 금융상품 범주별 분류표의 기타채권 = 개별 명세 주석의 기타채권 합계 - "
        "재무제표 본문과는 무관하게 주석끼리만 비교)를 모두 같은 방식으로 처리하며, "
        "어느 쪽인지는 등록한 규칙의 시트 조합에 따라 결정됩니다."
    ),
    "연결-별도 비교": (
        "별도/연결 시트에서 이름이 같은 계정과목을 자동으로 찾아 금액과 차이를 나열합니다. "
        "차이가 있다고 오류는 아니며(종속기업 실적 반영·내부거래 제거 등으로 정상적으로 "
        "차이가 남), 그 차이가 공시된 연결조정 내역으로 설명되는지 확인할 검토포인트 "
        "후보 목록입니다."
    ),
    "요약": "전체 검증 결과 통계와 불일치 건수, 그리고 자동화 대상이 아닌 정성적 검토포인트 체크리스트입니다.",
}


class ExcelReviewPanel:
    def __init__(self, parent):
        self.parent = parent
        self.wb = None
        self.excel_path = None
        self.sum_results = []
        self.recon_results = []
        self.compare_results = []

        self.root = ctk.CTkFrame(parent, fg_color="transparent")
        self.root.pack(fill="both", expand=True)

        self._build_toolbar()
        self._build_tabs()

    # ---------------------------------------------------------------- 상단 툴바
    def _build_toolbar(self):
        bar = ctk.CTkFrame(self.root, fg_color=theme.BG_CARD, corner_radius=12,
                            border_width=1, border_color=theme.BORDER_SOFT)
        bar.pack(fill="x", padx=4, pady=(4, 10))

        row1 = ctk.CTkFrame(bar, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkButton(row1, text="① PDF 불러오기(자동 채움)", corner_radius=8,
                      fg_color=theme.ACCENT_SKY, hover_color=theme.ACCENT_SKY_DARK,
                      text_color=theme.TEXT_MAIN, command=self._on_import_pdf).pack(side="left", padx=(0, 6))
        ctk.CTkButton(row1, text="② 템플릿 직접 생성", corner_radius=8,
                      fg_color=theme.BG_SIDEBAR, hover_color=theme.BORDER_SOFT,
                      text_color=theme.TEXT_MAIN, command=self._on_create_template).pack(side="left", padx=6)
        ctk.CTkButton(row1, text="③ 검증 실행 (완료 시 자동 저장)", corner_radius=8,
                      fg_color=theme.ACCENT_PRIMARY, hover_color=theme.ACCENT_PRIMARY_HOVER,
                      text_color=theme.TEXT_ON_ACCENT, command=self._on_run_verification).pack(side="left", padx=6)

        self.file_label = ctk.CTkLabel(row1, text="불러온 파일 없음", font=theme.FONT_SMALL,
                                        text_color=theme.TEXT_SUB)
        self.file_label.pack(side="right", padx=4)

        row2 = ctk.CTkFrame(bar, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkLabel(row2, text="회사명", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB).pack(side="left")
        self.company_var = tk.StringVar(value="")
        ctk.CTkEntry(row2, textvariable=self.company_var, width=140,
                     placeholder_text="예: OO전자").pack(side="left", padx=(4, 16))
        ctk.CTkLabel(row2, text="기준년월", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB).pack(side="left")
        self.period_var = tk.StringVar(value="")
        ctk.CTkEntry(row2, textvariable=self.period_var, width=80,
                     placeholder_text="예: 2612").pack(side="left", padx=(4, 16))
        ctk.CTkLabel(row2, text="합계검증 허용오차(원)", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(side="left")
        self.tol_var = tk.StringVar(value="1")
        ctk.CTkEntry(row2, textvariable=self.tol_var, width=60).pack(side="left", padx=(4, 16))
        ctk.CTkLabel(row2, text="→ [③ 검증 실행] 완료 시 '회사명+기준년월.xlsx' 파일로 다운로드 폴더에 자동 저장됩니다.",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_SUB).pack(side="left")

    # ---------------------------------------------------------------- 결과 탭
    def _build_tabs(self):
        self.tabview = ctk.CTkTabview(
            self.root, fg_color=theme.BG_CARD, segmented_button_fg_color=theme.BG_SIDEBAR,
            segmented_button_selected_color=theme.ACCENT_PRIMARY,
            segmented_button_selected_hover_color=theme.ACCENT_PRIMARY_HOVER,
            segmented_button_unselected_color=theme.BG_SIDEBAR,
            text_color=theme.TEXT_MAIN, corner_radius=14,
        )
        self.tabview.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self.result_frames = {}
        for name in ("합계검증", "대사검증", "연결-별도 비교", "요약"):
            self.tabview.add(name)
            frame = ctk.CTkScrollableFrame(self.tabview.tab(name), fg_color="transparent")
            frame.pack(fill="both", expand=True)
            self.result_frames[name] = frame
            desc = ctk.CTkLabel(frame, text=_TAB_DESCRIPTIONS[name], font=theme.FONT_SMALL,
                                 text_color=theme.TEXT_SUB, anchor="w", justify="left", wraplength=900)
            desc.pack(fill="x", padx=8, pady=(4, 10))
            rh.empty_note(frame, "[③ 검증 실행]을 누르면 결과가 여기에 표시됩니다.")

    # ---------------------------------------------------------------- 파일 로드
    def _ensure_loaded(self) -> bool:
        """아직 불러온 파일이 없으면 선택창을 띄운다. 있으면 디스크에서 새로 읽어
        Excel에서 방금 수정한 내용을 그대로 반영한다(재무제표는 초안이라 반드시
        검토·수정한 뒤 검증하는 것이 정상 흐름이므로)."""
        if self.excel_path is None:
            path = filedialog.askopenfilename(
                title="검토용 Excel 파일 선택 (① PDF 불러오기 또는 ② 템플릿 생성으로 만든 파일)",
                filetypes=[("Excel 파일", "*.xlsx;*.xlsm")],
            )
            if not path:
                return False
            self.excel_path = path
        try:
            self.wb = openpyxl.load_workbook(self.excel_path, data_only=True)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("오류", f"파일을 열 수 없습니다:\n{self.excel_path}\n\n{e}")
            self.excel_path = None
            return False
        self.file_label.configure(text=f"불러온 파일: {os.path.basename(self.excel_path)}")
        return True

    # ---------------------------------------------------------------- 버튼 동작
    def _on_import_pdf(self):
        if engine.pdfplumber is None:
            messagebox.showerror("안내", "PDF 불러오기 기능을 사용하려면 pdfplumber 패키지가 필요합니다.")
            return
        sep_path = filedialog.askopenfilename(
            title="별도재무제표 PDF 선택 (없으면 취소를 누르세요)", filetypes=[("PDF 파일", "*.pdf")])
        con_path = filedialog.askopenfilename(
            title="연결재무제표 PDF 선택 (없으면 취소를 누르세요)", filetypes=[("PDF 파일", "*.pdf")])
        if not sep_path and not con_path:
            return
        try:
            wb, counts = engine.build_workbook_from_pdfs(sep_path, con_path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("오류", f"PDF 자동 추출 중 오류가 발생했습니다:\n{e}")
            return

        default_name = self._auto_basename("review_from_pdf") + ".xlsx"
        save_path = filedialog.asksaveasfilename(
            title="자동 추출된 검토용 Excel 저장 (저장 후 열어서 원문과 대조·수정하십시오)",
            defaultextension=".xlsx", initialfile=default_name, filetypes=[("Excel 파일", "*.xlsx")],
        )
        if not save_path:
            return
        try:
            wb.save(save_path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("오류", f"저장 실패:\n{e}")
            return

        self.excel_path = save_path
        self._ensure_loaded()
        summary = "\n".join(f"  - {k}: {v}건" for k, v in counts.items()) or "  (추출된 항목 없음)"
        messagebox.showwarning(
            "PDF 자동 추출 완료 - 검토 필수",
            "재무상태표·손익계산서·현금흐름표 본문을 PDF에서 자동으로 읽어 Excel에 채웠습니다.\n\n"
            f"{summary}\n\n"
            "⚠️ 자동 추출은 참고용입니다. [③ 검증 실행] 전에 저장된 파일을 열어 반드시 확인하세요:\n"
            "  · 계정과목명/금액이 실제 PDF와 일치하는지 (각 행 '비고'에 원문 줄을 함께 넣어두었습니다)\n"
            "  · 구분(세부/소계/합계) 분류가 올바른지\n"
            "  · 자본변동표(SOCE)와 주석은 자동 추출되지 않으므로 직접 입력해야 합니다\n\n"
            f"저장 위치: {save_path}\n\n"
            "수정을 마쳤으면 [③ 검증 실행]을 누르세요 - 저장한 파일을 다시 여는 절차 없이 "
            "그대로 최신 내용을 읽어 검증합니다.",
        )

    def _on_create_template(self):
        default_name = self._auto_basename("review_template") + ".xlsx"
        path = filedialog.asksaveasfilename(
            title="템플릿 저장 위치", defaultextension=".xlsx",
            initialfile=default_name, filetypes=[("Excel 파일", "*.xlsx")],
        )
        if not path:
            return
        try:
            engine.create_template(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("오류", f"템플릿 생성 실패:\n{e}")
            return
        self.excel_path = path
        messagebox.showinfo("완료", f"템플릿을 생성했습니다:\n{path}\n\n"
                                    "Excel에서 열어 재무제표 숫자를 채운 뒤 [③ 검증 실행]을 누르세요.")

    def _on_run_verification(self):
        if not self._ensure_loaded():
            return
        try:
            tolerance = engine.to_number(self.tol_var.get())
            if tolerance is None:
                tolerance = 1
            self.sum_results = engine.run_sum_verification(self.wb, tolerance)
            lookup = engine.build_lookup(self.wb)
            self.recon_results = engine.run_recon_verification(self.wb, lookup)
            self.compare_results = engine.run_sep_con_compare(self.wb)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("오류", f"검증 중 오류가 발생했습니다:\n{e}")
            return

        self._render_all()

        company = self.company_var.get().strip()
        period = self.period_var.get().strip()
        if not company or not period:
            messagebox.showwarning(
                "안내", "결과는 표시했지만 자동 저장은 건너뛰었습니다.\n"
                        "회사명과 기준년월(예: 2612)을 입력하면 검증 실행 시 결과가\n"
                        "'회사명+기준년월.xlsx' 파일로 다운로드 폴더에 자동 저장됩니다.")
            return

        save_path = self._auto_save_report(company, period)
        if save_path:
            messagebox.showinfo("검증 완료", f"검증 결과를 저장했습니다:\n{save_path}")

    def _auto_basename(self, fallback: str) -> str:
        company = self.company_var.get().strip()
        period = self.period_var.get().strip()
        if company and period:
            return self._sanitize_filename(f"{company}{period}")
        return fallback

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        return "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "검토결과"

    def _auto_save_report(self, company: str, period: str) -> str | None:
        filename = self._sanitize_filename(f"{company}{period}") + ".xlsx"
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        try:
            os.makedirs(downloads, exist_ok=True)
            save_path = os.path.join(downloads, filename)
            wb = engine.build_report_workbook(self.excel_path, self.sum_results,
                                               self.recon_results, self.compare_results,
                                               source_wb=self.wb, source_path=self.excel_path)
            wb.save(save_path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("오류", f"검토 결과 자동 저장에 실패했습니다:\n{e}")
            return None
        return save_path

    # ---------------------------------------------------------------- 결과 렌더링
    def _render_all(self):
        self._render_table("합계검증", self.sum_results,
                            ("시트", "구간", "계정과목", "구분", "표시값", "계산값", "차이", "결과"))
        self._render_table("대사검증", self.recon_results, ("검증명", "값1", "값2", "차이", "결과"))
        self._render_table("연결-별도 비교", self.compare_results,
                            ("구분표", "계정과목", "기간", "별도", "연결", "차이"), result_key=None)
        self._render_summary()

    def _render_table(self, tab_name, rows, columns, result_key="결과"):
        frame = self.result_frames[tab_name]
        rh.clear(frame)
        ctk.CTkLabel(frame, text=_TAB_DESCRIPTIONS[tab_name], font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB, anchor="w", justify="left",
                     wraplength=900).pack(fill="x", padx=8, pady=(4, 10))
        if not rows:
            rh.empty_note(frame, "결과가 없습니다.")
            return

        n_fail = sum(1 for r in rows if r.get(result_key) == "불일치") if result_key else \
            sum(1 for r in rows if (r.get("차이") or 0) != 0)
        rh.badge(frame, f"총 {len(rows)}건 · 불일치/차이 {n_fail}건",
                  theme.ACCENT_CORAL if n_fail else theme.ACCENT_MINT).pack(anchor="w", padx=8, pady=(0, 8))

        table = ctk.CTkFrame(frame, fg_color=theme.BG_CARD, corner_radius=10,
                              border_width=1, border_color=theme.BORDER_SOFT)
        table.pack(fill="x", padx=8, pady=4)
        for c, h in enumerate(columns):
            ctk.CTkLabel(table, text=h, font=theme.FONT_SUBTITLE, text_color=theme.TEXT_MAIN,
                         anchor="w").grid(row=0, column=c, sticky="w", padx=8, pady=(8, 4))

        for r, row in enumerate(rows[:300], start=1):
            if result_key:
                result = row.get(result_key)
                bg = {"불일치": theme.ACCENT_CORAL, "일치": theme.ACCENT_MINT,
                      "데이터없음": theme.BG_SIDEBAR}.get(result, theme.BG_MAIN)
            else:
                diff = row.get("차이")
                bg = theme.ACCENT_PEACH if (diff not in (None, 0)) else theme.BG_MAIN
            for c, col in enumerate(columns):
                v = row.get(col)
                if isinstance(v, (int, float)):
                    v = engine.fmt(v)
                ctk.CTkLabel(table, text=v if v is not None else "", font=theme.FONT_SMALL,
                             text_color=theme.TEXT_MAIN, fg_color=bg, corner_radius=4,
                             anchor="w" if col in ("시트", "계정과목", "검증명") else "e")\
                    .grid(row=r, column=c, sticky="ew", padx=2, pady=1, ipady=3, ipadx=4)
        table.grid_columnconfigure(0, weight=2)
        for c in range(1, len(columns)):
            table.grid_columnconfigure(c, weight=1)
        if len(rows) > 300:
            rh.empty_note(frame, f"외 {len(rows) - 300}건 더 있습니다 (자동 저장된 Excel에서 전체 확인 가능).")

    def _render_summary(self):
        frame = self.result_frames["요약"]
        rh.clear(frame)
        ctk.CTkLabel(frame, text=_TAB_DESCRIPTIONS["요약"], font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB, anchor="w", justify="left",
                     wraplength=900).pack(fill="x", padx=8, pady=(4, 10))
        lines = engine.summary_lines(self.excel_path, self.sum_results, self.recon_results, self.compare_results)
        ctk.CTkLabel(frame, text="\n".join(lines), font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                     anchor="w", justify="left", wraplength=900).pack(fill="x", padx=8, pady=4)
