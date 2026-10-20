from __future__ import annotations

"""Infer clusters and atomically persist node assignments and promotions."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile

CONFIG_PATH = Path.home() / '.config' / 'nekotron' / 'fleet-map.json'


def short_name(name: str) -> str:
    """Summarize an inferred name without pasted context or commit hash tokens."""
    cleaned = re.sub(r'^\s*<([A-Za-z_][\w:.-]*)\b[^>]*>(?:.*?</\1\s*>)?',
                     '', name, count=1, flags=re.DOTALL)
    words = [word for word in cleaned.split()
             if not re.fullmatch(r'[0-9a-fA-F]{32,}', word)]
    if not words:
        return name
    return ' '.join(words[:5]) + ('…' if len(words) > 5 else '')


@dataclass
class ClusterConfig:
    initiatives: list[tuple[str, list[str]]]
    assign: dict[str, str]
    projects: list[dict] = field(default_factory=list)
    hosts: dict[str, dict] = field(default_factory=dict)
    caps: dict[str, int] = field(default_factory=dict)
    providers: dict | None = None
    notes: list[str] = field(default_factory=list)


def _node_id(node_id: str) -> str:
    return node_id if ':' in node_id else f'local:sid:{node_id}'


def _read_config(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


def load(path=CONFIG_PATH) -> ClusterConfig:
    """Load rules, pins, projects, hosts, caps and providers; a missing file is empty.

    Canonical node IDs take precedence when a bare session alias also exists.
    Invalid JSON and I/O errors propagate so damaged config is not overwritten.
    """
    data = _read_config(path)
    assignments = data.get('assign', {})
    normalized = {_node_id(key): value for key, value in assignments.items()}
    normalized.update({key: value for key, value in assignments.items() if ':' in key})
    projects = data.get('projects', [])
    for project in projects:
        for item in project.get('slices', []):
            item['sessions'] = [_node_id(session) for session in item.get('sessions', [])]
    return ClusterConfig(
        [(entry['name'], entry['match']) for entry in data.get('initiatives', [])],
        normalized, projects, data.get('hosts', {}), data.get('caps', {}),
        data.get('providers'),
        [f'unknown provider: {name}' for name in (data.get('providers') or {})
         if name not in ('engineering_os', 'directory')])


def _write_config(data, path):
    """Replace one complete document; failed writes leave the old file intact."""
    path = Path(path)
    encoded = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_assign(node_id: str, initiative: str, path=CONFIG_PATH):
    """Pin a node, preserving all other config values and assignments."""
    data = _read_config(path)
    data.setdefault('assign', {})[_node_id(node_id)] = initiative
    _write_config(data, path)


def _remove_membership(projects, canonical, keep=None):
    # Retain project/slice metadata, including empty slices, for future use.
    for project in projects:
        for item in project.get('slices', []):
            if item is not keep and any(_node_id(session) == canonical
                                         for session in item.get('sessions', [])):
                item['sessions'] = [session for session in item['sessions']
                                    if _node_id(session) != canonical]


def promote(node_id: str, project: str, slice_name: str, stage: str, path=CONFIG_PATH):
    """Pin a node and set its project slice's stage in a single atomic write.

    Repeated promotion updates the slice; moving slices removes old membership.
    Other sessions in the destination slice share its hand-set stage.
    """
    data = _read_config(path)
    canonical = _node_id(node_id)
    projects = data.setdefault('projects', [])
    entry = next((entry for entry in projects if entry['name'] == project), None)
    if entry is None:
        entry = {'name': project, 'slices': []}
        projects.append(entry)
    slices = entry.setdefault('slices', [])
    item = next((item for item in slices if item['name'] == slice_name), None)
    if item is None:
        item = {'name': slice_name, 'sessions': []}
        slices.append(item)
    _remove_membership(projects, canonical, keep=item)
    sessions = item.setdefault('sessions', [])
    if not any(_node_id(session) == canonical for session in sessions):
        sessions.append(canonical)
    item['stage'] = stage
    data.setdefault('assign', {})[canonical] = project
    _write_config(data, path)


def move(node_id: str, cluster: str, path=CONFIG_PATH):
    """Pin a node, dropping its promotion membership for a non-project target."""
    data = _read_config(path)
    canonical = _node_id(node_id)
    data.setdefault('assign', {})[canonical] = cluster
    projects = data.get('projects', [])
    if not any(project['name'] == cluster for project in projects):
        _remove_membership(projects, canonical)
    _write_config(data, path)


def _project_slice(node_id, config):
    canonical = _node_id(node_id)
    for project in config.projects:
        for item in project.get('slices', []):
            if any(_node_id(session) == canonical for session in item.get('sessions', [])):
                return project, item
    return None


def update_stage(node_id: str, stage: str, path=CONFIG_PATH):
    """Change the existing slice's stage without creating or moving membership."""
    data = _read_config(path)
    config = ClusterConfig([], {}, projects=data.get('projects', []))
    membership = _project_slice(node_id, config)
    if membership is None:
        raise ValueError('Session is no longer in a project slice')
    membership[1]['stage'] = stage
    _write_config(data, path)


def stage_for(node_id: str, config: ClusterConfig) -> str | None:
    """Return a hand-set stage; callers use a run projection's stage first."""
    membership = _project_slice(node_id, config)
    return membership[1].get('stage') if membership is not None else None


def cluster_for(node_id: str, *, run_objective: str | None, title: str,
                purpose: str | None, worktree: str, branch: str,
                config: ClusterConfig, projection_cluster: str | None = None,
                repository: str | None = None) -> str:
    """Resolve projection, pin/project, run objective, match, repository, Unsorted.

    A None purpose means no human prompt, so worktree inference is skipped.
    The legacy run-objective fallback remains for runs without a projection.
    """
    if projection_cluster is not None:
        return projection_cluster
    canonical = _node_id(node_id)
    if canonical in config.assign:
        return config.assign[canonical]
    if canonical.startswith('local:sid:'):
        bare = canonical[len('local:sid:'):]
        if bare in config.assign:
            return config.assign[bare]
    membership = _project_slice(canonical, config)
    if membership is not None:
        return membership[0]['name']
    if run_objective:
        return re.split('[:;]', run_objective, maxsplit=1)[0][:60]
    fields = [(value or '').casefold() for value in (title, purpose, worktree, branch)]
    for name, patterns in config.initiatives:
        if any(pattern.casefold() in value for pattern in patterns for value in fields):
            return name
    if purpose is not None and repository:
        return repository
    return 'Unsorted'
