from __future__ import annotations

"""Derive one-off progress from local commits and GitHub pull requests."""
import json
from pathlib import Path
import subprocess
import time


def never_prompted(node: dict) -> bool:
    return node.get('you_at') is None and node.get('purpose') in (None, '')


def _checks(rollup: list | None) -> str:
    if not rollup:
        return 'none'
    pending = False
    for check in rollup:
        result = check.get('conclusion') or check.get('state')
        if result in ('FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED',
                      'ACTION_REQUIRED', 'STALE', 'STARTUP_FAILURE'):
            return 'fail'
        if (check.get('status') in ('QUEUED', 'IN_PROGRESS', 'WAITING', 'PENDING', 'REQUESTED')
                or result not in ('SUCCESS', 'NEUTRAL', 'SKIPPED')):
            pending = True
    return 'pending' if pending else 'pass'


class Ladder:
    def __init__(self, git: str = 'git', gh: str = 'gh', ttl: float = 60.0):
        self.git = git
        self.gh = gh
        self.ttl = ttl
        self._cache: dict[tuple[str, str | None], tuple[float, dict]] = {}
        self._defaults: dict[str, str] = {}

    def _run(self, binary: str, args: list[str], worktree: str) -> str:
        process = subprocess.run([binary, *args], cwd=worktree, capture_output=True,
                                 timeout=5.0, check=True)
        return process.stdout.decode('utf-8', errors='replace').strip()

    def _default(self, worktree: str) -> str:
        if worktree in self._defaults:
            return self._defaults[worktree]
        try:
            target = self._run(self.git, ['symbolic-ref', 'refs/remotes/origin/HEAD'],
                               worktree)
        except subprocess.CalledProcessError:
            # Older clones may lack the remote HEAD symbolic reference.
            candidates = []
            for name in ('master', 'main'):
                try:
                    self._run(self.git, ['rev-parse', '--verify',
                                         'refs/remotes/origin/' + name], worktree)
                except subprocess.CalledProcessError:
                    continue
                candidates.append('origin/' + name)
            if len(candidates) != 1:
                raise ValueError('Unknown remote default branch')
            # Only the ladder's TTL cache may retain a guessed baseline, so
            # the next refresh can discover a repaired origin/HEAD.
            return candidates[0]
        else:
            if not target.startswith('refs/remotes/origin/'):
                raise ValueError('Invalid remote HEAD')
            default = 'origin/HEAD'
        self._defaults[worktree] = default
        return default

    def _read(self, worktree: str, branch: str) -> dict:
        default = self._default(worktree)
        ahead = int(self._run(self.git, ['rev-list', '--count', default + '..HEAD'],
                              worktree))
        if ahead < 0:
            raise ValueError('Negative commit count')
        prs = json.loads(self._run(self.gh, [
            'pr', 'list', '--head', branch, '--state', 'all', '--json',
            'number,state,isDraft,statusCheckRollup', '--limit', '1'], worktree))
        if not isinstance(prs, list):
            raise ValueError('Invalid pull request list')
        rung = 'working' if ahead else 'asked'
        pr = None
        if prs:
            record = prs[0]
            if not isinstance(record, dict):
                raise ValueError('Invalid pull request')
            number, state, draft = record['number'], record['state'], record['isDraft']
            rollup = record.get('statusCheckRollup')
            if (type(number) is not int or number <= 0
                    or state not in ('OPEN', 'CLOSED', 'MERGED')
                    or type(draft) is not bool
                    or (rollup is not None and (not isinstance(rollup, list)
                        or any(not isinstance(check, dict) for check in rollup)))):
                raise ValueError('Invalid pull request fields')
            pr = {'number': number, 'state': state, 'isDraft': draft,
                  'checks': _checks(rollup)}
            if state == 'OPEN':
                rung = 'pr'
            elif state == 'MERGED':
                rung = 'merged'
        return {'rung': rung, 'ahead': ahead, 'pr': pr}

    def rung(self, worktree: str, branch: str | None) -> dict:
        """Return a cached ladder, retaining its last value on command failure."""
        asked = {'rung': 'asked', 'ahead': 0, 'pr': None}
        if not branch or not (Path(worktree) / '.git').exists():
            return asked
        key = (worktree, branch)
        cached = self._cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < self.ttl:
            return cached[1]
        try:
            value = self._read(worktree, branch)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            value = cached[1] if cached is not None else asked
        self._cache[key] = (time.monotonic(), value)
        return value
