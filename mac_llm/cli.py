"""Console entry point for mac-llm."""

from __future__ import annotations

import argparse

from mac_llm import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mac-llm",
        description="Local-agent runtime for Apple Silicon Mac Mini",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.parse_args()


if __name__ == "__main__":
    main()
