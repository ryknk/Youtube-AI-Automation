from youtube_generator.services.subtitle_splitter import SubtitleSettings, SubtitleSplitter


def test_short_text_is_one_two_line_segment():
    parts = SubtitleSplitter(SubtitleSettings()).split("これは短い字幕です。", 3, 1)
    assert len(parts) == 1
    assert parts[0].end_time == 3


def test_long_text_is_split_within_two_lines_and_duration():
    text = "人間の脳は、自分が信じたい情報を無意識に集めてしまう傾向があります。"
    parts = SubtitleSplitter(SubtitleSettings(max_chars_per_line=10)).split(text, 10, 1)
    assert len(parts) > 1
    assert all(len(part.text.splitlines()) <= 2 for part in parts)
    assert all(part.start_time < part.end_time for part in parts)
    assert parts[-1].end_time == 10
    assert "".join(part.text.replace("\n", "") for part in parts) == text


def test_complete_sentence_is_not_mixed_with_part_of_next_sentence():
    first_sentence = "最初の文章はここで終わります。"
    text = first_sentence + "次の文章は、この後もまだまだ長く続いていきます。"

    parts = SubtitleSplitter(
        SubtitleSettings(max_lines=2, max_chars_per_line=12)
    ).split(text, 8, 1)

    normalized = [part.text.replace("\n", "") for part in parts]
    assert normalized[0] == first_sentence
    assert "".join(normalized) == text


def test_small_overflow_is_kept_until_sentence_end_without_losing_text():
    text = "この文章は上限を少し超えますが句点まで一緒に表示します。"

    parts = SubtitleSplitter(
        SubtitleSettings(max_lines=2, max_chars_per_line=15)
    ).split(text, 5, 1)

    assert len(parts) == 1
    assert parts[0].text.replace("\n", "") == text
    assert parts[0].text.endswith("。")
    assert len(parts[0].text.splitlines()) <= 2


def test_closing_quote_stays_with_sentence_end():
    text = "「これは本当ですか？」次の文章で詳しく説明します。"

    parts = SubtitleSplitter(
        SubtitleSettings(max_lines=1, max_chars_per_line=12)
    ).split(text, 5, 1)

    assert parts[0].text.endswith("？」")
    assert "".join(part.text.replace("\n", "") for part in parts) == text
