from __future__ import annotations

"""Discover Engineering OS-owned run-status records and run plans within local worktree roots."""
import json
import os
from pathlib import Path
import subprocess

from . import _read_projection, _updated_at
from ..projection import NoStatusBlock, Projection, parse_projection, status_block

GLOBS = ('run-status.json', '*/run-status.json', 'engineering-os/*/run-status.json')
PLAN_GLOBS = ('run-plan.md', '*/run-plan.md', 'engineering-os/*/run-plan.md')


STATUS_ALLOWANCE = 15 * 60


def _head_state(plan):
    """Repository HEAD identity read from files, so a commit changes it with no subprocess."""
    try:
        directory = plan.resolve().parent
        for candidate in (directory, *directory.parents):
            marker = candidate / '.git'
            if marker.exists():
                break
        else:
            return ''
        if marker.is_file():
            gitdir = Path(marker.read_text().split(':', 1)[1].strip())
            gitdir = gitdir if gitdir.is_absolute() else (candidate / gitdir).resolve()
        else:
            gitdir = marker
        head = (gitdir / 'HEAD').read_text().strip()
        common = gitdir
        if (gitdir / 'commondir').is_file():
            common = (gitdir / (gitdir / 'commondir').read_text().strip()).resolve()
        if not head.startswith('ref:'):
            return head
        ref = head.split(':', 1)[1].strip()
        for base in (gitdir, common):
            if (base / ref).is_file():
                return head + ' ' + (base / ref).read_text().strip()
        packed = common / 'packed-refs'
        return head + ' ' + (str(packed.stat().st_mtime) if packed.exists() else '')
    except (OSError, IndexError, ValueError):
        return ''


def _plan_git(plan):
    """Repository root, last commit hash and time, and the commits that touched the plan and its updatedAt.

    Slow thread only. Returns (top, short, commit_at, plan_hash, status_hash).
    """
    none = ('', '', None, '', '')
    try:
        top = subprocess.run(['git', '-C', str(plan.parent), 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True, timeout=5)
        if top.returncode:
            return none
        top = Path(top.stdout.strip()).resolve()
        relative = str(plan.resolve().relative_to(top))
        log = subprocess.run(['git', '-C', str(top), '--literal-pathspecs', 'log', '-1',
                              '--format=%h %ct %H', '--', relative],
                             capture_output=True, text=True, timeout=5)
        fields = log.stdout.split() if log.returncode == 0 else []
        if len(fields) != 3:
            return (str(top), '', None, '', '')
        marked = subprocess.run(['git', '-C', str(top), '--literal-pathspecs', 'log', '-1',
                                 '-G', '"updatedAt"', '--format=%H', '--', relative],
                                capture_output=True, text=True, timeout=5)
        status_hash = marked.stdout.strip() if marked.returncode == 0 else ''
        return str(top), fields[0], float(fields[1]), fields[2], status_hash
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return none


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
        self._file_commits = {}
        self._found = None
        self._parsed = {}
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

    def _git_for(self, path, fresh):
        """Cached git answer for a file, keyed by its mtime and the repository HEAD."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        head = _head_state(path)
        entry = self._git.get(str(path))
        if entry and entry[:2] == (mtime, head):
            result = entry[2]
        else:
            result = _plan_git(path)
        fresh[str(path)] = (mtime, head, result)
        return result

    def refresh(self, roots: list[Path]) -> None:
        """Slow thread: the only place that runs git for plans."""
        fresh, files = {}, {}
        plans = list(self._discover(roots, PLAN_GLOBS))
        statuses = list(self._discover(roots, GLOBS))
        for _, path in plans:
            self._git_for(path, fresh)
        for _, path in statuses:
            plan = self._file_plan(path)
            result = plan and self._git_for(plan, fresh)
            if result and result[2] is not None:
                files[str(path)] = result[2]
        self._git, self._file_commits = fresh, files
        self._found = (statuses, plans)

    @staticmethod
    def _file_plan(path):
        """The run plan a run-status.json names, when it exists on disk."""
        try:
            plan = json.loads(path.read_text(encoding='utf-8')).get('runPlan')
            worktree, relative = plan.get('worktree'), plan.get('path')
            if isinstance(worktree, str) and isinstance(relative, str) and worktree and relative:
                candidate = Path(worktree) / relative
                return candidate if candidate.is_file() else None
        except (OSError, ValueError, RecursionError, AttributeError):
            pass
        return None

    def _read_plan(self, path, boundary):
        try:
            with path.open(encoding='utf-8') as source:
                text = source.read()
                mtime = os.fstat(source.fileno()).st_mtime
        except (OSError, ValueError):
            raise ValueError('unreadable')
        data = status_block(text)
        entry = self._git.get(str(path))
        top, commit, commit_at, plan_hash, status_hash = (
            entry[2] if entry and entry[0] == mtime else ('', '', None, '', ''))
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
        if plan_hash and status_hash:
            projection.plan_changed = plan_hash != status_hash
        return projection, data

    def _cached(self, path, key, parse):
        """Parse result for a file, re-run only when its mtime or git answer changed."""
        try:
            stamp = (path.stat().st_mtime, key)
        except OSError:
            self._parsed.pop(str(path), None)
            return 'none', None
        entry = self._parsed.get(str(path))
        if entry and entry[0] == stamp:
            return entry[1]
        result = parse()
        self._parsed[str(path)] = (stamp, result)
        return result

    def _load_status(self, path):
        try:
            projection = _read_projection(path)
            commit_at = self._file_commits.get(str(path))
            if commit_at is not None:
                projection.plan_commit_at = commit_at
                updated = _updated_at(projection)
                if updated != float('-inf'):
                    projection.plan_changed = commit_at - updated > STATUS_ALLOWANCE
            return 'ok', projection
        except ValueError as error:
            return 'bad', (str(error), self._run_hint(path, lambda text: json.loads(text)))

    def _load_plan(self, boundary, path):
        try:
            return 'ok', self._read_plan(path, boundary)[0]
        except NoStatusBlock:
            return 'none', None
        except ValueError as error:
            return 'bad', (str(error), self._run_hint(path, status_block))

    def load(self, roots: list[Path]) -> tuple[list[Projection], dict[str, str]]:
        """Fast path: stats the paths the slow thread found; globs only before the first refresh."""
        found = self._found
        if found is None:
            found = (list(self._discover(roots, GLOBS)), list(self._discover(roots, PLAN_GLOBS)))
        statuses, plans = found
        good, bad, hints = [], {}, {}
        for boundary, path in statuses:
            state, value = self._cached(path, self._file_commits.get(str(path)),
                                        lambda: self._load_status(path))
            self._collect(path, state, value, good, bad, hints)
        for boundary, path in plans:
            entry = self._git.get(str(path))
            state, value = self._cached(path, entry and entry[2],
                                        lambda: self._load_plan(boundary, path))
            self._collect(path, state, value, good, bad, hints)
        self.rejected_runs = {key: run for key, run in hints.items() if run}
        return good, bad

    @staticmethod
    def _collect(path, state, value, good, bad, hints):
        if state == 'ok':
            good.append(value)
        elif state == 'bad':
            bad[str(path)], hints[str(path)] = value

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
