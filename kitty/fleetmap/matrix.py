from __future__ import annotations

"""Build evidence matrices, retaining usable data when validation is bypassed."""
from .edges import Resolver
from .projection import GATE_IDS, PACKAGE_STATES, Projection, STAGES, VERDICTS

REVIEW_GATES = ('test-quality', 'code-standards', 'commenting', 'general-code')
SIZE_UNITS = {'S': 1, 'M': 2, 'L': 3}


def _records(value, path, notes, valid):
    """Filter malformed containers and records before consumers access fields."""
    if not isinstance(value, list):
        notes.append(f'{path}: expected list; using empty list')
        return []
    result = []
    for index, record in enumerate(value):
        if not isinstance(record, dict) or not valid(record):
            notes.append(f'{path}[{index}]: malformed record; skipped')
        else:
            result.append(record)
    return result


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _nullable_string(value):
    return value is None or isinstance(value, str)


def _valid_package(record):
    # Size values are normalized separately; missing required fields skip the record.
    return (
        'size' in record
        and all(isinstance(record.get(key), str) for key in
                ('id', 'slice', 'title', 'checkpointEvidence', 'verifier'))
        and record.get('state') in PACKAGE_STATES
        and all(key in record and _nullable_string(record[key])
                for key in ('dispatchId', 'machine', 'branch'))
        and all(_strings(record.get(key)) for key in ('blockedBy', 'proofs'))
        and all(_nullable_string(record.get(key))
                for key in ('headSha', 'lastEvent', 'lastEventAt')))


def _valid_slice(record):
    return (all(isinstance(record.get(key), str) for key in ('id', 'name'))
            and 'stage' in record and isinstance(record.get('gates'), list)
            and _strings(record.get('packages'))
            and _nullable_string(record.get('branch')))


def _gate_index(value, path, notes):
    records = _records(value, path, notes, lambda gate: (
        isinstance(gate.get('id'), str) and gate['id'] in GATE_IDS
        and gate.get('verdict') in VERDICTS and 'at' in gate
        and all(_nullable_string(gate.get(key)) for key in ('at', 'ref', 'headSha'))))
    return {gate['id']: gate for gate in records}


def _acceptance(value, notes):
    if (isinstance(value, dict) and value.get('state') in ('pending', 'accepted', 'merged')
            and all(_nullable_string(value.get(key)) for key in ('at', 'by'))):
        return dict(value)
    notes.append('acceptance: malformed record; using pending')
    return {'state': 'pending'}


def derive_stage(projection: Projection) -> str:
    """Place a run without slices using its gate evidence and acceptance."""
    if _acceptance(projection.acceptance, [])['state'] in ('accepted', 'merged'):
        return 'accepted'
    gates = _gate_index(projection.gates, 'gates', [])
    if gates.get('delivery', {}).get('verdict') == 'pass':
        return 'delivery'
    if any(gate_id in gates for gate_id in REVIEW_GATES):
        return 'review'
    for stage in ('goal', 'design', 'plan'):
        if gates.get(stage, {}).get('verdict') != 'pass':
            return stage
    return 'implementing'


def _gate_cell(gates, gate_id):
    gate = gates.get(gate_id, {})
    return {'verdict': gate.get('verdict', 'pending'), 'at': gate.get('at'),
            'ref': gate.get('ref'), 'stale': None}


def build_matrix(p: Projection, resolver: Resolver) -> dict:
    """Build ordered slice rows; only independently verified units earn credit.

    Slice package lists define membership and ordering. Without slices, all
    packages belong to the run row. Staleness and stalls are later overlays.
    """
    notes = []
    packages = {package['id']: package for package in
                _records(p.packages, 'packages', notes, _valid_package)}
    slices = _records(p.slices, 'slices', notes, _valid_slice)
    run_gates = _gate_index(p.gates, 'gates', notes)
    acceptance = _acceptance(p.acceptance, notes)
    metadata = {}
    for key, value in (('run', p.run), ('title', p.title), ('now', p.now)):
        if not isinstance(value, str):
            notes.append(f'{key}: expected string; using empty string')
            value = ''
        metadata[key] = value
    if not slices:
        slices = [{'id': metadata['run'], 'name': metadata['title'], 'stage': derive_stage(p),
                   'gates': [], 'packages': list(packages)}]
    rows = []
    for slice_record in slices:
        gates = dict(run_gates)
        gates.update(_gate_index(slice_record['gates'], f"slice {slice_record['id']}.gates", notes))
        segments = []
        live = []
        verified_units = total_units = 0
        for package_id in slice_record['packages']:
            package = packages.get(package_id)
            if package is None:
                notes.append(f"slice {slice_record['id']}: unknown package {package_id}; skipped")
                continue
            size = package['size']
            if isinstance(size, str) and size in SIZE_UNITS:
                units = SIZE_UNITS[size]
            else:
                units = 1
                notes.append(f"package {package_id}: unknown size {package['size']}; using weight 1")
            node = None
            if package['dispatchId']:
                node = resolver.node_for_handle('dispatch:' + package['dispatchId'],
                                                package['machine'] or 'local')
            segments.append({'id': package_id, 'size': units,
                             'state': package['state'], 'node': node})
            total_units += units
            if package['state'] == 'verified':
                verified_units += units
            if node is not None and node not in live:
                live.append(node)
        cells = {stage: _gate_cell(gates, stage) for stage in ('goal', 'design', 'plan')}
        cells['implementing'] = {'segments': segments, 'verified_units': verified_units,
                                 'total_units': total_units}
        cells['review'] = {'chips': [dict(id=gate_id, **_gate_cell(gates, gate_id))
                                     for gate_id in REVIEW_GATES]}
        cells['delivery'] = _gate_cell(gates, 'delivery')
        cells['accepted'] = dict(acceptance)
        stage = slice_record['stage']
        if not isinstance(stage, str) or stage not in STAGES:
            notes.append(f"slice {slice_record['id']}: unknown stage {stage}; using goal")
            stage = 'goal'
        stage_index = STAGES.index(stage)
        rows.append({'id': slice_record['id'], 'name': slice_record['name'],
                     'stage': stage,
                     'stepper': [int(i <= stage_index) for i in range(len(STAGES))],
                     'cells': cells, 'live': live})
    decisions = _records(p.decisions, 'decisions', notes,
                         lambda decision: decision.get('class') in ('B', 'C', 'D'))
    proofs = _records(p.proofs, 'proofs', notes, lambda proof: all(
        isinstance(proof.get(key), str) for key in ('id', 'status')))
    merge_gate = p.mergeGate
    if (not isinstance(merge_gate, dict) or type(merge_gate.get('ready')) is not bool
            or any(type(merge_gate.get(key)) is not int
                   for key in ('classDOpen', 'classBUnratified'))):
        notes.append('mergeGate: malformed record; using not ready')
        merge_gate = {'ready': False, 'classDOpen': 0, 'classBUnratified': 0}
    chief = p.chiefTerminal
    if not isinstance(chief, str):
        notes.append('chiefTerminal: expected string; no Chief node')
        chief = ''
    return dict(metadata, chief_node=resolver.node_for_handle(chief, 'local'),
                waiting=len(decisions), stalled=0, proofs=[dict(proof) for proof in proofs],
                merge_gate=dict(merge_gate), rows=rows, notes=notes)
