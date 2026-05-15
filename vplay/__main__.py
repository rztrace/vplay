from __future__ import annotations

import sys

from . import __version__


def main() -> None:
    if any(arg in {"--version", "-V"} for arg in sys.argv[1:]):
        print(f"vplay {__version__}")
        return
    from .app import main as run_app

    run_app()


if __name__ == "__main__":
    main()
