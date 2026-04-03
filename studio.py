import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from studio_gui import main  # noqa: E402


if __name__ == "__main__":
    main()
