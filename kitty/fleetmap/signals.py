from __future__ import annotations

"""Read-only overlays for the fleet collector.

StaleChecker.check(p, gate, branch=None) accepts a projection gate (verdict,
headSha); a branch selects the slice head, otherwise the run's PR is checked.
is_stalled compares it_at, optional last_output_at (epoch seconds), and optional
offset with the previous node. Both activity timestamps must be unchanged and
the latest known timestamp at least window seconds old; missing evidence cannot
establish a stall. Neither helper changes the projection or snapshot records.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

from .projection import Projection


def decision_strip(projections: list[Projection]) -> list[dict]:
    """List projected open decisions, with dated class B defaults first."""
    items = [{'run': p.run, 'title': p.title, 'id': d['id'],
              'class': d['class'], 'text': d['text'], 'packet': d.get('packet'),
              'applyAt': d.get('applyAt')}
        for p in projections for d in p.decisions]

    def order(item):
        deadline = float('inf')
        if item['class'] == 'B' and item['applyAt']:
            at = datetime.fromisoformat(item['applyAt'].replace('Z', '+00:00'))
            # Projection validation permits naive ISO times; interpret them as UTC.
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            deadline = at.timestamp()
        return ('BCD'.index(item['class']), deadline)

    return sorted(items, key=order)


def _run(args: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, check=True, timeout=5)
    return result.stdout.decode('utf-8', errors='replace').strip()


def _sha(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{4,64}', value) is not None


class StaleChecker:
    def __init__(self, gh: str = 'gh', git: str = 'git', ttl: float = 60.0):
        self.gh = gh
        self.git = git
        self.ttl = ttl
        self._cache: dict[tuple, tuple[float, dict | None]] = {}

    def check(self, p: Projection, gate: dict, branch: str | None = None) -> dict | None:
        """Compare passed evidence with a remote head, without fetching objects.

        Missing worktrees, missing targets, and failed head probes mean no check.
        A moved head remains reportable when its commit range is unavailable.
        """
        old = gate.get('headSha')
        worktree = p.runPlan.get('worktree')
        number, repo = p.pr.get('number'), p.pr.get('repo')
        if (gate.get('verdict') != 'pass' or not _sha(old) or not worktree
                or not Path(worktree).is_dir() or not (branch or (number and repo))):
            return None
        key = (p.run, worktree, branch, number, repo, old)
        cached = self._cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < self.ttl:
            return cached[1]
        value = None
        try:
            if branch:
                output = _run([self.git, 'ls-remote', 'origin', branch], cwd=worktree)
                ref = branch if branch.startswith('refs/heads/') else 'refs/heads/' + branch
                heads = [line.split()[0] for line in output.splitlines()
                         if len(line.split()) == 2 and line.split()[1] == ref]
                new = heads[0] if len(heads) == 1 else None
            else:
                result = json.loads(_run([self.gh, 'pr', 'view', str(number),
                                         '--repo', repo, '--json', 'headRefOid'], cwd=worktree))
                new = result.get('headRefOid') if isinstance(result, dict) else None
            if _sha(new):
                moved = not new.lower().startswith(old.lower())
                commits = []
                if moved:
                    try:
                        # git log fails when either endpoint is absent locally.
                        commits = _run([self.git, 'log', '--format=%H', old + '..' + new, '--'],
                                       cwd=worktree).splitlines()
                    except (OSError, subprocess.SubprocessError):
                        commits = None
                value = {'moved': moved, 'commits': commits}
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        self._cache[key] = (time.monotonic(), value)
        return value


def is_stalled(node: dict, prev_node: dict | None, now: float, window: float = 600) -> bool:
    """Require unchanged activity and enough elapsed time for a working node."""
    if (not prev_node or node.get('state') != 'working'
            or node.get('kind') not in ('claude', 'terminal')):
        return False
    if any(node.get(key) != prev_node.get(key) for key in ('it_at', 'last_output_at', 'offset')):
        return False
    timestamps = [node[key] for key in ('it_at', 'last_output_at')
                  if isinstance(node.get(key), (int, float))]
    return bool(timestamps) and now - max(timestamps) >= window


def _memory(vm_stat: str, memsize: str, swapusage: str) -> dict:
    page_size = re.search(r'page size of\s+(\d+)\s+bytes', vm_stat)
    free_pages = re.search(r'Pages free:\s+(\d+)\.', vm_stat)
    total = re.fullmatch(r'(?:hw\.memsize:\s*)?(\d+)', memsize.strip())
    swap = re.search(r'\bused\s*=\s*(\d+(?:\.\d+)?)\s*([BKMGTP])\b', swapusage)
    if not all((page_size, free_pages, total, swap)):
        raise ValueError('Incomplete memory probe')
    total_bytes = int(total[1])
    page_bytes = int(page_size[1])
    free_bytes = int(free_pages[1]) * page_bytes
    if total_bytes <= 0 or page_bytes <= 0 or free_bytes > total_bytes:
        raise ValueError('Invalid memory probe')
    # Report literal free pages; inactive and speculative pages remain separate.
    return {'free_pct': free_bytes * 100.0 / total_bytes,
            'swap_gb': float(swap[1]) * 1024 ** ('BKMGTP'.index(swap[2]) - 3)}


class MemoryProbe:
    def __init__(self, ssh: str = 'ssh', ttl: float = 15.0):
        self.ssh = ssh
        self.ttl = ttl
        self._cache: dict[tuple, tuple[float, dict]] = {}

    def probe(self, host: str, ssh_target: str | None) -> dict:
        """Read free page percentage and swap GiB, or None for both on failure.

        Local vm_stat and sysctl executables are injectable through PATH. Remote
        output is three lines: flattened vm_stat, hw.memsize, and vm.swapusage.
        """
        blank = {'free_pct': None, 'swap_gb': None}
        if host != 'local' and not ssh_target:
            return blank
        key = (host, ssh_target)
        cached = self._cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < self.ttl:
            return cached[1]
        try:
            if host == 'local':
                values = (_run(['vm_stat']), _run(['sysctl', 'hw.memsize']),
                          _run(['sysctl', 'vm.swapusage']))
            else:
                # Flatten vm_stat into one line so the three probe values have
                # unambiguous boundaries in a single SSH response.
                command = ("vm_stat | tr '\\n' ' '; printf '\\n'; "
                           'sysctl hw.memsize; sysctl vm.swapusage')
                output = _run([self.ssh, '-o', 'StrictHostKeyChecking=accept-new',
                               '-o', 'ConnectTimeout=3', ssh_target, command])
                values = output.splitlines()
                if len(values) != 3:
                    raise ValueError('Incomplete remote memory probe')
            value = _memory(*values)
        except (OSError, subprocess.SubprocessError, ValueError):
            value = blank
        self._cache[key] = (time.monotonic(), value)
        return value


def running_workers(workers_by_host: dict, terminals_by_host: dict) -> dict[str, int]:
    """Count active dispatches where their terminal lives, ignoring worker.host."""
    counts = dict.fromkeys(list(workers_by_host) + list(terminals_by_host), 0)
    handles = {host: {terminal['handle'] for terminal in terminals}
               for host, terminals in terminals_by_host.items()}
    seen = set()
    for workers in workers_by_host.values():
        for worker in workers:
            handle = worker.get('agentTerminalHandle')
            if not handle or worker.get('workerState') in ('settled', 'released', 'abandoned'):
                continue
            dispatch = worker.get('dispatchId') or worker.get('id') or handle
            for host, terminals in handles.items():
                key = (host, dispatch)
                if handle in terminals and key not in seen:
                    counts[host] += 1
                    seen.add(key)
    return counts
