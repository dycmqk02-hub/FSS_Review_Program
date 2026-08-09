"""파스텔톤 웹페이지st 컬러 팔레트 (라이트 테마 고정)."""

BG_MAIN = "#FAF8FF"        # 메인 콘텐츠 배경 (아주 옅은 라벤더 화이트)
BG_SIDEBAR = "#EDE7FB"     # 사이드바 배경 (소프트 라벤더)
BG_CARD = "#FFFFFF"        # 카드/패널 배경
BORDER_SOFT = "#E3DCF7"    # 카드 테두리

TEXT_MAIN = "#3F3856"      # 진한 플럼 (본문)
TEXT_SUB = "#8A83A0"       # 보조 텍스트(회색빛 라벤더)
TEXT_ON_ACCENT = "#FFFFFF"

ACCENT_PRIMARY = "#A79BFE"      # 주요 버튼(페리윙클) - 리뷰 진행률 0%
ACCENT_PRIMARY_HOVER = "#8F80FA"
ACCENT_PRIMARY_DEEP = "#4B3F9E"  # 리뷰 진행률 100%/완료 시 짙은 퍼플
ACCENT_MINT = "#B7ECD8"         # 성공/OK
ACCENT_MINT_DARK = "#3FAE85"
ACCENT_PEACH = "#FFD8B8"        # 참고/해당시
ACCENT_PEACH_DARK = "#D98B3F"
ACCENT_CORAL = "#FFB4B0"        # 경고/필수 미확인
ACCENT_CORAL_DARK = "#D9524C"
ACCENT_SKY = "#B9E3FF"          # 정보(참조자료 등)
ACCENT_SKY_DARK = "#3E8FC7"

# 재무제표 증감분석표 행 음영색
VARIANCE_AMOUNT_COLOR = "#FFF3B0"   # 금액차이가 PM 기준 이상 - 연노랑
VARIANCE_PCT_COLOR = "#FFD5A8"      # 증감률 5% 이상 - 살구색
VARIANCE_BOTH_COLOR = "#FFC04D"     # 두 조건 모두 해당 - 진한 호박색


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def interpolate_color(start_hex: str, end_hex: str, t: float) -> str:
    """t=0 -> start_hex, t=1 -> end_hex 사이의 색상 보간 (진행률 버튼 색상 변화용)."""
    t = max(0.0, min(1.0, t))
    s = _hex_to_rgb(start_hex)
    e = _hex_to_rgb(end_hex)
    mixed = tuple(s[i] + (e[i] - s[i]) * t for i in range(3))
    return _rgb_to_hex(mixed)

# 참조자료 출처별 배지 색상 (시행중 KIFRS / 조기적용가능 KIFRS / 일반기업회계기준 구분용)
REF_SOURCE_COLORS = {
    "시행중 KIFRS": ACCENT_SKY,
    "조기적용가능 KIFRS": ACCENT_PEACH,
    "일반기업회계기준(K-GAAP)": ACCENT_MINT,
}
REF_SOURCE_COLOR_DEFAULT = "#E3DCF7"  # BORDER_SOFT와 동일 - 미매칭 출처용 중립색


def ref_source_color(label: str) -> str:
    return REF_SOURCE_COLORS.get(label, REF_SOURCE_COLOR_DEFAULT)


FONT_FAMILY = "맑은 고딕"
FONT_TITLE = (FONT_FAMILY, 20, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 13, "bold")
FONT_BODY = (FONT_FAMILY, 12)
FONT_SMALL = (FONT_FAMILY, 10)
FONT_MONO = ("Consolas", 11)
