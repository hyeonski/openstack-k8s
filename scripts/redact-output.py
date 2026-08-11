#!/usr/bin/env python3
"""Redact bounded credential patterns from streamed command output."""

from __future__ import annotations

import re
import sys


PATTERNS = (
    (
        re.compile(r"\b[a-z0-9]{6}\.[a-z0-9]{16}\b"),
        "<redacted-bootstrap-token>",
    ),
    (
        re.compile(r"(?i)(--certificate-key(?:=|\s+))[0-9a-f]{64}\b"),
        r"\1<redacted-certificate-key>",
    ),
    (
        re.compile(r"(?i)(application_credential_secret\s*[:=]\s*)[^\s,}\]]+"),
        r"\1<redacted-application-credential>",
    ),
    (
        re.compile(r"(?i)(-u\s+openstack:)[^\s'\"]+"),
        r"\1<redacted-password>",
    ),
    (
        re.compile(r"(?i)(https?://[^\s:/@]+:)[^\s/@]+(@)"),
        r"\1<redacted-password>\2",
    ),
)


def redact(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def main() -> int:
    for line in sys.stdin:
        sys.stdout.write(redact(line))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
