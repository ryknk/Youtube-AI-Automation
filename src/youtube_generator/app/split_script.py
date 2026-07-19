"""台本をシーン別テキストファイルに保存するユースケース。"""

from pathlib import Path

from youtube_generator.domain.scene_splitter import SceneSplitter


class SplitScriptUseCase:
    """script.txtを読み込み、sceneNN.txtへ保存する。"""

    def __init__(self, splitter: SceneSplitter) -> None:
        self._splitter = splitter

    def execute(self, script_file: Path) -> tuple[Path, ...]:
        """入力台本を分割し、入力ファイルと同じフォルダへ連番保存する。"""
        try:
            script = script_file.read_text(encoding="utf-8")
        except OSError as error:
            raise FileNotFoundError(f"台本ファイルを読み込めません: {script_file}") from error

        scenes = self._splitter.split(script)
        scene_files: list[Path] = []
        for index, scene in enumerate(scenes, start=1):
            scene_file = script_file.parent / f"scene{index:02}.txt"
            scene_file.write_text(scene + "\n", encoding="utf-8")
            scene_files.append(scene_file)
        return tuple(scene_files)
