from __future__ import annotations

"""Read-only overlays for the fleet collector.

StaleChecker.check(p, row, branch=None) accepts a gate-shaped row (verdict,
headSha); a branch selects the slice head, otherwise the run's PR is checked.
is_stalled uses the collector's activity_changed_at epoch-seconds stamp, updated
whenever it_at, transcript offset, or last_output_at changes. A working node is
stalled only when that stamp is present and at least window seconds old; the
prev_node argument is retained for compatibility and ignored. Neither helper
changes the projection or snapshot records.
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

    def check(self, p: Projection, row: dict, branch: str | None = None) -> dict | None:
        """Compare passed evidence with a remote head, without fetching objects.

        Missing worktrees, missing targets, and failed head probes mean no check.
        A moved head remains reportable when its commit range is unavailable.
        """
        old = row.get('headSha')
        worktree = p.runPlan.get('worktree')
        number, repo = p.pr.get('number'), p.pr.get('repo')
        if (row.get('verdict') != 'pass' or not _sha(old) or not worktree
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
    """Require a working node and an activity_changed_at stamp aged by window.

    The collector updates the epoch-seconds stamp whenever it_at, transcript
    offset, or last_output_at changes. No stamp means no stall evidence;
    prev_node is ignored and retained only for signature compatibility.
    """
    stamp = node.get('activity_changed_at')
    return node.get('state') == 'working' and stamp is not None and now - stamp >= window


def _memory(vm_stat: str, memsize: str, swapusage: str) -> dict:
    page_size = re.search(r'page size of\s+(\d+)\s+bytes', vm_stat)
    available_pages = [re.search(r'Pages ' + kind + r':\s+(\d+)\.', vm_stat)
                       for kind in ('free', 'inactive', 'speculative')]
    total = re.fullmatch(r'(?:hw\.memsize:\s*)?(\d+)', memsize.strip())
    swap = re.search(r'\bused\s*=\s*(\d+(?:\.\d+)?)\s*([BKMGTP])\b', swapusage)
    if not all((page_size, total, swap, *available_pages)):
        raise ValueError('Incomplete memory probe')
    total_bytes = int(total[1])
    page_bytes = int(page_size[1])
    free_bytes = sum(int(pages[1]) for pages in available_pages) * page_bytes
    if total_bytes <= 0 or page_bytes <= 0 or free_bytes > total_bytes:
        raise ValueError('Invalid memory probe')
    # macOS can reclaim inactive and speculative pages for new work.
    return {'free_pct': free_bytes * 100.0 / total_bytes,
            'swap_gb': float(swap[1]) * 1024 ** ('BKMGTP'.index(swap[2]) - 3)}


class MemoryProbe:
    def __init__(self, ssh: str = 'ssh', ttl: float = 15.0):
        self.ssh = ssh
        self.ttl = ttl
        self._cache: dict[tuple, tuple[float, dict]] = {}

    def probe(self, host: str, ssh_target: str | None) -> dict:
        """Read free + inactive + speculative page percentage and swap GiB.

        Failures return None for both measurements.
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
