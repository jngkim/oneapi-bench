"""Helpers for ``apps/<app>/hooks.py``.

A hooks module defines:

``parse(rep_dir, ctx) -> dict``  (required)
    Read the output files of one repetition and return metrics. Must contain
    the workload's primary metric when the run succeeded.
``checks(metrics, rep_dir, ctx) -> list of (name, ok, detail)``  (optional)
    Validation: correct answer, GPU really used, enough steps measured, ...
``context(variables) -> dict``  (optional)
    Extra template variables derived from the case (e.g. flags that depend
    on the number of ranks).

``ctx`` contains the case variables (nodes, total_devices, ranks, ...), the
rendered workload parameters, and ``ctx["validate"]`` from the workload file.
"""

import re
from pathlib import Path

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def read(rep_dir, *names):
    """Text of the first existing file among ``names`` ('' if none exists)."""
    for name in names:
        path = Path(rep_dir) / name
        if path.exists():
            return path.read_text(errors="replace")
    return ""


def last_match(pattern, text, group=1, cast=float):
    matches = re.findall(pattern, text, re.MULTILINE)
    if not matches:
        return None
    value = matches[-1]
    if isinstance(value, tuple):
        value = value[group - 1]
    return cast(value)


def all_matches(pattern, text, cast=float):
    return [cast(m if not isinstance(m, tuple) else m[0])
            for m in re.findall(pattern, text, re.MULTILINE)]


def check(name, ok, good, bad):
    return (name, bool(ok), good if ok else bad)


def threshold(ctx, key, default):
    return ctx.get("validate", {}).get(key, default)
