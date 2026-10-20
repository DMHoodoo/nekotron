from __future__ import annotations

"""Discover Engineering OS-owned run-status records within local worktree roots."""
from pathlib import Path

from . import _read_projection
from ..projection import Projection

GLOBS = ('run-status.json', '*/run-status.json', 'engineering-os/*/run-status.json')


def _within(path, root):
    try:
        path.resolve().relative_to(root)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _paths(root, boundary, pattern):
    # Check each segment before traversing it, including directory symlinks.
    candidates = [root]
    for segment in pattern.split('/'):
        following = []
        for parent in candidates:
            try:
                following.extend(path for path in parent.glob(segment) if _within(path, boundary))
            except OSError:
                continue
        candidates = following
    return candidates


class EngineeringOsProvider:
    name = 'engineering_os'

    def __init__(self, extra_roots: list[Path]):
        self.extra_roots = [Path(root).expanduser() for root in extra_roots]

    def load(self, roots: list[Path]) -> tuple[list[Projection], dict[str, str]]:
        good, bad, seen = [], {}, set()
        for root in roots + self.extra_roots:
            try:
                root = Path(root)
                boundary = root.resolve()
            except (OSError, RuntimeError):
                continue
            for pattern in GLOBS:
                for path in sorted(_paths(root, boundary, pattern)):
                    canonical = path.resolve()
                    if canonical in seen:
                        continue
                    seen.add(canonical)
                    try:
                        good.append(_read_projection(path))
                    except ValueError as error:
                        bad[str(path)] = str(error)
        return good, bad
