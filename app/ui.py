"""보고서 Review프로그램 - 메인 GUI."""
import os
import re
import threading
import tkinter.filedialog as fd
import tkinter.messagebox as mb

import customtkinter as ctk

from . import theme, settings, render_helpers as rh
from .review_engine import run_review, REPORT_TYPE_CHOICES, FS_TYPE_CHOICES, ACCOUNTING_STANDARD_CHOICES
from .report_render import export_txt, export_docx
from .variance_export import export_variance_excel
from .settings_dialog import SettingsDialog

ctk.set_appearance_mode("light")

APP_TITLE = "보고서 Review프로그램"


def _parse_pm(text: str) -> float | None:
    s = (text or "").strip().replace(",", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def _bind_thousands_separator(entry: ctk.CTkEntry, var: ctk.StringVar) -> None:
    """숫자만 남기고 입력 즉시 천단위 콤마를 붙여주는 포맷터 (커서 위치도 보정)."""
    state = {"active": False}

    def on_write(*_args):
        if state["active"]:
            return
        raw = var.get()
        try:
            cursor = entry.index("insert")
        except Exception:
            cursor = len(raw)
        digits_before_cursor = len(re.sub(r"[^0-9]", "", raw[:cursor]))
        digits_only = re.sub(r"[^0-9]", "", raw)
        formatted = f"{int(digits_only):,}" if digits_only else ""
        if formatted == raw:
            return
        state["active"] = True
        var.set(formatted)
        new_cursor = len(formatted)
        count = 0
        for i, ch in enumerate(formatted):
            if ch.isdigit():
                count += 1
                if count == digits_before_cursor:
                    new_cursor = i + 1
                    break
        try:
            entry.icursor(new_cursor)
        except Exception:
            pass
        state["active"] = False

    var.trace_add("write", on_write)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1360x880")
        self.minsize(1150, 720)
        self.configure(fg_color=theme.BG_MAIN)

        self.settings = settings.load_settings()
        self.report_type = ctk.StringVar(value=self.settings.get("last_report_type", "분반기"))
        self.fs_type = ctk.StringVar(value=self.settings.get("last_fs_type", "연결"))
        self.accounting_standard = ctk.StringVar(value=self.settings.get("last_accounting_standard", "KIFRS"))
        self.pm_consol_var = ctk.StringVar(value=self.settings.get("last_pm_consol", ""))
        self.pm_separate_var = ctk.StringVar(value=self.settings.get("last_pm_separate", ""))

        self.main_pdf_path = None
        self.consol_pdf_path = None
        self.separate_pdf_path = None
        self.xbrl_source_path = None
        self.excel_review_path = None
        self.company_var = ctk.StringVar(value="")
        self.period_var = ctk.StringVar(value="")
        self.last_result = None

        self._build_layout()
        self._rebuild_file_section()

    # ---------------------------------------------------------------- layout
    def _build_layout(self):
        root = ctk.CTkFrame(self, fg_color=theme.BG_MAIN)
        root.pack(fill="both", expand=True)

        self.sidebar = ctk.CTkFrame(root, fg_color=theme.BG_SIDEBAR, width=340, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.main_area = ctk.CTkFrame(root, fg_color=theme.BG_MAIN, corner_radius=0)
        self.main_area.pack(side="left", fill="both", expand=True)

        self._build_sidebar()
        self._build_main_area()

    def _build_sidebar(self):
        s = ctk.CTkScrollableFrame(self.sidebar, fg_color=theme.BG_SIDEBAR, scrollbar_button_color=theme.BORDER_SOFT)
        s.pack(fill="both", expand=True)

        ctk.CTkLabel(s, text=APP_TITLE, font=theme.FONT_TITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(fill="x", padx=22, pady=(26, 2))
        ctk.CTkLabel(s, text="Big4 품질관리실 사전리뷰 보조도구", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB, anchor="w").pack(fill="x", padx=22, pady=(0, 20))

        # 옵션1: 보고서 종류
        ctk.CTkLabel(s, text="① 보고서 종류", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(fill="x", padx=22, pady=(6, 6))
        opt1 = ctk.CTkSegmentedButton(
            s, values=REPORT_TYPE_CHOICES, variable=self.report_type,
            fg_color=theme.BG_CARD, selected_color=theme.ACCENT_PRIMARY,
            selected_hover_color=theme.ACCENT_PRIMARY_HOVER, unselected_color=theme.BG_CARD,
            unselected_hover_color=theme.BORDER_SOFT, text_color=theme.TEXT_MAIN,
            corner_radius=10,
            command=lambda _v: self._rebuild_file_section(),
        )
        opt1.pack(fill="x", padx=22, pady=(0, 4))
        self.audit_hint = ctk.CTkLabel(
            s, text="※ 감사보고서 리뷰는 추후 지원 예정입니다 (현재는 페이지 수만 확인).",
            font=theme.FONT_SMALL, text_color=theme.ACCENT_PEACH_DARK, anchor="w", justify="left",
            wraplength=252,
        )
        self._refresh_audit_hint()

        # 옵션2: 재무제표 구분
        ctk.CTkLabel(s, text="② 재무제표 구분", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(fill="x", padx=22, pady=(14, 6))
        opt2 = ctk.CTkSegmentedButton(
            s, values=FS_TYPE_CHOICES, variable=self.fs_type,
            fg_color=theme.BG_CARD, selected_color=theme.ACCENT_PRIMARY,
            selected_hover_color=theme.ACCENT_PRIMARY_HOVER, unselected_color=theme.BG_CARD,
            unselected_hover_color=theme.BORDER_SOFT, text_color=theme.TEXT_MAIN,
            text_color_disabled=theme.TEXT_SUB, corner_radius=10,
            command=lambda _v: self._rebuild_file_section(),
        )
        opt2.pack(fill="x", padx=22, pady=(0, 18))

        # 옵션3: 적용 회계처리기준
        ctk.CTkLabel(s, text="③ 적용 회계처리기준", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(fill="x", padx=22, pady=(0, 6))
        opt3 = ctk.CTkSegmentedButton(
            s, values=ACCOUNTING_STANDARD_CHOICES, variable=self.accounting_standard,
            fg_color=theme.BG_CARD, selected_color=theme.ACCENT_SKY_DARK,
            selected_hover_color=theme.ACCENT_SKY_DARK, unselected_color=theme.BG_CARD,
            unselected_hover_color=theme.BORDER_SOFT, text_color=theme.TEXT_MAIN,
            corner_radius=10,
        )
        opt3.pack(fill="x", padx=22, pady=(0, 18))

        # 옵션4/5: PM (증감분석표 금액차이 음영 기준)
        ctk.CTkLabel(s, text="④⑤ 증감분석 금액차이 기준(PM)", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(fill="x", padx=22, pady=(0, 4))
        pm_row = ctk.CTkFrame(s, fg_color="transparent")
        pm_row.pack(fill="x", padx=22, pady=(0, 4))
        pm_col1 = ctk.CTkFrame(pm_row, fg_color="transparent")
        pm_col1.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkLabel(pm_col1, text="④ 연결 PM", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w").pack(fill="x")
        pm_entry1 = ctk.CTkEntry(pm_col1, textvariable=self.pm_consol_var, corner_radius=8,
                                  placeholder_text="예: 500,000,000")
        pm_entry1.pack(fill="x")
        _bind_thousands_separator(pm_entry1, self.pm_consol_var)
        pm_col2 = ctk.CTkFrame(pm_row, fg_color="transparent")
        pm_col2.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ctk.CTkLabel(pm_col2, text="⑤ 별도 PM", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w").pack(fill="x")
        pm_entry2 = ctk.CTkEntry(pm_col2, textvariable=self.pm_separate_var, corner_radius=8,
                                  placeholder_text="예: 400,000,000")
        pm_entry2.pack(fill="x")
        _bind_thousands_separator(pm_entry2, self.pm_separate_var)
        ctk.CTkLabel(
            s, text="개별재무제표는 ④(연결PM)값을 사용합니다.\n"
                    "미입력 시 금액차이 음영은 표시되지 않으며,\n"
                    "증감률 5% 음영은 항상 적용됩니다. (단위는\n"
                    "재무제표 표시단위와 동일하게 입력하십시오)",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, anchor="w", justify="left",
            wraplength=268,
        ).pack(fill="x", padx=22, pady=(2, 18))

        # 파일 업로드 영역 (동적)
        self.file_section_title = ctk.CTkLabel(s, text="⑥ 보고서 PDF 업로드", font=theme.FONT_SUBTITLE,
                                                text_color=theme.TEXT_MAIN, anchor="w")
        self.file_section_title.pack(fill="x", padx=22, pady=(0, 6))
        self.file_section = ctk.CTkFrame(s, fg_color="transparent")
        self.file_section.pack(fill="x", padx=22, pady=(0, 18))

        # 옵션7: XBRL 데이터 (선택 - 증감분석 정밀도 향상)
        ctk.CTkLabel(s, text="⑦ XBRL 데이터 (선택, 증감분석 정밀화)", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(fill="x", padx=22, pady=(0, 4))
        xbrl_frame = ctk.CTkFrame(s, fg_color=theme.BG_CARD, corner_radius=10,
                                   border_width=1, border_color=theme.BORDER_SOFT)
        xbrl_frame.pack(fill="x", padx=22, pady=(0, 4))
        self.xbrl_path_label = ctk.CTkLabel(xbrl_frame, text="선택 안 함 (미선택 시 PDF 표 휴리스틱 사용)",
                                             font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, anchor="w",
                                             wraplength=230, justify="left")
        self.xbrl_path_label.pack(fill="x", padx=10, pady=(8, 4))
        xbrl_btn_row = ctk.CTkFrame(xbrl_frame, fg_color="transparent")
        xbrl_btn_row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkButton(xbrl_btn_row, text="ZIP 선택", width=80, corner_radius=8,
                      fg_color=theme.ACCENT_SKY, hover_color=theme.ACCENT_SKY_DARK,
                      text_color=theme.TEXT_MAIN, command=self._browse_xbrl_zip).pack(side="left")
        ctk.CTkButton(xbrl_btn_row, text="폴더 선택", width=80, corner_radius=8,
                      fg_color=theme.ACCENT_SKY, hover_color=theme.ACCENT_SKY_DARK,
                      text_color=theme.TEXT_MAIN, command=self._browse_xbrl_folder).pack(side="left", padx=(6, 0))
        ctk.CTkButton(xbrl_btn_row, text="지우기", width=60, corner_radius=8,
                      fg_color=theme.BG_SIDEBAR, hover_color=theme.BORDER_SOFT,
                      text_color=theme.TEXT_MAIN, command=self._clear_xbrl).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(
            s, text="DART 원문XBRL(zip 또는 압축 해제한 폴더)을\n"
                    "넣으면\n"
                    "재무상태표/손익계산서/자본변동표/현금흐름표\n"
                    "증감분석을 PDF 표 인식 대신\n"
                    "XBRL 원본 수치로 정확하게 산출합니다.\n"
                    "연결·별도 값이 같은 XBRL 안에 모두\n"
                    "있으므로 1개만 올리면 됩니다.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, anchor="w", justify="left",
            wraplength=268,
        ).pack(fill="x", padx=22, pady=(2, 18))

        # 옵션8: Excel 정밀검증 (선택) - fin-review-toolkit 이식. 사람이 직접 검토·수정한
        # Excel 값을 기준으로 합계검증/대사검증/연결-별도비교를 수행해, 위 ⑥ PDF/⑦ XBRL 기반
        # 자동 검증 결과와 같은 탭(합계검증/연결 vs 별도)에 함께 표시된다. ⑥에서 이미 올린
        # PDF를 그대로 재사용하므로 여기서 PDF를 다시 올릴 필요가 없다.
        ctk.CTkLabel(s, text="⑧ Excel 정밀검증 (선택)", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(fill="x", padx=22, pady=(0, 4))
        excel_frame = ctk.CTkFrame(s, fg_color=theme.BG_CARD, corner_radius=10,
                                    border_width=1, border_color=theme.BORDER_SOFT)
        excel_frame.pack(fill="x", padx=22, pady=(0, 4))

        name_row = ctk.CTkFrame(excel_frame, fg_color="transparent")
        name_row.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(name_row, text="회사명", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB).pack(side="left")
        ctk.CTkEntry(name_row, textvariable=self.company_var, width=90,
                     placeholder_text="예: OO전자").pack(side="left", padx=(4, 10))
        ctk.CTkLabel(name_row, text="기준년월", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB).pack(side="left")
        ctk.CTkEntry(name_row, textvariable=self.period_var, width=60,
                     placeholder_text="2612").pack(side="left", padx=(4, 0))

        self.excel_status_label = ctk.CTkLabel(excel_frame, text="선택 안 함 (미선택 시 Excel 정밀검증 생략)",
                                                font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, anchor="w",
                                                wraplength=230, justify="left")
        self.excel_status_label.pack(fill="x", padx=10, pady=(0, 4))

        excel_btn_row1 = ctk.CTkFrame(excel_frame, fg_color="transparent")
        excel_btn_row1.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(excel_btn_row1, text="PDF로 초안 생성", width=104, corner_radius=8,
                      fg_color=theme.ACCENT_SKY, hover_color=theme.ACCENT_SKY_DARK,
                      text_color=theme.TEXT_MAIN, command=self._on_generate_excel_draft).pack(side="left")
        ctk.CTkButton(excel_btn_row1, text="빈 템플릿", width=70, corner_radius=8,
                      fg_color=theme.ACCENT_SKY, hover_color=theme.ACCENT_SKY_DARK,
                      text_color=theme.TEXT_MAIN, command=self._on_create_excel_template).pack(side="left", padx=(6, 0))
        excel_btn_row2 = ctk.CTkFrame(excel_frame, fg_color="transparent")
        excel_btn_row2.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkButton(excel_btn_row2, text="검토 완료한 파일 선택", width=140, corner_radius=8,
                      fg_color=theme.BG_SIDEBAR, hover_color=theme.BORDER_SOFT,
                      text_color=theme.TEXT_MAIN, command=self._on_browse_excel_file).pack(side="left")
        ctk.CTkButton(excel_btn_row2, text="지우기", width=60, corner_radius=8,
                      fg_color=theme.BG_SIDEBAR, hover_color=theme.BORDER_SOFT,
                      text_color=theme.TEXT_MAIN, command=self._clear_excel_review).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(
            s, text="PDF로 초안을 만들면(위 ⑥에서 이미 올린 PDF 재사용) 저장 후 열어서\n"
                    "원문과 대조·수정해야 합니다. 수정을 마친 뒤(또는 이미 검토가\n"
                    "끝난 파일이 있으면) [▶ 리뷰 시작]을 누르면 그 Excel 내용을 매번\n"
                    "새로 읽어 합계검증/대사검증/연결-별도비교에 반영합니다. 회사명·\n"
                    "기준년월을 입력해 두면 완료 시 '회사명기준년월.xlsx'로 다운로드\n"
                    "폴더에 검증 결과가 자동 저장됩니다(차이만 모은 하이퍼링크 시트 포함).",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, anchor="w", justify="left",
            wraplength=268,
        ).pack(fill="x", padx=22, pady=(2, 18))

        # 설정 / 실행 버튼
        ctk.CTkButton(s, text="⚙ 참조자료 폴더 설정", corner_radius=10, height=38,
                      fg_color=theme.BG_CARD, hover_color=theme.BORDER_SOFT,
                      text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER_SOFT,
                      command=self._open_settings).pack(fill="x", padx=22, pady=(4, 10))

        self.run_btn = ctk.CTkButton(
            s, text="▶  리뷰 시작", corner_radius=12, height=46, font=theme.FONT_SUBTITLE,
            fg_color=theme.ACCENT_PRIMARY, hover_color=theme.ACCENT_PRIMARY_HOVER,
            text_color=theme.TEXT_ON_ACCENT, command=self._start_review,
        )
        self.run_btn.pack(fill="x", padx=22, pady=(6, 10))

        self.progress = ctk.CTkProgressBar(s, mode="determinate", fg_color=theme.BORDER_SOFT,
                                            progress_color=theme.ACCENT_PRIMARY)
        self.progress.set(0)
        self.status_label = ctk.CTkLabel(s, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                                          anchor="w", wraplength=252, justify="left")
        self.status_label.pack(fill="x", padx=22, pady=(0, 4))

        disclaimer = ("본 프로그램은 규칙·키워드 기반 1차 스크리닝 도구입니다.\n"
                      "합산검증, 문단46 필수기재사항, 회계처리변경 키워드, 증감분석 등을\n"
                      "자동 점검하되, 실질적 회계 판단·최종 검토의견은\n반드시 검토자가 직접 수행하십시오.")
        ctk.CTkLabel(s, text=disclaimer, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w", justify="left", wraplength=252).pack(fill="x", padx=22, pady=(20, 16))

    def _refresh_audit_hint(self):
        if self.report_type.get() == "감사":
            self.audit_hint.pack(fill="x", padx=22, pady=(0, 0))
        else:
            self.audit_hint.pack_forget()

    def _build_main_area(self):
        header = ctk.CTkFrame(self.main_area, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 8))
        ctk.CTkLabel(header, text="리뷰 결과", font=theme.FONT_TITLE, text_color=theme.TEXT_MAIN,
                     anchor="w").pack(side="left")
        self.export_txt_btn = ctk.CTkButton(header, text="TXT로 저장", width=110, corner_radius=10,
                                             fg_color=theme.ACCENT_MINT, hover_color=theme.ACCENT_MINT_DARK,
                                             text_color=theme.TEXT_MAIN, state="disabled",
                                             command=self._export_txt)
        self.export_txt_btn.pack(side="right", padx=(6, 0))
        self.export_docx_btn = ctk.CTkButton(header, text="DOCX로 저장", width=120, corner_radius=10,
                                              fg_color=theme.ACCENT_PEACH, hover_color=theme.ACCENT_PEACH_DARK,
                                              text_color=theme.TEXT_MAIN, state="disabled",
                                              command=self._export_docx)
        self.export_docx_btn.pack(side="right", padx=(6, 0))
        self.export_xlsx_btn = ctk.CTkButton(header, text="증감분석 Excel", width=130, corner_radius=10,
                                              fg_color=theme.ACCENT_SKY, hover_color=theme.ACCENT_SKY_DARK,
                                              text_color=theme.TEXT_MAIN, state="disabled",
                                              command=self._export_excel)
        self.export_xlsx_btn.pack(side="right", padx=(6, 0))

        self.tabview = ctk.CTkTabview(
            self.main_area, fg_color=theme.BG_MAIN,
            segmented_button_fg_color=theme.BG_SIDEBAR, segmented_button_selected_color=theme.ACCENT_PRIMARY,
            segmented_button_selected_hover_color=theme.ACCENT_PRIMARY_HOVER,
            segmented_button_unselected_color=theme.BG_SIDEBAR, text_color=theme.TEXT_MAIN,
            corner_radius=14,
        )
        self.tabview.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        self.tab_names = ["요약", "체크리스트", "숫자 스크리닝", "증감분석", "합계검증", "회계처리 변경", "참조자료", "연결 vs 별도"]
        for name in self.tab_names:
            self.tabview.add(name)

        self.scroll_frames = {}
        for name in self.tab_names:
            frame = ctk.CTkScrollableFrame(self.tabview.tab(name), fg_color="transparent")
            frame.pack(fill="both", expand=True)
            self.scroll_frames[name] = frame
            rh.empty_note(frame, "리뷰를 시작하면 결과가 여기에 표시됩니다.")

    # ------------------------------------------------------------ 파일업로드
    def _rebuild_file_section(self):
        self._refresh_audit_hint()
        for w in self.file_section.winfo_children():
            w.destroy()

        doc_word = "검토보고서" if self.report_type.get() == "분반기" else "감사보고서"
        self.file_section_title.configure(text=f"⑥ {doc_word} PDF 업로드")

        if self.fs_type.get() == "연결 vs 별도":
            self._file_row(self.file_section, f"연결재무제표 {doc_word} PDF", "consol")
            self._file_row(self.file_section, f"별도재무제표 {doc_word} PDF", "separate")
        else:
            label = f"{self.fs_type.get()}재무제표 {doc_word} PDF"
            self._file_row(self.file_section, label, "main")

    def _file_row(self, parent, label, key):
        frame = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=10,
                              border_width=1, border_color=theme.BORDER_SOFT)
        frame.pack(fill="x", pady=5)
        ctk.CTkLabel(frame, text=label, font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                     anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        path_label = ctk.CTkLabel(frame, text="선택된 파일 없음", font=theme.FONT_SMALL,
                                   text_color=theme.TEXT_SUB, anchor="w")
        path_label.pack(fill="x", padx=12, pady=(0, 6))

        def browse():
            path = fd.askopenfilename(title=label, filetypes=[("PDF 파일", "*.pdf")])
            if not path:
                return
            setattr(self, f"{key}_pdf_path", path)
            path_label.configure(text=os.path.basename(path), text_color=theme.ACCENT_MINT_DARK)

        ctk.CTkButton(frame, text="파일 선택", corner_radius=8, height=30, fg_color=theme.ACCENT_SKY,
                      hover_color=theme.ACCENT_SKY_DARK, text_color=theme.TEXT_MAIN,
                      command=browse).pack(padx=12, pady=(0, 10), anchor="w")

    # -------------------------------------------------------------- XBRL
    def _browse_xbrl_zip(self):
        path = fd.askopenfilename(title="XBRL ZIP 파일 선택", filetypes=[("ZIP 파일", "*.zip")])
        if not path:
            return
        self.xbrl_source_path = path
        self.xbrl_path_label.configure(text=f"ZIP: {os.path.basename(path)}", text_color=theme.ACCENT_MINT_DARK)

    def _browse_xbrl_folder(self):
        path = fd.askdirectory(title="XBRL 폴더 선택")
        if not path:
            return
        self.xbrl_source_path = path
        self.xbrl_path_label.configure(text=f"폴더: {os.path.basename(path) or path}",
                                        text_color=theme.ACCENT_MINT_DARK)

    def _clear_xbrl(self):
        self.xbrl_source_path = None
        self.xbrl_path_label.configure(text="선택 안 함 (미선택 시 PDF 표 휴리스틱 사용)",
                                        text_color=theme.TEXT_SUB)

    # ------------------------------------------------------------- Excel 정밀검증
    def _excel_default_basename(self) -> str:
        company = self.company_var.get().strip()
        period = self.period_var.get().strip()
        if company and period:
            safe = "".join(c for c in f"{company}{period}" if c not in '\\/:*?"<>|').strip()
            if safe:
                return safe
        return "review"

    def _refresh_excel_status(self):
        if self.excel_review_path:
            self.excel_status_label.configure(text=f"파일: {os.path.basename(self.excel_review_path)}",
                                               text_color=theme.ACCENT_MINT_DARK)
        else:
            self.excel_status_label.configure(text="선택 안 함 (미선택 시 Excel 정밀검증 생략)",
                                               text_color=theme.TEXT_SUB)

    def _on_generate_excel_draft(self):
        if self.fs_type.get() == "연결 vs 별도":
            sep_path, con_path = self.separate_pdf_path, self.consol_pdf_path
        elif self.fs_type.get() == "연결":
            sep_path, con_path = None, self.main_pdf_path
        else:  # 별도/개별
            sep_path, con_path = self.main_pdf_path, None
        if not sep_path and not con_path:
            mb.showwarning("파일 필요", "먼저 사이드바 ⑥에서 검토보고서 PDF를 선택해 주세요.\n"
                                       "(같은 PDF를 여기서 다시 올릴 필요 없이 ⑥의 파일을 그대로 사용합니다)")
            return
        from .rules import excel_review_engine as xlengine
        if xlengine.pdfplumber is None:
            mb.showerror("안내", "PDF 자동 채움 기능을 사용하려면 pdfplumber 패키지가 필요합니다.")
            return
        try:
            wb, counts = xlengine.build_workbook_from_pdfs(sep_path, con_path)
        except Exception as e:  # noqa: BLE001
            mb.showerror("오류", f"PDF 자동 추출 중 오류가 발생했습니다:\n{e}")
            return

        save_path = fd.asksaveasfilename(
            title="자동 추출된 검토용 Excel 저장 (저장 후 열어서 원문과 대조·수정하십시오)",
            defaultextension=".xlsx", initialfile=self._excel_default_basename() + ".xlsx",
            filetypes=[("Excel 파일", "*.xlsx")],
        )
        if not save_path:
            return
        try:
            wb.save(save_path)
        except Exception as e:  # noqa: BLE001
            mb.showerror("오류", f"저장 실패:\n{e}")
            return

        self.excel_review_path = save_path
        self._refresh_excel_status()
        summary = "\n".join(f"  - {k}: {v}건" for k, v in counts.items()) or "  (추출된 항목 없음)"
        mb.showwarning(
            "PDF 자동 추출 완료 - 검토 필수",
            "재무상태표·손익계산서·현금흐름표 본문을 PDF에서 자동으로 읽어 Excel에 채웠습니다.\n\n"
            f"{summary}\n\n"
            "⚠️ 자동 추출은 참고용입니다. [▶ 리뷰 시작] 전에 저장된 파일을 열어 반드시 확인하세요:\n"
            "  · 계정과목명/금액이 실제 PDF와 일치하는지 (각 행 '비고'에 원문 줄을 함께 넣어두었습니다)\n"
            "  · 구분(세부/소계/합계) 분류가 올바른지\n"
            "  · 자본변동표(SOCE)와 주석은 자동 추출되지 않으므로 직접 입력해야 합니다\n\n"
            f"저장 위치: {save_path}\n\n"
            "수정을 마쳤으면 [▶ 리뷰 시작]을 누르세요 - 저장한 파일을 다시 여는 절차 없이 "
            "그대로 최신 내용을 읽어 검증합니다.",
        )

    def _on_create_excel_template(self):
        from .rules import excel_review_engine as xlengine
        path = fd.asksaveasfilename(
            title="템플릿 저장 위치", defaultextension=".xlsx",
            initialfile=self._excel_default_basename() + "_template.xlsx", filetypes=[("Excel 파일", "*.xlsx")],
        )
        if not path:
            return
        try:
            xlengine.create_template(path)
        except Exception as e:  # noqa: BLE001
            mb.showerror("오류", f"템플릿 생성 실패:\n{e}")
            return
        self.excel_review_path = path
        self._refresh_excel_status()
        mb.showinfo("완료", f"템플릿을 생성했습니다:\n{path}\n\n"
                            "Excel에서 열어 재무제표 숫자를 채운 뒤 [▶ 리뷰 시작]을 누르세요.")

    def _on_browse_excel_file(self):
        path = fd.askopenfilename(title="검토 완료한 Excel 정밀검증 파일 선택",
                                   filetypes=[("Excel 파일", "*.xlsx;*.xlsm")])
        if not path:
            return
        self.excel_review_path = path
        self._refresh_excel_status()

    def _clear_excel_review(self):
        self.excel_review_path = None
        self._refresh_excel_status()

    # ------------------------------------------------------------------ 설정
    def _open_settings(self):
        def on_save(new_settings):
            self.settings = new_settings
            settings.save_settings(self.settings)

        SettingsDialog(self, self.settings, on_save)

    # --------------------------------------------------------------- 리뷰실행
    def _start_review(self):
        report_type = self.report_type.get()
        fs_type = self.fs_type.get()
        accounting_standard = self.accounting_standard.get()
        pm_consol = _parse_pm(self.pm_consol_var.get())
        pm_separate = _parse_pm(self.pm_separate_var.get())

        doc_word = "검토보고서" if report_type == "분반기" else "감사보고서"
        if fs_type == "연결 vs 별도":
            if not self.consol_pdf_path or not self.separate_pdf_path:
                mb.showwarning("파일 필요", f"연결·별도 {doc_word} PDF를 모두 선택해 주세요.")
                return
            files = {"consol": self.consol_pdf_path, "separate": self.separate_pdf_path}
        else:
            if not self.main_pdf_path:
                mb.showwarning("파일 필요", f"{doc_word} PDF를 선택해 주세요.")
                return
            files = {"main": self.main_pdf_path}

        self.settings["last_report_type"] = report_type
        self.settings["last_fs_type"] = fs_type
        self.settings["last_accounting_standard"] = accounting_standard
        self.settings["last_pm_consol"] = self.pm_consol_var.get().strip()
        self.settings["last_pm_separate"] = self.pm_separate_var.get().strip()
        settings.save_settings(self.settings)

        self.progress.pack(fill="x", padx=22, pady=(0, 6))
        self._set_progress_ui("검토 시작...", 0)

        def progress_cb(msg, percent):
            self.after(0, lambda: self._set_progress_ui(msg, percent))

        def worker():
            try:
                result = run_review(report_type, fs_type, accounting_standard, files, self.settings,
                                     pm_consol=pm_consol, pm_separate=pm_separate,
                                     xbrl_source=self.xbrl_source_path, excel_path=self.excel_review_path,
                                     company_name=self.company_var.get(), period=self.period_var.get(),
                                     progress_cb=progress_cb)
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda: self._on_review_error(e))
                return
            self.after(0, lambda: self._on_review_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _set_progress_ui(self, msg: str, percent: float):
        percent = max(0.0, min(100.0, percent))
        self.status_label.configure(text=msg)
        self.progress.set(percent / 100)
        color = theme.interpolate_color(theme.ACCENT_PRIMARY, theme.ACCENT_PRIMARY_DEEP, percent / 100)
        self.run_btn.configure(state="disabled", text=f"리뷰 중... {int(percent)}%",
                                fg_color=color, hover_color=color, text_color_disabled=theme.TEXT_ON_ACCENT)

    def _on_review_error(self, err: Exception):
        self.progress.pack_forget()
        self.progress.set(0)
        self.run_btn.configure(state="normal", text="▶  리뷰 시작",
                                fg_color=theme.ACCENT_PRIMARY, hover_color=theme.ACCENT_PRIMARY_HOVER)
        self.status_label.configure(text=f"오류: {err}")
        mb.showerror("리뷰 실패", f"PDF 분석 중 오류가 발생했습니다.\n\n{err}")

    def _on_review_done(self, result: dict):
        self.progress.pack_forget()
        self.run_btn.configure(state="normal", text="✓ 리뷰완료",
                                fg_color=theme.ACCENT_PRIMARY_DEEP, hover_color=theme.ACCENT_PRIMARY_DEEP,
                                text_color=theme.TEXT_ON_ACCENT)
        self.status_label.configure(text="완료되었습니다.")
        self.last_result = result
        self.export_txt_btn.configure(state="normal")
        self.export_docx_btn.configure(state="normal")
        self.export_xlsx_btn.configure(state="normal" if not result.get("not_supported") else "disabled")
        self._render_result(result)
        if result.get("excel_report_path"):
            mb.showinfo("Excel 정밀검증 결과 저장 완료",
                        f"합계검증/대사검증/연결-별도비교 결과를 저장했습니다:\n{result['excel_report_path']}\n\n"
                        "맨 왼쪽 '차이요약' 시트에서 하이퍼링크를 클릭하면 원본 Excel의 해당 셀로 이동합니다.")

    # -------------------------------------------------------------- 렌더링
    def _render_result(self, result: dict):
        for frame in self.scroll_frames.values():
            rh.clear(frame)

        top = ctk.CTkFrame(self.scroll_frames["요약"], fg_color="transparent")
        top.pack(fill="x", pady=(4, 12))
        rh.badge(top, f"보고서종류: {result['report_type']}", theme.ACCENT_PRIMARY, theme.TEXT_ON_ACCENT).pack(side="left", padx=4)
        rh.badge(top, f"재무제표구분: {result['fs_type']}", theme.ACCENT_PRIMARY, theme.TEXT_ON_ACCENT).pack(side="left", padx=4)
        rh.badge(top, f"적용기준: {result['accounting_standard']}", theme.ACCENT_SKY_DARK, theme.TEXT_ON_ACCENT).pack(side="left", padx=4)
        for src in result.get("ref_sources", []):
            rh.badge(top, f"{src['label']}: {src['status']}", theme.ref_source_color(src["label"])).pack(side="left", padx=4)

        if result.get("not_supported"):
            note = ctk.CTkFrame(self.scroll_frames["요약"], fg_color=theme.ACCENT_PEACH, corner_radius=12)
            note.pack(fill="x", pady=8, padx=4)
            ctk.CTkLabel(note, text=result.get("not_supported_note", ""), font=theme.FONT_BODY,
                         text_color=theme.TEXT_MAIN, justify="left", anchor="w",
                         wraplength=820).pack(padx=16, pady=14, anchor="w")
            for key, n in (result.get("page_counts") or {}).items():
                rh.badge(self.scroll_frames["요약"], f"{key}: {n if n is not None else '읽기 실패'}p",
                          theme.BG_SIDEBAR).pack(anchor="w", padx=4, pady=2)
            for name in self.tab_names[1:]:
                rh.empty_note(self.scroll_frames[name], "감사보고서 리뷰는 추후 지원 예정입니다.")
            return

        sections = result["sections"]
        is_dual = "consol_vs_sep" in sections

        # 요약 탭
        summary = self.scroll_frames["요약"]
        if is_dual:
            self._render_summary_doc(summary, "연결", sections["consol"])
            self._render_summary_doc(summary, "별도", sections["separate"])
        else:
            self._render_summary_doc(summary, result["fs_type"], sections["single"])

        # 체크리스트 탭
        checklist_tab = self.scroll_frames["체크리스트"]
        if is_dual:
            rh.doc_label_title(checklist_tab, "연결재무제표 검토보고서")
            rh.render_checklist(checklist_tab, sections["consol"]["checklist"])
            rh.render_opinion(checklist_tab, sections["consol"]["opinion"])
            rh.render_comparative(checklist_tab, sections["consol"]["comparative"])
            rh.doc_label_title(checklist_tab, "별도재무제표 검토보고서")
            rh.render_checklist(checklist_tab, sections["separate"]["checklist"])
            rh.render_opinion(checklist_tab, sections["separate"]["opinion"])
            rh.render_comparative(checklist_tab, sections["separate"]["comparative"])
        else:
            data = sections["single"]
            rh.render_checklist(checklist_tab, data["checklist"])
            rh.render_opinion(checklist_tab, data["opinion"])
            rh.render_comparative(checklist_tab, data["comparative"])

        # 숫자 스크리닝 탭
        num_tab = self.scroll_frames["숫자 스크리닝"]
        if is_dual:
            rh.doc_label_title(num_tab, "연결재무제표")
            rh.render_sum_check(num_tab, sections["consol"]["sum_check"])
            rh.render_cross_check(num_tab, sections["consol"]["cross_check"])
            rh.doc_label_title(num_tab, "별도재무제표")
            rh.render_sum_check(num_tab, sections["separate"]["sum_check"])
            rh.render_cross_check(num_tab, sections["separate"]["cross_check"])
        else:
            data = sections["single"]
            rh.render_sum_check(num_tab, data["sum_check"])
            rh.render_cross_check(num_tab, data["cross_check"])

        # 증감분석 탭
        var_tab = self.scroll_frames["증감분석"]
        if is_dual:
            rh.doc_label_title(var_tab, "연결재무제표")
            rh.render_variance_tables(var_tab, sections["consol"]["variance_tables"],
                                       sections["consol"]["detected_unit"], sections["consol"]["pm_threshold"],
                                       sections["consol"].get("variance_source"))
            rh.doc_label_title(var_tab, "별도재무제표")
            rh.render_variance_tables(var_tab, sections["separate"]["variance_tables"],
                                       sections["separate"]["detected_unit"], sections["separate"]["pm_threshold"],
                                       sections["separate"].get("variance_source"))
        else:
            data = sections["single"]
            rh.render_variance_tables(var_tab, data["variance_tables"], data["detected_unit"], data["pm_threshold"],
                                       data.get("variance_source"))

        # 합계검증 탭 (재무제표 계층별 합계검증 + FS간 교차검증, XBRL·PDF 둘 다)
        calc_tab = self.scroll_frames["합계검증"]
        if is_dual:
            rh.doc_label_title(calc_tab, "연결재무제표")
            rh.render_calc_check(calc_tab, sections["consol"].get("calc_check", {}))
            rh.render_cross_check_fs(calc_tab, sections["consol"].get("cross_check_fs", {}))
            rh.render_note_check(calc_tab, sections["consol"].get("note_check", {}))
            rh.doc_label_title(calc_tab, "별도재무제표")
            rh.render_calc_check(calc_tab, sections["separate"].get("calc_check", {}))
            rh.render_cross_check_fs(calc_tab, sections["separate"].get("cross_check_fs", {}))
            rh.render_note_check(calc_tab, sections["separate"].get("note_check", {}))
        else:
            data = sections["single"]
            rh.render_calc_check(calc_tab, data.get("calc_check", {}))
            rh.render_cross_check_fs(calc_tab, data.get("cross_check_fs", {}))
            rh.render_note_check(calc_tab, data.get("note_check", {}))

        # 회계처리 변경 탭
        change_tab = self.scroll_frames["회계처리 변경"]
        if is_dual:
            rh.doc_label_title(change_tab, "연결재무제표")
            rh.render_accounting_changes(change_tab, sections["consol"]["accounting_changes"])
            rh.doc_label_title(change_tab, "별도재무제표")
            rh.render_accounting_changes(change_tab, sections["separate"]["accounting_changes"])
        else:
            rh.render_accounting_changes(change_tab, sections["single"]["accounting_changes"])

        # 참조자료 탭
        ref_tab = self.scroll_frames["참조자료"]
        rh.render_reference(ref_tab, sections.get("reference_matches", {}), result.get("ref_sources", []))

        # 연결 vs 별도 탭
        cvs_tab = self.scroll_frames["연결 vs 별도"]
        if is_dual:
            rh.render_consol_vs_sep(cvs_tab, sections["consol_vs_sep"])
        else:
            rh.empty_note(cvs_tab, "키워드/실무체크리스트 비교는 옵션2에서 '연결 vs 별도'를 선택한 "
                                    "경우에만 표시됩니다.")
        rh.render_excel_compare(cvs_tab, result.get("excel_compare"))

    def _render_summary_doc(self, parent, label, data):
        rh.doc_label_title(parent, f"{label} 요약")
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 4))
        op = data["opinion"]
        color_map = {
            "적정(변형 없음)": theme.ACCENT_MINT, "한정의견": theme.ACCENT_PEACH,
            "부적정의견": theme.ACCENT_CORAL, "의견거절": theme.ACCENT_CORAL,
        }
        rh.badge(row, f"의견: {op['opinion_type']}", color_map.get(op["opinion_type"], theme.ACCENT_SKY)).pack(side="left", padx=4)

        found_n = sum(1 for i in data["checklist"] if i["found"])
        req_missing = sum(1 for i in data["checklist"] if i.get("required") and not i["found"])
        rh.badge(row, f"체크리스트 {found_n}/{len(data['checklist'])}",
                  theme.ACCENT_MINT if req_missing == 0 else theme.ACCENT_CORAL).pack(side="left", padx=4)
        rh.badge(row, f"합계검산 불일치 {len(data['sum_check'])}건",
                  theme.ACCENT_MINT if not data["sum_check"] else theme.ACCENT_CORAL).pack(side="left", padx=4)
        calc_check = data.get("calc_check") or {}
        calc_mismatches = sum(len(src.get(s, {}).get("mismatches", []))
                               for src in calc_check.values() if src
                               for s in ["재무상태표", "손익계산서", "자본변동표", "현금흐름표"])
        cross_check_fs = data.get("cross_check_fs") or {}
        cross_mismatches = sum(len(v) for v in cross_check_fs.values() if v)
        total_calc_issues = calc_mismatches + cross_mismatches
        rh.badge(row, f"합계검증(계층/FS간) 불일치 {total_calc_issues}건",
                  theme.ACCENT_MINT if total_calc_issues == 0 else theme.ACCENT_CORAL).pack(side="left", padx=4)
        rh.badge(row, f"회계처리변경 키워드 {len(data['accounting_changes'])}건", theme.ACCENT_SKY).pack(side="left", padx=4)
        rh.badge(row, f"총 {data['page_count']}p", theme.BG_SIDEBAR).pack(side="left", padx=4)

    # -------------------------------------------------------------- 내보내기
    def _export_txt(self):
        if not self.last_result:
            return
        path = fd.asksaveasfilename(defaultextension=".txt", filetypes=[("텍스트 파일", "*.txt")],
                                     initialfile="사전리뷰결과.txt")
        if not path:
            return
        export_txt(self.last_result, path)
        mb.showinfo("저장 완료", f"저장되었습니다:\n{path}")

    def _export_docx(self):
        if not self.last_result:
            return
        path = fd.asksaveasfilename(defaultextension=".docx", filetypes=[("Word 문서", "*.docx")],
                                     initialfile="사전리뷰결과.docx")
        if not path:
            return
        try:
            export_docx(self.last_result, path)
        except Exception as e:  # noqa: BLE001
            mb.showerror("저장 실패", f"DOCX 저장 중 오류가 발생했습니다.\n\n{e}")
            return
        mb.showinfo("저장 완료", f"저장되었습니다:\n{path}")

    def _export_excel(self):
        if not self.last_result or self.last_result.get("not_supported"):
            return
        path = fd.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel 통합 문서", "*.xlsx")],
                                     initialfile="증감분석표.xlsx")
        if not path:
            return
        try:
            export_variance_excel(self.last_result, path)
        except Exception as e:  # noqa: BLE001
            mb.showerror("저장 실패", f"Excel 저장 중 오류가 발생했습니다.\n\n{e}")
            return
        mb.showinfo("저장 완료", f"저장되었습니다:\n{path}")


def run_app():
    app = App()
    app.mainloop()
