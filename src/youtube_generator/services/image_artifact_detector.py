"""生成画像に既知のアーティファクト（レターボックス帯）がないかを検出する。

Qwen-Imageは、ワイド画面のイラスト生成を指示した際に、まれに学習データ由来の
「アニメ動画スクリーンショット」的な構図（上下に黒帯＋文字化けした字幕/タイトル風の
文字）を生成することがある。プロンプト・negative_promptでの抑制だけでは完全には
防げないため、生成直後に検出し、可能であれば別seedで再生成するために利用する。
"""

from PIL import Image

# 画像上下端から検査する帯の高さ（画像高さに対する比率）。
_EDGE_STRIP_HEIGHT_RATIO = 0.02
_MIN_EDGE_STRIP_PIXELS = 6
# 平均輝度がこの値未満なら「黒に近い」とみなす（0〜255階調）。
_DARK_MEAN_THRESHOLD = 18.0
# 標準偏差がこの値未満なら「ムラのない単色帯」とみなす。イラストの自然な暗部
# （夜空・影等）は完全な単色にはならないため区別できる。
_UNIFORM_STD_THRESHOLD = 6.0


def has_letterbox_bars(image: Image.Image) -> bool:
    """画像の上端または下端に、単色に近い黒帯（レターボックス）があるかを判定する。"""
    grayscale = image.convert("L")
    width, height = grayscale.size
    strip_height = min(height, max(_MIN_EDGE_STRIP_PIXELS, round(height * _EDGE_STRIP_HEIGHT_RATIO)))
    top_strip = grayscale.crop((0, 0, width, strip_height))
    bottom_strip = grayscale.crop((0, height - strip_height, width, height))
    return _is_uniform_dark(top_strip) or _is_uniform_dark(bottom_strip)


def _is_uniform_dark(strip: Image.Image) -> bool:
    pixel_values = list(strip.getdata())
    if not pixel_values:
        return False
    mean = sum(pixel_values) / len(pixel_values)
    if mean >= _DARK_MEAN_THRESHOLD:
        return False
    variance = sum((value - mean) ** 2 for value in pixel_values) / len(pixel_values)
    return variance**0.5 < _UNIFORM_STD_THRESHOLD
