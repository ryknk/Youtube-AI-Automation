"""APIに依存しない台本品質チェック。"""

import re
import html
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from youtube_generator.domain.audio_duration_provider import AudioDurationProvider
from youtube_generator.domain.quality import (
    ProjectQualityReport,
    QualityCheckResult,
    QualityIssue,
    QualityReport,
    QualitySeverity,
)
from youtube_generator.services.image_prompt_builder import ImagePromptBuilder


@dataclass(frozen=True, slots=True)
class QualityRules:
    min_characters: int
    max_characters: int
    characters_per_second: float
    forbidden_words: tuple[str, ...]
    duplicate_sentence_threshold: int


def load_quality_rules(settings: object) -> QualityRules:
    """config.yamlのquality設定からルールを読み込む。"""
    try:
        if not isinstance(settings, dict):
            raise ValueError("quality セクションが必要です。")
        forbidden_words = settings.get("forbidden_words", [])
        if not isinstance(forbidden_words, list) or not all(isinstance(word, str) for word in forbidden_words):
            raise ValueError("forbidden_words は文字列配列で指定してください。")
        return QualityRules(
            min_characters=int(settings["min_characters"]),
            max_characters=int(settings["max_characters"]),
            characters_per_second=float(settings["characters_per_second"]),
            forbidden_words=tuple(forbidden_words),
            duplicate_sentence_threshold=int(settings["duplicate_sentence_threshold"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("config.yaml の品質設定を読み込めません。") from error


class ScriptQualityChecker:
    """台本の文字数、想定時間、NGワード、重複文を検査する。"""

    def __init__(self, rules: QualityRules) -> None:
        self._rules = rules

    def check(self, script: str) -> QualityReport:
        normalized_script = re.sub(r"\s+", "", script)
        character_count = len(normalized_script)
        duration = character_count / self._rules.characters_per_second
        issues: list[QualityIssue] = []

        if character_count < self._rules.min_characters:
            issues.append(QualityIssue("min_characters", "台本の文字数が下限を下回っています。", QualitySeverity.ERROR))
        if character_count > self._rules.max_characters:
            issues.append(QualityIssue("max_characters", "台本の文字数が上限を超えています。", QualitySeverity.ERROR))

        for word in self._rules.forbidden_words:
            if word in script:
                issues.append(QualityIssue("forbidden_word", f"NGワードを検出しました: {word}", QualitySeverity.ERROR))

        sentences = [sentence.strip() for sentence in re.split(r"[。！？!?]", script) if sentence.strip()]
        duplicates = Counter(sentences)
        for sentence, count in duplicates.items():
            if count >= self._rules.duplicate_sentence_threshold:
                issues.append(QualityIssue("duplicate_sentence", f"同じ表現が {count} 回あります: {sentence[:30]}", QualitySeverity.WARNING))

        return QualityReport(character_count, duration, tuple(issues))


class QualityChecker:
    """動画プロジェクト全体を評価し、JSON/HTMLレポートを保存する。"""

    def __init__(self, rules: QualityRules, duration_provider: AudioDurationProvider | None = None) -> None:
        self._rules = rules
        self._duration_provider = duration_provider

    def check_project(self, project_dir: Path, image_prompt_builder: ImagePromptBuilder) -> ProjectQualityReport:
        script_file = project_dir / "script.txt"
        script = self._read_text(script_file)
        checks = self._check_script(script)
        scene_files = tuple(sorted(project_dir.glob("scene*.txt")))
        checks.extend(self._check_scenes(scene_files))
        checks.extend(self._check_metadata(project_dir))
        checks.extend(self._check_prompts(scene_files, image_prompt_builder))
        checks.extend(self._check_media(project_dir))
        return ProjectQualityReport(str(project_dir), tuple(checks))

    def save_report(self, report: ProjectQualityReport, output_dir: Path) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_file = output_dir / "quality_report.json"
        html_file = output_dir / "quality_report.html"
        payload = {
            "project_dir": report.project_dir,
            "has_errors": report.has_errors,
            "improvements": list(report.improvements),
            "checks": [
                {"name": item.check_name, "status": item.severity.value.upper(), "message": item.message, "value": item.value}
                for item in report.checks
            ],
        }
        json_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = "".join(
            f"<tr><td>{html.escape(item.check_name)}</td><td>{item.severity.value.upper()}</td>"
            f"<td>{html.escape(item.message)}</td><td>{html.escape(str(item.value or ''))}</td></tr>"
            for item in report.checks
        )
        improvements = "".join(f"<li>{html.escape(item)}</li>" for item in report.improvements)
        html_file.write_text(
            "<!doctype html><html lang='ja'><meta charset='utf-8'><title>Quality Report</title>"
            "<style>body{font-family:Segoe UI,Meiryo,sans-serif;margin:24px}table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #ccc;padding:8px}.PASS{color:#16803c}.WARNING{color:#a66c00}.ERROR{color:#b42318}</style>"
            f"<h1>品質レポート</h1><p>重大エラー: {'あり' if report.has_errors else 'なし'}</p>"
            f"<table><tr><th>項目</th><th>判定</th><th>内容</th><th>値</th></tr>{rows}</table>"
            f"<h2>改善案</h2><ul>{improvements}</ul></html>",
            encoding="utf-8",
        )
        return json_file, html_file

    def _check_script(self, script: str) -> list[QualityCheckResult]:
        normalized = re.sub(r"\s+", "", script)
        character_count = len(normalized)
        duration = character_count / self._rules.characters_per_second if self._rules.characters_per_second else 0
        results = [
            self._range("文字数", character_count, self._rules.min_characters, self._rules.max_characters, "文字"),
            QualityCheckResult("想定読み上げ時間", QualitySeverity.PASS, "想定読み上げ時間を算出しました。", round(duration, 1)),
            self._range("改行数", script.count("\n"), 1, 200, "行"),
        ]
        ending_sentences = [item.strip() for item in re.split(r"[。！？!?]", script) if item.strip()]
        endings = [sentence[-3:] for sentence in ending_sentences if len(sentence) >= 3]
        repeated_ending = any(count >= 3 for count in Counter(endings).values())
        results.append(QualityCheckResult("同じ語尾の連続", QualitySeverity.WARNING if repeated_ending else QualitySeverity.PASS,
            "同じ終止記号が3回以上連続しています。" if repeated_ending else "語尾の連続はありません。"))
        sentences = [item.strip() for item in re.split(r"[。！？!?]", script) if item.strip()]
        duplicated = [text for text, count in Counter(sentences).items() if count >= self._rules.duplicate_sentence_threshold]
        results.append(QualityCheckResult("重複表現", QualitySeverity.WARNING if duplicated else QualitySeverity.PASS,
            "重複表現を検出しました。" if duplicated else "重複表現はありません。", len(duplicated)))
        forbidden = [word for word in self._rules.forbidden_words if word in script]
        results.append(QualityCheckResult("NGワード", QualitySeverity.ERROR if forbidden else QualitySeverity.PASS,
            f"NGワードを検出しました: {', '.join(forbidden)}" if forbidden else "NGワードはありません。", len(forbidden)))
        return results

    def _check_scenes(self, scene_files: tuple[Path, ...]) -> list[QualityCheckResult]:
        if not scene_files:
            return [QualityCheckResult("シーン長", QualitySeverity.ERROR, "シーンファイルがありません。")]
        lengths = [len(re.sub(r"\s+", "", self._read_text(path))) for path in scene_files]
        too_short = sum(length < 10 for length in lengths)
        return [QualityCheckResult("シーン長", QualitySeverity.WARNING if too_short else QualitySeverity.PASS,
            "短すぎるシーンがあります。" if too_short else "全シーンの長さは適切です。", len(scene_files))]

    def _check_metadata(self, project_dir: Path) -> list[QualityCheckResult]:
        titles = [line.strip() for line in self._read_text(project_dir / "titles.txt").splitlines() if line.strip()]
        title_lengths = [len(re.sub(r"^\d+\.\s*", "", title)) for title in titles]
        title_error = bool(title_lengths) and any(length > 60 for length in title_lengths)
        description_length = len(self._read_text(project_dir / "description.txt").strip())
        return [
            QualityCheckResult("タイトル長", QualitySeverity.ERROR if title_error else QualitySeverity.PASS,
                "60文字を超えるタイトルがあります。" if title_error else "タイトル長は適切です。", max(title_lengths, default=0)),
            QualityCheckResult("説明文長", QualitySeverity.WARNING if description_length and description_length < 80 else QualitySeverity.PASS,
                "説明文が短すぎます。" if description_length and description_length < 80 else "説明文長は適切です。", description_length),
        ]

    def _check_prompts(self, scene_files: tuple[Path, ...], builder: ImagePromptBuilder) -> list[QualityCheckResult]:
        prompts = [builder.build(self._read_text(path)) for path in scene_files if self._read_text(path).strip()]
        if not prompts:
            return [QualityCheckResult("画像生成プロンプト文字数", QualitySeverity.WARNING, "評価対象のプロンプトがありません。")]
        lengths = [len(prompt) for prompt in prompts]
        unique_ratio = len(set(prompts)) / len(prompts)
        return [
            QualityCheckResult("画像生成プロンプト文字数", QualitySeverity.WARNING if any(length > 4000 for length in lengths) else QualitySeverity.PASS,
                "4000文字を超えるプロンプトがあります。" if any(length > 4000 for length in lengths) else "プロンプト長は適切です。", max(lengths)),
            QualityCheckResult("同じ画像プロンプト率", QualitySeverity.WARNING if unique_ratio < 0.8 else QualitySeverity.PASS,
                "類似・重複した画像プロンプトが多すぎます。" if unique_ratio < 0.8 else "画像プロンプトの重複率は適切です。", round(1 - unique_ratio, 2)),
        ]

    def _check_media(self, project_dir: Path) -> list[QualityCheckResult]:
        audio_files = tuple(sorted(project_dir.glob("scene*.mp3")))
        if self._duration_provider is None or not audio_files:
            return [QualityCheckResult("動画時間", QualitySeverity.WARNING, "音声時間を取得できません。"),
                    QualityCheckResult("字幕同期", QualitySeverity.WARNING, "字幕同期を確認できません。")]
        audio_duration = sum(self._duration_provider.get_duration_seconds(path) for path in audio_files)
        subtitle_duration = self._srt_end_seconds(project_dir / "subtitles.srt")
        sync_error = subtitle_duration is None or abs(audio_duration - subtitle_duration) > 1.0
        return [
            QualityCheckResult("動画時間", QualitySeverity.PASS, "音声から動画時間を算出しました。", round(audio_duration, 1)),
            QualityCheckResult("字幕同期", QualitySeverity.ERROR if sync_error else QualitySeverity.PASS,
                "字幕終端と音声時間が一致しません。" if sync_error else "字幕同期は適切です。", round(subtitle_duration or 0, 1)),
        ]

    @staticmethod
    def _read_text(file_path: Path) -> str:
        try:
            return file_path.read_text(encoding="utf-8-sig")
        except OSError:
            return ""

    @staticmethod
    def _range(name: str, value: int, minimum: int, maximum: int, unit: str) -> QualityCheckResult:
        severity = QualitySeverity.ERROR if value < minimum or value > maximum else QualitySeverity.PASS
        return QualityCheckResult(name, severity, f"{minimum}〜{maximum}{unit}の範囲で評価しました。", value)

    @staticmethod
    def _srt_end_seconds(srt_file: Path) -> float | None:
        content = QualityChecker._read_text(srt_file)
        matches = re.findall(r"-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})", content)
        if not matches:
            return None
        hours, minutes, seconds, milliseconds = (int(value) for value in matches[-1])
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
