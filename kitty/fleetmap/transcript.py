"""Read session facts from a transcript without rescanning consumed bytes."""
from dataclasses import dataclass, field, replace
from datetime import datetime
import json
import os
import re

TAIL_BYTES = 4 * 1024 * 1024
_CROSS_SESSION = re.compile(r'''<cross-session-message\b[^>]*?\sfrom\s*=\s*(["'])(.*?)\1''')


@dataclass
class TranscriptFacts:
    title: str | None = None
    purpose: str | None = None
    doing: str | None = None
    last_said: str | None = None
    you_at: float | None = None
    it_at: float | None = None
    moves: list[tuple[float, str]] = field(default_factory=list)
    outbound: list[tuple[float, str]] = field(default_factory=list)
    inbound: list[tuple[float, str]] = field(default_factory=list)
    offset: int = 0
    # These flags survive tail gaps and polls, including files with no purpose yet.
    _human_prompt_seen: bool = field(default=False, repr=False)
    _has_tool: bool = field(default=False, repr=False)

    @classmethod
    def empty(cls):
        return cls()


def _content(record):
    message = record.get('message')
    return message.get('content') if isinstance(message, dict) else None


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(block['text'] for block in content
                         if isinstance(block, dict) and block.get('type') == 'text'
                         and isinstance(block.get('text'), str))
    return ''


def is_hassan_prompt(record: dict) -> bool:
    """Recognize human text, including wrappers but excluding tool results."""
    if (record.get('type') != 'user' or record.get('isMeta')
            or record.get('turnOrigin') not in (None, 'human')):
        return False
    content = _content(record)
    if (isinstance(content, list) and content and isinstance(content[0], dict)
            and content[0].get('type') == 'tool_result'):
        return False
    return bool(_text(content))


def _epoch(record):
    timestamp = record.get('timestamp')
    if not isinstance(timestamp, str):
        return None
    try:
        return datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _move(facts, epoch, label):
    facts.moves.insert(0, (epoch, label))
    facts.moves.sort(key=lambda move: move[0], reverse=True)
    del facts.moves[5:]


def _consume(line, facts, treat_dispatch_prompt_as_hassan):
    if not line.strip():
        return
    try:
        record = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return
    if not isinstance(record, dict):
        return
    kind = record.get('type')
    if kind == 'ai-title' and isinstance(record.get('aiTitle'), str):
        facts.title = record['aiTitle']
    content = _content(record)
    text = _text(content)
    epoch = _epoch(record)
    if is_hassan_prompt(record):
        first = not facts._human_prompt_seen
        facts._human_prompt_seen = True
        if facts.purpose is None and not text.startswith('<'):
            facts.purpose = text
        if epoch is not None and (treat_dispatch_prompt_as_hassan or not first):
            facts.you_at = max(facts.you_at, epoch) if facts.you_at is not None else epoch
    if epoch is None:
        return
    if kind == 'user':
        for match in _CROSS_SESSION.finditer(text):
            facts.inbound.append((epoch, match.group(2)))
    if kind != 'assistant':
        return
    facts.it_at = max(facts.it_at, epoch) if facts.it_at is not None else epoch
    blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
    if not isinstance(blocks, list):
        return
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'text' and isinstance(block.get('text'), str):
            text = block['text']
            if not text:
                continue
            facts.last_said = text
            if not facts._has_tool:
                facts.doing = text[:60]
            _move(facts, epoch, 'said: ' + text[:60])
        elif block.get('type') == 'tool_use' and isinstance(block.get('name'), str):
            inputs = block.get('input')
            if not isinstance(inputs, dict):
                continue
            argument = next((inputs[key] for key in
                             ('description', 'to', 'file_path', 'command', 'pattern')
                             if key in inputs), '')
            label = block['name'] + ': ' + str(argument)[:60]
            facts.doing = label
            facts._has_tool = True
            _move(facts, epoch, label)
            if block['name'] == 'SendMessage' and isinstance(inputs.get('to'), str):
                facts.outbound.append((epoch, inputs['to']))


def read_transcript(path: str, prev: TranscriptFacts | None = None, *,
                    treat_dispatch_prompt_as_hassan: bool = True) -> TranscriptFacts:
    """Scan through the first purpose, then the tail; later polls read new bytes.

    Only complete newline-terminated records advance the byte offset. Initial
    reads omit the middle of large files after finding purpose, so activity and
    message edges in that gap are intentionally absent. Keep the dispatch policy
    unchanged when passing a previous result. The previous result is not mutated.
    """
    facts = (TranscriptFacts.empty() if prev is None else
             replace(prev, moves=list(prev.moves), outbound=list(prev.outbound),
                     inbound=list(prev.inbound)))
    with open(path, 'rb') as fh:
        size = os.fstat(fh.fileno()).st_size
        if prev is None:
            while facts.purpose is None and fh.tell() < size:
                line = fh.readline(size - fh.tell())
                if not line.endswith(b'\n'):
                    return facts
                _consume(line, facts, treat_dispatch_prompt_as_hassan)
                facts.offset = fh.tell()
            start = max(facts.offset, size - TAIL_BYTES)
        else:
            start = facts.offset
        # Read one preceding byte only on an initial tail jump to determine
        # whether its first line is whole. Incremental reads start at the offset.
        skip_fragment = False
        if start > facts.offset:
            fh.seek(start - 1)
            skip_fragment = fh.read(1) != b'\n'
        fh.seek(start)
        data = fh.read(max(0, size - start))
        end = data.rfind(b'\n')
        if end < 0:
            return facts
        lines = data[:end].split(b'\n')
        if skip_fragment:
            lines = lines[1:]
        for line in lines:
            _consume(line, facts, treat_dispatch_prompt_as_hassan)
        facts.offset = start + end + 1
    return facts
