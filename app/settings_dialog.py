"""참조자료 폴더/커스텀 체크리스트 경로 설정 대화상자."""
import tkinter.filedialog as fd

import customtkinter as ctk

from . import theme
from .rules.reference_lookup import folder_status


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, settings: dict, on_save):
        super().__init__(master)
        self.title("설정 - 참조자료 폴더")
        self.geometry("680x640")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_MAIN)
        self.settings = dict(settings)
        self.on_save = on_save

        self.grab_set()  # 모달

        body = ctk.CTkScrollableFrame(self, fg_color=theme.BG_MAIN, scrollbar_button_color=theme.BORDER_SOFT)
        body.pack(fill="both", expand=True)

        ctk.CTkLabel(body, text="참조자료 · 체크리스트 설정", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_MAIN).pack(pady=(20, 4), padx=20, anchor="w")
        ctk.CTkLabel(
            body,
            text="KIFRS·일반기업회계기준 PDF는 로그인/자동 스크래핑이 불가능하여, 각 폴더에 미리\n"
                 "다운로드해 두면 프로그램이 해당 폴더의 PDF에서 관련 조항을 검색합니다.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, justify="left",
        ).pack(padx=20, anchor="w", pady=(0, 14))

        self.kgaap_var = ctk.StringVar(value=self.settings.get("kgaap_folder", ""))
        self.kifrs_var = ctk.StringVar(value=self.settings.get("kifrs_folder", ""))
        self.kifrs_early_var = ctk.StringVar(value=self.settings.get("kifrs_early_folder", ""))
        self.checklist_var = ctk.StringVar(value=self.settings.get("custom_checklist_path", ""))

        self._folder_row(body, "일반기업회계기준(K-GAAP) 폴더", self.kgaap_var)
        self._folder_row(body, "KIFRS 폴더 (시행중)", self.kifrs_var)
        self._folder_row(body, "KIFRS 폴더 (조기적용가능)", self.kifrs_early_var)
        self._file_row(body, "커스텀 체크리스트 파일 (CSV/XLSX, 추후 추가 예정)", self.checklist_var)

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(pady=24)
        ctk.CTkButton(btn_row, text="저장", width=120, corner_radius=10,
                       fg_color=theme.ACCENT_PRIMARY, hover_color=theme.ACCENT_PRIMARY_HOVER,
                       text_color=theme.TEXT_ON_ACCENT, command=self._save).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="취소", width=120, corner_radius=10,
                       fg_color="#EDE7FB", hover_color=theme.BORDER_SOFT, text_color=theme.TEXT_MAIN,
                       command=self.destroy).pack(side="left", padx=6)

    def _folder_row(self, parent, label, var):
        frame = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=12,
                              border_width=1, border_color=theme.BORDER_SOFT)
        frame.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(frame, text=label, font=theme.FONT_SUBTITLE, text_color=theme.TEXT_MAIN)\
            .pack(anchor="w", padx=14, pady=(10, 2))

        entry = ctk.CTkEntry(frame, textvariable=var, corner_radius=8)
        entry.pack(fill="x", padx=14, pady=(0, 6))

        bottom = ctk.CTkFrame(frame, fg_color="transparent")
        bottom.pack(fill="x", padx=14, pady=(0, 10))
        status = ctk.CTkLabel(bottom, text=folder_status(var.get()), font=theme.FONT_SMALL,
                               text_color=theme.TEXT_SUB, anchor="w")
        status.pack(side="left", fill="x", expand=True)

        def browse():
            path = fd.askdirectory(title=f"{label} 선택")
            if path:
                var.set(path)
                status.configure(text=folder_status(path))

        ctk.CTkButton(bottom, text="찾아보기", width=90, corner_radius=8,
                       fg_color=theme.ACCENT_SKY, hover_color=theme.ACCENT_SKY_DARK,
                       text_color=theme.TEXT_MAIN, command=browse).pack(side="left", padx=(8, 0))

    def _file_row(self, parent, label, var):
        frame = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=12,
                              border_width=1, border_color=theme.BORDER_SOFT)
        frame.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(frame, text=label, font=theme.FONT_SUBTITLE, text_color=theme.TEXT_MAIN)\
            .pack(anchor="w", padx=14, pady=(10, 2))
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 10))
        entry = ctk.CTkEntry(row, textvariable=var, corner_radius=8)
        entry.pack(side="left", fill="x", expand=True)

        def browse():
            path = fd.askopenfilename(title=label, filetypes=[("CSV/Excel", "*.csv *.xlsx *.xls")])
            if path:
                var.set(path)

        ctk.CTkButton(row, text="찾아보기", width=90, corner_radius=8,
                       fg_color=theme.ACCENT_SKY, hover_color=theme.ACCENT_SKY_DARK,
                       text_color=theme.TEXT_MAIN, command=browse).pack(side="left", padx=(8, 0))

    def _save(self):
        self.settings["kgaap_folder"] = self.kgaap_var.get().strip()
        self.settings["kifrs_folder"] = self.kifrs_var.get().strip()
        self.settings["kifrs_early_folder"] = self.kifrs_early_var.get().strip()
        self.settings["custom_checklist_path"] = self.checklist_var.get().strip()
        self.on_save(self.settings)
        self.destroy()
