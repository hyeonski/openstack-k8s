#!/usr/bin/env python3
"""Render a strict ${NAME} template from the current environment."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from string import Template


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    content = args.source.read_text(encoding="utf-8")
    rendered = Template(content).substitute(os.environ)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(rendered, encoding="utf-8")
    os.chmod(args.destination, 0o600)


if __name__ == "__main__":
    main()

