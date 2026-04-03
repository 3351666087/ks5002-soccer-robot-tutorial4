from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "packaging" / "KS5002Studio.spec"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
APP_PATH = DIST_DIR / "KS5002Studio.app"


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    result = subprocess.run(command, cwd=ROOT, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    pyinstaller = Path(sys.executable).with_name("pyinstaller")
    if not pyinstaller.exists():
        raise SystemExit("找不到 pyinstaller，请先激活 .venv。")

    run([str(pyinstaller), "--noconfirm", str(SPEC_PATH)])

    if APP_PATH.exists():
        run(["codesign", "--force", "--deep", "--sign", "-", str(APP_PATH)])
        print("已生成：%s" % APP_PATH)
    else:
        raise SystemExit("没有找到构建产物：%s" % APP_PATH)


if __name__ == "__main__":
    main()
