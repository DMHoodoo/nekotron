from __future__ import annotations

"""Load consumer-selected progress sources and retain the newest record per run."""
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Protocol

from ..projection import Projection, parse_projection


class ProgressProvider(Protocol):
    name: str

    def load(self, roots: list[Path]) -> tuple[list[Projection], dict[str, str]]:
        ...


def _read_projection(path):
    try:
        with path.open(encoding='utf-8') as source:
            data = json.load(source)
            # Metadata belongs to this open file even during an atomic replace.
            mtime = os.fstat(source.fileno()).st_mtime
    except (OSError, ValueError, RecursionError) as error:
        raise ValueError('unreadable') from error
    projection = parse_projection(data, mtime)
    projection.path = str(path)
    return projection


def _updated_at(projection):
    try:
        value = datetime.fromisoformat(projection.updatedAt.replace('Z', '+00:00'))
        return value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()
    except (ValueError, OverflowError):
        # The upstream schema accepts any string; unparseable times rank oldest.
        return float('-inf')


def load_from_providers(providers: list[ProgressProvider], roots: list[Path]
                        ) -> tuple[list[Projection], dict[str, str]]:
    selected = {}
    rejected = {}
    for provider in providers:
        projections, bad = provider.load(roots)
        rejected.update(bad)
        for projection in projections:
            label = f'{provider.name}:{projection.path}'
            previous = selected.get(projection.run)
            if previous is None:
                selected[projection.run] = (projection, label)
            elif _updated_at(projection) > _updated_at(previous[0]):
                rejected[previous[1]] = 'superseded'
                selected[projection.run] = (projection, label)
            else:
                rejected[label] = 'superseded'
    return [entry[0] for entry in selected.values()], rejected


def providers_from_config(config) -> list[ProgressProvider]:
    from .directory import DirectoryProvider
    from .engineering_os import EngineeringOsProvider

    settings = config.get('providers') if isinstance(config, dict) else config.providers
    if settings is None:
        return [EngineeringOsProvider(extra_roots=[])]
    providers = []
    for name, options in settings.items():
        if name == 'engineering_os':
            providers.append(EngineeringOsProvider(
                extra_roots=[Path(root).expanduser() for root in options.get('roots', [])]))
        elif name == 'directory':
            providers.append(DirectoryProvider(Path(options['path']).expanduser()))
        else:
            note = f'unknown provider: {name}'
            logging.getLogger(__name__).warning('config: %s', note)
            if not isinstance(config, dict) and note not in config.notes:
                config.notes.append(note)
    return providers
