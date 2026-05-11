"""Strip // line comments and /* */ block comments from JSONC input.

Preserves // and /* inside string literals. Leaves whitespace/newlines intact
so byte offsets remain close to the original when useful for error reporting.
"""
from __future__ import annotations


def strip_jsonc_comments(src: str) -> str:
    out: list[str] = []
    i = 0
    n = len(src)
    in_string = False
    escape = False

    while i < n:
        ch = src[i]

        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            # line comment: skip to end of line, preserve the newline
            i += 2
            while i < n and src[i] != "\n":
                i += 1
            continue

        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i = min(n, i + 2)
            continue

        out.append(ch)
        i += 1

    return "".join(out)
