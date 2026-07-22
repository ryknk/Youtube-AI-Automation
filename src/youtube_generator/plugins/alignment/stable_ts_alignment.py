"""stable-tsを利用したローカル強制アライメントプラグイン。"""

import json
from pathlib import Path
from typing import Any

from youtube_generator.exceptions import AlignmentGenerationError
from youtube_generator.logger import get_logger


class StableTSAlignmentProvider:
    """元台本テキストと音声をstable-tsで強制アライメントし、alignment.jsonへ保存する。

    Whisperによる文字起こしは行わず、既知の台本テキストを音声へ強制アライメントする
    stable-tsの``align()``機能のみを使用する。
    """

    def __init__(self, model: str, language: str) -> None:
        self._model_name = model
        self._language = language
        self._loaded_model: Any = None
        self._logger = get_logger(__name__)

    def align(self, audio_file: Path, script_text: str, output_file: Path) -> None:
        self._logger.info(
            "stable-tsアライメントを開始します: audio=%s, model=%s, language=%s",
            audio_file, self._model_name, self._language,
        )
        units = self._run_alignment(audio_file, script_text)
        payload = {"provider": "stable_ts", "text": script_text, "units": units}
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._logger.info("stable-tsアライメントを終了しました: %s", output_file)

    def _run_alignment(self, audio_file: Path, script_text: str) -> list[dict[str, Any]]:
        """stable-tsで強制アライメントし、単語単位のunits配列を返す。テストでは差し替え対象。"""
        model = self._load_model()
        try:
            result = model.align(str(audio_file), script_text, language=self._language)
        except AlignmentGenerationError:
            raise
        except Exception as error:  # stable-ts/whisper側の例外は多様なため広く捕捉する
            raise AlignmentGenerationError(f"stable-tsアライメントに失敗しました: {audio_file}") from error
        if result is None:
            # model.align()は整合に失敗すると例外を出さずNoneを返す仕様（stable-ts alignment.align()参照）。
            raise AlignmentGenerationError(f"stable-tsがアライメント結果を返しませんでした: {audio_file}")

        units: list[dict[str, Any]] = []
        for segment in result.segments:
            words = getattr(segment, "words", None)
            if words:
                units.extend(
                    {"text": word.word, "start": float(word.start), "end": float(word.end)}
                    for word in words
                )
            else:
                units.append({
                    "text": segment.text, "start": float(segment.start), "end": float(segment.end),
                })
        if not units:
            raise AlignmentGenerationError(f"stable-tsのアライメント結果が空でした: {audio_file}")
        return units

    def _load_model(self) -> Any:
        if self._loaded_model is None:
            try:
                import stable_whisper
            except ImportError as error:
                raise AlignmentGenerationError(
                    "stable-tsがインストールされていません。`pip install stable-ts`を実行してください。"
                ) from error
            try:
                self._loaded_model = stable_whisper.load_model(self._model_name)
            except Exception as error:
                raise AlignmentGenerationError(
                    f"stable-tsモデルを読み込めません: {self._model_name}"
                ) from error
        return self._loaded_model
