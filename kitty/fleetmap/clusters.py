"""Infer initiative clusters and persist explicit node assignments."""
from dataclasses import dataclass
import json
from pathlib import Path
import re

CONFIG_PATH = Path.home() / '.config' / 'nekotron' / 'fleet-map.json'


@dataclass
class ClusterConfig:
    initiatives: list[tuple[str, list[str]]]
    assign: dict[str, str]


def _node_id(node_id: str) -> str:
    return node_id if ':' in node_id else f'local:sid:{node_id}'


def _read_config(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


def load(path=CONFIG_PATH) -> ClusterConfig:
    """Load ordered match rules and pins; a missing file is an empty config.

    Canonical node IDs take precedence when a bare session alias also exists.
    Invalid JSON and I/O errors propagate so damaged config is not overwritten.
    """
    data = _read_config(path)
    assignments = data.get('assign', {})
    normalized = {_node_id(key): value for key, value in assignments.items()}
    normalized.update({key: value for key, value in assignments.items() if ':' in key})
    return ClusterConfig(
        [(entry['name'], entry['match']) for entry in data.get('initiatives', [])],
        normalized)


def save_assign(node_id: str, initiative: str, path=CONFIG_PATH):
    """Pin a node, preserving all other config values and assignments."""
    path = Path(path)
    data = _read_config(path)
    data.setdefault('assign', {})[_node_id(node_id)] = initiative
    encoded = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding='utf-8')


def cluster_for(node_id: str, *, run_objective: str | None, title: str,
                purpose: str, worktree: str, branch: str,
                config: ClusterConfig) -> str:
    """Resolve pins, run objective, ordered patterns, then worktree branch.

    Callers decide which sessions are eligible for clustering; this function
    does not inspect transcripts or query Orca.
    """
    canonical = _node_id(node_id)
    if canonical in config.assign:
        return config.assign[canonical]
    if canonical.startswith('local:sid:'):
        bare = canonical[len('local:sid:'):]
        if bare in config.assign:
            return config.assign[bare]
    if run_objective:
        return re.split('[:;]', run_objective, maxsplit=1)[0][:60]
    fields = [value.casefold() for value in (title, purpose, worktree, branch)]
    for name, patterns in config.initiatives:
        if any(pattern.casefold() in value for pattern in patterns for value in fields):
            return name
    if worktree and branch:
        return branch.removeprefix('refs/heads/').rsplit('/', 1)[-1]
    return 'Unsorted'
