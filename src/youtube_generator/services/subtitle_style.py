"""FFmpeg/libassに渡す字幕スタイルを組み立てる。"""

import re


_ASS_COLOR_PATTERN = re.compile(r"^&H(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})&?$")
_HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def build_ass_subtitle_style(
    *, font: str, size: int, primary_color: str,
    position: str, alignment: str, margin: int,
    box_enabled: bool, background_color: str, background_opacity: float,
) -> str:
    """ASS形式のforce_style文字列を返す。"""
    if not 0.0 <= background_opacity <= 1.0:
        raise ValueError("subtitles.background_opacity は0.0～1.0で指定してください。")
    if margin < 0:
        raise ValueError("subtitles.bottom_margin は0以上で指定してください。")

    values = [
        f"FontName={_escape_style_value(font)}",
        f"FontSize={size}",
        f"PrimaryColour={_escape_style_value(primary_color)}",
        f"Alignment={_ass_alignment(position, alignment)}",
        f"MarginV={margin}",
        # BorderStyle=3(不透明ボックス)はBackColourのアルファを無視し常に完全不透明になる
        # libassの既知の制限があるため、アルファを尊重するBorderStyle=4を使う。
        # BorderStyle=4ではOutlineが通常の文字縁取りに戻り、Shadowがボックスの余白を担う。
        f"BorderStyle={4 if box_enabled else 1}",
        f"BackColour={_background_color(background_color, background_opacity)}",
    ]
    if box_enabled:
        values.extend(("Outline=0", "Shadow=4"))
    return ",".join(values)


def _ass_alignment(position: str, alignment: str) -> int:
    horizontal = {"left": 1, "center": 2, "right": 3}
    vertical = {"bottom": 0, "middle": 3, "center": 3, "top": 6}
    try:
        return vertical[position.lower()] + horizontal[alignment.lower()]
    except KeyError as error:
        raise ValueError(
            "subtitles.position は bottom/middle/top、"
            "subtitles.alignment は left/center/right を指定してください。"
        ) from error


def _background_color(color: str, opacity: float) -> str:
    normalized = color.strip()
    if _HEX_COLOR_PATTERN.fullmatch(normalized):
        red, green, blue = normalized[1:3], normalized[3:5], normalized[5:7]
        bgr = f"{blue}{green}{red}"
    elif _ASS_COLOR_PATTERN.fullmatch(normalized):
        digits = normalized[2:].rstrip("&")
        bgr = digits[-6:]
    else:
        raise ValueError(
            "subtitles.background_color は #RRGGBB または "
            "&HAABBGGRR 形式で指定してください。"
        )
    ass_alpha = round((1.0 - opacity) * 255)
    return f"&H{ass_alpha:02X}{bgr.upper()}"


def _escape_style_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'").replace(",", "\\,")
