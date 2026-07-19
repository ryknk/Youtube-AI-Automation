"""ローカル開発用の実行エントリーポイント。"""

import sys
from pathlib import Path

# パッケージを未インストールの開発環境でも `python main.py` で起動できるようにする。
SRC_DIR = Path(__file__).resolve().parent / "src"
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
