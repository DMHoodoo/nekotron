from __future__ import annotations

"""Read the Chief's schema v2 run projections without inferring plan progress."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path

PROGRESS_DIR = Path.home() / '.glow' / 'orca-progress'
REQUIRED_FIELDS = (
    'schemaVersion', 'run', 'title', 'updatedAt', 'runPlan', 'pr', 'acceptance',
    'chiefTerminal', 'now', 'statusCard', 'decisions', 'gates', 'mergeGate',
    'proofs', 'slices', 'packages',
)
STAGES = ('goal', 'design', 'plan', 'implementing', 'review', 'delivery', 'accepted')
PACKAGE_STATES = ('planned', 'assigned', 'running', 'returned', 'verified', 'blocked')
SIZES = ('S', 'M', 'L')
GATE_IDS = ('goal', 'design', 'plan', 'test-quality', 'code-standards',
            'commenting', 'general-code', 'delivery')
VERDICTS = ('pass', 'revise', 'pending')


@dataclass
class Projection:
    """Reference H fields, preserving nested records and optional-field omissions."""

    schemaVersion: int
    run: str
    title: str
    updatedAt: str
    runPlan: dict
    pr: dict
    acceptance: dict
    chiefTerminal: str
    now: str
    statusCard: dict
    decisions: list[dict]
    gates: list[dict]
    mergeGate: dict
    proofs: list[dict]
    slices: list[dict]
    packages: list[dict]
    path: str
    mtime: float
    caps: dict[str, int] = field(default_factory=dict)


def validate(data: dict) -> list[str]:
    """Return every Reference H violation; safe for malformed JSON value shapes.

    Keep this function self-contained: the lab renderer copies its source and
    checks it byte for byte. Schema vocabulary is repeated here intentionally so
    that the copied validator needs no module globals or companion helpers.
    """
    from datetime import datetime
    from posixpath import isabs

    nullable_string = (str, type(None))
    stages = ('goal', 'design', 'plan', 'implementing', 'review', 'delivery', 'accepted')
    states = ('planned', 'assigned', 'running', 'returned', 'verified', 'blocked')
    sizes = ('S', 'M', 'L')
    gate_ids = ('goal', 'design', 'plan', 'test-quality', 'code-standards',
                'commenting', 'general-code', 'delivery')
    verdicts = ('pass', 'revise', 'pending')
    gate = {
        'id': ('GATE_IDS', gate_ids), 'verdict': ('VERDICTS', verdicts),
        'at': nullable_string, 'ref?': nullable_string, 'headSha?': nullable_string,
    }
    schema = {
        'schemaVersion': int,
        'run': str, 'title': str, 'updatedAt': str,
        'runPlan': {'path': str, 'commit': str, 'worktree': str},
        'pr': {'repo': str, 'number?': (int, type(None))},
        'acceptance': {
            'state': ('pending, accepted, merged', ('pending', 'accepted', 'merged')),
            'at?': nullable_string, 'by?': nullable_string,
        },
        'chiefTerminal': str, 'now': str,
        'statusCard': {'done': str, 'running': str, 'blockedOn': str, 'nextCheckpoint': str},
        'decisions': [{
            'id': str, 'class': ('B, C, D', ('B', 'C', 'D')), 'text': str,
            'packet?': nullable_string, 'applyAt?': nullable_string,
        }],
        'gates': [gate],
        'mergeGate': {'ready': bool, 'classDOpen': int, 'classBUnratified': int},
        'proofs': [{'id': str, 'status': str}],
        'caps?': dict,
        'slices': [{
            'id': str, 'name': str, 'stage': ('STAGES', stages),
            'branch?': nullable_string, 'gates': [gate], 'packages': [str],
        }],
        'packages': [{
            'id': str, 'slice': str, 'title': str, 'size': str,
            'state': ('PACKAGE_STATES', states), 'dispatchId': nullable_string,
            'machine': nullable_string, 'branch': nullable_string,
            'headSha?': nullable_string, 'blockedBy': [str], 'proofs': [str],
            'checkpointEvidence': str, 'verifier': str,
            'lastEvent?': nullable_string, 'lastEventAt?': nullable_string,
        }],
    }
    errors = []

    def check(value, rule, path):
        if isinstance(rule, dict):
            if not isinstance(value, dict):
                errors.append(f'{path or "$"}: expected object')
                return
            for field_name, child_rule in rule.items():
                optional = field_name.endswith('?')
                key = field_name.rstrip('?')
                child_path = f'{path}.{key}' if path else key
                if key in value:
                    check(value[key], child_rule, child_path)
                elif not optional:
                    errors.append(f'{child_path}: missing')
        elif isinstance(rule, list):
            if not isinstance(value, list):
                errors.append(f'{path}: expected array')
                return
            for index, item in enumerate(value):
                check(item, rule[0], f'{path}[{index}]')
        elif isinstance(rule, tuple) and isinstance(rule[0], str):
            label, vocabulary = rule
            if not isinstance(value, str) or value not in vocabulary:
                errors.append(f'{path}: {value!r} not in {label}')
        else:
            types = rule if isinstance(rule, tuple) else (rule,)
            # bool is an int subclass, but a JSON boolean is not a JSON integer.
            if type(value) not in types:
                names = {str: 'string', int: 'integer', bool: 'boolean',
                         dict: 'object', type(None): 'null'}
                expected = ' or '.join(names[kind] for kind in types)
                errors.append(f'{path}: expected {expected}')

    check(data, schema, '')
    if not isinstance(data, dict):
        return errors
    if type(data.get('schemaVersion')) is int and data['schemaVersion'] != 2:
        errors.append('schemaVersion: expected 2')
    packages = data.get('packages')
    if isinstance(packages, list):
        package_ids = set()
        for index, package in enumerate(packages):
            if not isinstance(package, dict):
                continue
            if isinstance(package.get('id'), str):
                package_ids.add(package['id'])
            size = package.get('size')
            if isinstance(size, str) and size not in sizes:
                errors.append(f'packages[{index}].size: not in SIZES')
        slices = data.get('slices')
        if isinstance(slices, list):
            for index, slice_record in enumerate(slices):
                if not isinstance(slice_record, dict):
                    continue
                references = slice_record.get('packages')
                if not isinstance(references, list):
                    continue
                for ref_index, package_id in enumerate(references):
                    if isinstance(package_id, str) and package_id not in package_ids:
                        errors.append(f'slices[{index}].packages[{ref_index}]: '
                                      f'unknown package {package_id}')
    plan = data.get('runPlan')
    if isinstance(plan, dict) and isinstance(plan.get('worktree'), str):
        if not isabs(plan['worktree']):
            errors.append('runPlan.worktree: expected absolute path')
    caps = data.get('caps')
    if isinstance(caps, dict):
        for machine, cap in caps.items():
            check(cap, int, f'caps.{machine}')
    decisions = data.get('decisions')
    if isinstance(decisions, list):
        for index, decision in enumerate(decisions):
            if not isinstance(decision, dict):
                continue
            apply_at = decision.get('applyAt')
            if isinstance(apply_at, str):
                path = f'decisions[{index}].applyAt'
                if decision.get('class') != 'B':
                    errors.append(f'{path}: must be null unless class is B')
                try:
                    # Python 3.9 does not accept the ISO UTC Z suffix directly.
                    datetime.fromisoformat(apply_at.replace('Z', '+00:00'))
                    if 'T' not in apply_at:
                        raise ValueError('missing time')
                except ValueError:
                    errors.append(f'{path}: expected ISO 8601 time')
    return errors


def load_projections(directory=PROGRESS_DIR) -> tuple[list[Projection], dict[str, str]]:
    """Read each JSON independently, returning valid runs and file diagnostics.

    Files predating schemaVersion are v1. A missing or inaccessible projection
    directory is empty; per-file read failures never hide other valid runs.
    """
    good = []
    bad = {}
    try:
        paths = sorted(Path(directory).glob('*.json'))
    except OSError:
        return good, bad
    for path in paths:
        try:
            with path.open(encoding='utf-8') as source:
                data = json.load(source)
                # Use the same open file for content and metadata if a Chief
                # atomically replaces the path during this read.
                mtime = os.fstat(source.fileno()).st_mtime
        except (OSError, ValueError, RecursionError):
            bad[path.name] = 'unreadable'
            continue
        if isinstance(data, dict):
            version = data.get('schemaVersion', 1)
            if type(version) is not int or version != 2:
                bad[path.name] = f'schemaVersion {version}, Chief must re-render'
                continue
        violations = validate(data)
        if violations:
            bad[path.name] = violations[0]
            continue
        fields = {name: data[name] for name in REQUIRED_FIELDS}
        good.append(Projection(**fields, caps=data.get('caps', {}),
                               path=str(path), mtime=mtime))
    return good, bad
