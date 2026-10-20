from __future__ import annotations

"""Read explicit --out exports from a user-configured directory."""
from pathlib import Path

from . import _read_projection
from ..projection import Projection


class DirectoryProvider:
    name = 'directory'

    def __init__(self, path: Path):
        self.path = Path(path).expanduser()

    def load(self, roots: list[Path]) -> tuple[list[Projection], dict[str, str]]:
        good, bad = [], {}
        try:
            paths = sorted(self.path.glob('*.json'))
        except OSError:
            return good, bad
        for path in paths:
            try:
                good.append(_read_projection(path))
            except ValueError as error:
                bad[path.name] = str(error)
        return good, bad
