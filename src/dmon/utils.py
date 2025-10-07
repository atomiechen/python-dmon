import re
from typing import Literal


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def len_ansi(s: str) -> int:
    return len(ANSI_RE.sub("", s))


def pad_ansi(
    s: str, width: int, align: Literal["<", ">", "^"] = "<", fill: str = " "
) -> str:
    """Pad a string with ANSI escape codes to a given width."""
    real_len = len_ansi(s)
    if real_len == width:
        return s
    if real_len > width:
        return s[: width - 3] + "..."  # truncate and add ellipsis

    pad_len = width - real_len
    if align == "<":
        return s + fill * pad_len
    elif align == ">":
        return fill * pad_len + s
    elif align == "^":
        left = pad_len // 2
        right = pad_len - left
        return fill * left + s + fill * right
    else:
        raise ValueError(f"Invalid align: {align}")
