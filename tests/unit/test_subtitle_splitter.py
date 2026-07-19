from youtube_generator.services.subtitle_splitter import SubtitleSettings, SubtitleSplitter


def test_short_text_is_one_two_line_segment():
    parts = SubtitleSplitter(SubtitleSettings()).split("これは短い字幕です。", 3, 1)
    assert len(parts) == 1
    assert parts[0].end_time == 3


def test_long_text_is_split_within_two_lines_and_duration():
    parts = SubtitleSplitter(SubtitleSettings(max_chars_per_line=10)).split("人間の脳は、自分が信じたい情報を無意識に集めてしまう傾向があります。", 10, 1)
    assert len(parts) > 1
    assert all(len(part.text.splitlines()) <= 2 for part in parts)
    assert all(part.start_time < part.end_time for part in parts)
    assert parts[-1].end_time == 10
