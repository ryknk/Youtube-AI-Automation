"""ローカル開発用の実行エントリーポイント。"""

import os
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent


def _restart_in_project_venv() -> None:
    """`.venv` がある場合は、その Python でこのスクリプトを再起動する。"""
    if sys.platform == "win32":
        venv_python = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = PROJECT_DIR / ".venv" / "bin" / "python"

    if venv_python.is_file() and Path(sys.executable).resolve() != venv_python.resolve():
        os.execv(
            str(venv_python),
            [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        )


if __name__ == "__main__":
    _restart_in_project_venv()

# パッケージを未インストールの開発環境でも `python main.py` で起動できるようにする。
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from youtube_generator.cli.main import run  # noqa: E402


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "queue":
        from youtube_generator.cli.queue import run_queue

        run_queue(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "youtube":
        from youtube_generator.cli.youtube import run_youtube

        run_youtube(sys.argv[2:])
    else:
        run()
