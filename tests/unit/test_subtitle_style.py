"""ASS字幕背景スタイルのテスト。"""

import pytest

from youtube_generator.services.subtitle_style import build_ass_subtitle_style


def _style(**overrides: object) -> str:
    values = {
        "font": "Arial", "size": 24, "primary_color": "&H00FFFFFF",
        "position": "bottom", "alignment": "center", "margin": 80,
        "box_enabled": True, "background_color": "#000000",
        "background_opacity": 0.6,
    }
    values.update(overrides)
    return build_ass_subtitle_style(**values)  # type: ignore[arg-type]


def test_converts_rgb_and_opacity_to_ass_background_color() -> None:
    style = _style(background_color="#123456", background_opacity=0.75)

    assert "BorderStyle=4" in style
    assert "BackColour=&H40563412" in style
    assert "Outline=0,Shadow=4" in style


def test_accepts_ass_color_and_replaces_its_alpha_with_opacity() -> None:
    assert "BackColour=&HCC332211" in _style(
        background_color="&H00332211", background_opacity=0.2,
    )


def test_disabled_box_keeps_normal_subtitle_border_style() -> None:
    style = _style(box_enabled=False)

    assert "BorderStyle=1" in style
    assert "Outline=0" not in style


@pytest.mark.parametrize("opacity", [-0.1, 1.1])
def test_rejects_invalid_background_opacity(opacity: float) -> None:
    with pytest.raises(ValueError, match="background_opacity"):
        _style(background_opacity=opacity)


def test_rejects_invalid_background_color() -> None:
    with pytest.raises(ValueError, match="background_color"):
        _style(background_color="black")
