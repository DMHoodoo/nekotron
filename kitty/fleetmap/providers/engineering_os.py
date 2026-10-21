from __future__ import annotations

"""Discover Engineering OS-owned run-status records and run plans within local worktree roots."""
import json
import os
from pathlib import Path
import subprocess

from . import _read_projection
from ..projection import NoStatusBlock, Projection, parse_projection, status_block

GLOBS = ('run-status.json', '*/run-status.json', 'engineering-os/*/run-status.json')
PLAN_GLOBS = ('run-plan.md', '*/run-plan.md', 'engineering-os/*/run-plan.md')


def _plan_git(plan):
    """Repository root, last commit hash and commit time of a plan; slow thread only."""
    try:
        top = subprocess.run(['git', '-C', str(plan.parent), 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True, timeout=5)
        if top.returncode:
            return '', '', None
        top = Path(top.stdout.strip()).resolve()
        relative = plan.resolve().relative_to(top)
        log = subprocess.run(['git', '-C', str(top), '--literal-pathspecs', 'log', '-1',
                              '--format=%h %ct', '--', str(relative)],
                             capture_output=True, text=True, timeout=5)
        fields = log.stdout.split() if log.returncode == 0 else []
        if len(fields) != 2:
            return str(top), '', None
        return str(top), fields[0], float(fields[1])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return '', '', None


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
        self._git = {}
        self.rejected_runs = {}

    def _discover(self, roots, globs):
        seen = set()
        for root in roots + self.extra_roots:
            try:
                root = Path(root)
                boundary = root.resolve()
            except (OSError, RuntimeError):
                continue
            for pattern in globs:
                for path in sorted(_paths(root, boundary, pattern)):
                    canonical = path.resolve()
                    if canonical in seen:
                        continue
                    seen.add(canonical)
                    yield boundary, path

    def refresh(self, roots: list[Path]) -> None:
        """Slow thread: the only place that runs git for plans, cached by path and mtime."""
        fresh = {}
        for _, path in self._discover(roots, PLAN_GLOBS):
            try:
                key = (str(path), path.stat().st_mtime)
            except OSError:
                continue
            fresh[key] = self._git.get(key) or _plan_git(path)
        self._git = fresh

    def _read_plan(self, path, boundary):
        try:
            with path.open(encoding='utf-8') as source:
                text = source.read()
                mtime = os.fstat(source.fileno()).st_mtime
        except (OSError, ValueError):
            raise ValueError('unreadable')
        data = status_block(text)
        top, commit, commit_at = self._git.get((str(path), mtime), ('', '', None))
        top = Path(top) if top else boundary
        if isinstance(data, dict) and isinstance(data.get('runPlan'), dict):
            try:
                relative = str(path.resolve().relative_to(top))
            except ValueError:
                relative = str(path.resolve().relative_to(boundary))
            data['runPlan'].update(path=relative, commit=commit, worktree=str(top))
        projection = parse_projection(data, mtime)
        projection.path = str(path)
        projection.plan_commit_at = commit_at
        return projection, data

    def load(self, roots: list[Path]) -> tuple[list[Projection], dict[str, str]]:
        good, bad, hints = [], {}, {}
        for boundary, path in self._discover(roots, GLOBS):
            try:
                good.append(_read_projection(path))
            except ValueError as error:
                bad[str(path)] = str(error)
                hints[str(path)] = self._run_hint(path, lambda text: json.loads(text))
        for boundary, path in self._discover(roots, PLAN_GLOBS):
            try:
                good.append(self._read_plan(path, boundary)[0])
            except NoStatusBlock:
                continue
            except ValueError as error:
                bad[str(path)] = str(error)
                hints[str(path)] = self._run_hint(path, status_block)
        self.rejected_runs = {key: run for key, run in hints.items() if run}
        return good, bad

    @staticmethod
    def _run_hint(path, parse):
        """Run id named by the record when it parses, else by the source's directory."""
        try:
            data = parse(path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and isinstance(data.get('run'), str):
                return data['run']
        except (OSError, ValueError, RecursionError):
            pass
        return path.parent.name
