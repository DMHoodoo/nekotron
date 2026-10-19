"""Transcript facts from bounded initial reads and complete appended lines."""
import builtins
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.transcript import TranscriptFacts, is_hassan_prompt, read_transcript

FIX = ROOT / 'tests/fixtures/fleetmap/session.jsonl'


def iso(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def record(kind, content, timestamp='2026-10-19T10:09:00Z', **extra):
    return dict(type=kind, timestamp=timestamp,
                message={'role': kind, 'content': content}, **extra)


def assistant_tool_use(name, inputs, timestamp='2026-10-19T10:09:00Z'):
    return record('assistant', [{'type': 'tool_use', 'name': name, 'input': inputs}], timestamp)


def append_line(path, value):
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(value, ensure_ascii=False) + '\n')


class ObservedFile:
    """Observe byte ranges read at the filesystem boundary."""
    def __init__(self, fh, reads):
        self.fh = fh
        self.reads = reads

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.fh.close()

    def __getattr__(self, name):
        return getattr(self.fh, name)

    def read(self, *args):
        start = self.fh.tell()
        data = self.fh.read(*args)
        self.reads.append((start, len(data)))
        return data

    def readline(self, *args):
        start = self.fh.tell()
        data = self.fh.readline(*args)
        self.reads.append((start, len(data)))
        return data


class TranscriptReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='fleetmap-transcript-')
        self.addCleanup(self.tmp.cleanup)
        self.copy = Path(self.tmp.name) / 'session.jsonl'
        shutil.copyfile(FIX, self.copy)

    def test_first_read_extracts_all_fields(self):
        f = read_transcript(FIX)
        self.assertEqual(f.title, 'Handoff scheduling run')
        self.assertEqual(f.purpose, 'Review PR 6869 under run 20261007')
        self.assertEqual(f.doing, 'SendMessage: PR Review')
        self.assertEqual(f.last_said, 'Review complete. The checks passed.')
        self.assertEqual(f.you_at, iso('2026-10-19T10:00:00Z'))
        self.assertEqual(f.it_at, iso('2026-10-19T10:08:00Z'))
        self.assertEqual(f.outbound, [(iso('2026-10-19T10:06:00Z'), 'PR Review')])
        self.assertEqual(f.inbound, [(iso('2026-10-19T10:07:00Z'), 'uds:/tmp/cc-socks/19452.sock')])
        self.assertEqual(len(f.moves), 4)
        self.assertEqual([label for _, label in f.moves], [
            'said: Review complete. The checks passed.', 'SendMessage: PR Review',
            'Bash: Run gate:ratchet', 'said: I will review the PR and run its checks.'])
        self.assertEqual(f.offset, FIX.stat().st_size)

    def test_meta_peer_record_is_not_hassan(self):
        self.assertFalse(is_hassan_prompt(record('user', 'x', isMeta=True, turnOrigin='peer')))

    def test_hassan_prompt_rules(self):
        for origin in (None, 'human'):
            with self.subTest(origin=origin):
                self.assertTrue(is_hassan_prompt(record('user', 'x', turnOrigin=origin)))
                self.assertTrue(is_hassan_prompt(record('user', [{'type': 'text', 'text': 'x'}], turnOrigin=origin)))
        for value in (record('assistant', 'x'), record('user', 'x', isMeta=True),
                      record('user', 'x', turnOrigin='peer'),
                      record('user', 'x', turnOrigin='task_notification'),
                      record('user', 'x', turnOrigin='scheduled'),
                      record('user', [{'type': 'tool_result', 'content': 'x'}, {'type': 'text', 'text': 'x'}]),
                      record('user', [{'type': 'thinking', 'thinking': 'x'}]), {}):
            with self.subTest(value=value):
                self.assertFalse(is_hassan_prompt(value))

    def test_incremental_read_only_parses_appended_bytes(self):
        first = read_transcript(self.copy)
        append_line(self.copy, assistant_tool_use('Read', {'file_path': '/a'}))
        real_open = builtins.open
        reads = []
        with patch('builtins.open', side_effect=lambda *a, **kw: ObservedFile(real_open(*a, **kw), reads)):
            second = read_transcript(self.copy, first)
        self.assertTrue(reads)
        self.assertTrue(all(offset >= first.offset for offset, _ in reads))
        self.assertEqual(sum(size for _, size in reads), self.copy.stat().st_size - first.offset)
        self.assertEqual(second.doing, 'Read: /a')
        self.assertEqual(second.purpose, first.purpose)
        self.assertEqual(second.title, first.title)
        self.assertGreater(second.offset, first.offset)
        self.assertEqual(first.offset, FIX.stat().st_size)
        self.assertEqual(first.outbound, second.outbound)
        self.assertEqual(first.inbound, second.inbound)

    def test_partial_trailing_line_keeps_offset_at_last_newline(self):
        first = read_transcript(self.copy)
        with open(self.copy, 'ab') as fh:
            fh.write(b'{"type":"assistant","mess')
        second = read_transcript(self.copy, first)
        self.assertEqual(second.offset, first.offset)
        self.assertEqual(second.doing, first.doing)
        with open(self.copy, 'ab') as fh:
            fh.write(b'age":{"content":"Completed later"},"timestamp":"2026-10-19T10:10:00Z"}\n')
        third = read_transcript(self.copy, second)
        self.assertEqual(third.last_said, 'Completed later')
        self.assertEqual(third.offset, self.copy.stat().st_size)
        self.assertEqual(sum(label == 'said: Completed later' for _, label in third.moves), 1)

    def test_large_first_open_still_finds_purpose(self):
        self.copy.write_bytes(b'')
        append_line(self.copy, {'type': 'ai-title', 'aiTitle': 'Handoff scheduling run'})
        append_line(self.copy, record('user', 'Review PR 6869 under run 20261007', '2026-10-19T10:00:00Z'))
        header_size = self.copy.stat().st_size
        append_line(self.copy, record('user', [{'type': 'tool_result', 'content': 'x' * (6 * 1024 * 1024)}]))
        append_line(self.copy, assistant_tool_use('Read', {'file_path': '/tail'}))
        real_open = builtins.open
        reads = []
        with patch('builtins.open', side_effect=lambda *a, **kw: ObservedFile(real_open(*a, **kw), reads)):
            f = read_transcript(self.copy, treat_dispatch_prompt_as_hassan=False)
        self.assertLessEqual(sum(size for _, size in reads), header_size + 4 * 1024 * 1024 + 1)
        self.assertEqual(f.purpose, 'Review PR 6869 under run 20261007')
        self.assertEqual(f.title, 'Handoff scheduling run')
        self.assertEqual(f.doing, 'Read: /tail')
        self.assertEqual(f.moves, [(iso('2026-10-19T10:09:00Z'), 'Read: /tail')])
        self.assertIsNone(f.you_at)
        self.assertEqual(f.offset, self.copy.stat().st_size)

    def test_initial_tail_preserves_a_line_exactly_at_its_boundary(self):
        self.copy.write_bytes(b'')
        append_line(self.copy, record('user', 'Purpose'))
        with open(self.copy, 'ab') as fh:
            fh.write(b'x' * (5 * 1024 * 1024) + b'\n')
            line = json.dumps(assistant_tool_use('Read', {'file_path': '/boundary'})).encode() + b'\n'
            fh.write(line + b'\n' * (4 * 1024 * 1024 - len(line)))
        f = read_transcript(self.copy)
        self.assertEqual(f.doing, 'Read: /boundary')
        self.assertEqual(f.offset, self.copy.stat().st_size)

    def test_initial_read_does_not_consume_a_partial_prompt(self):
        line = json.dumps(record('user', 'Pending purpose')).encode()
        self.copy.write_bytes(line)
        first = read_transcript(self.copy, treat_dispatch_prompt_as_hassan=False)
        self.assertIsNone(first.purpose)
        self.assertEqual(first.offset, 0)
        with open(self.copy, 'ab') as fh:
            fh.write(b'\n')
        second = read_transcript(self.copy, first, treat_dispatch_prompt_as_hassan=False)
        self.assertEqual(second.purpose, 'Pending purpose')
        self.assertIsNone(second.you_at)

    def test_dispatch_prompt_is_ignored_only_for_you_age(self):
        first = read_transcript(self.copy, treat_dispatch_prompt_as_hassan=False)
        self.assertIsNone(first.you_at)
        self.assertEqual(first.purpose, 'Review PR 6869 under run 20261007')
        append_line(self.copy, record('user', 'Follow up', '2026-10-19T10:10:00Z'))
        second = read_transcript(self.copy, first, treat_dispatch_prompt_as_hassan=False)
        self.assertEqual(second.you_at, iso('2026-10-19T10:10:00Z'))
        self.assertEqual(second.purpose, first.purpose)
        self.assertIsNone(first.you_at)

    def test_wrapper_counts_as_human_but_not_as_purpose(self):
        self.copy.write_bytes(b'')
        append_line(self.copy, record('user', '<wrapper>injected</wrapper>'))
        first = read_transcript(self.copy)
        self.assertIsNone(first.purpose)
        self.assertEqual(first.you_at, iso('2026-10-19T10:09:00Z'))
        first_worker = read_transcript(self.copy, treat_dispatch_prompt_as_hassan=False)
        append_line(self.copy, record('user', 'Actual purpose', '2026-10-19T10:10:00Z'))
        second = read_transcript(self.copy, first_worker, treat_dispatch_prompt_as_hassan=False)
        self.assertEqual(second.purpose, 'Actual purpose')
        self.assertEqual(second.you_at, iso('2026-10-19T10:10:00Z'))

    def test_empty_transcript_can_be_followed_with_dispatch_policy(self):
        self.copy.write_bytes(b'')
        first = read_transcript(self.copy, treat_dispatch_prompt_as_hassan=False)
        self.assertEqual(first, TranscriptFacts())
        append_line(self.copy, record('user', 'Dispatch'))
        second = read_transcript(self.copy, first, treat_dispatch_prompt_as_hassan=False)
        self.assertEqual(second.purpose, 'Dispatch')
        self.assertIsNone(second.you_at)

    def test_malformed_records_do_not_hide_later_valid_records(self):
        with open(self.copy, 'ab') as fh:
            fh.write(b'not json\n[]\nnull\n\xff\n')
        for value in ({'type': 'assistant', 'message': None},
                      record('assistant', [None, {'type': 'tool_use', 'input': None}]),
                      record('assistant', 'Bad time', 'invalid')):
            append_line(self.copy, value)
        append_line(self.copy, assistant_tool_use('Read', {'file_path': '/valid'}))
        f = read_transcript(self.copy)
        self.assertEqual(f.doing, 'Read: /valid')
        self.assertEqual(f.offset, self.copy.stat().st_size)

    def test_tool_argument_priority_and_truncation(self):
        for inputs, expected in (({'description': 'Explain', 'to': 'target'}, 'Explain'),
                                 ({'to': 'target', 'file_path': '/a'}, 'target'),
                                 ({'file_path': '/a', 'command': 'pwd'}, '/a'),
                                 ({'command': 'pwd', 'pattern': 'x'}, 'pwd'),
                                 ({'pattern': 'x' * 80}, 'x' * 60),
                                 ({'description': '', 'command': 'pwd'}, '')):
            with self.subTest(inputs=inputs):
                self.copy.write_bytes(b'')
                append_line(self.copy, assistant_tool_use('Tool', inputs))
                self.assertEqual(read_transcript(self.copy).doing, 'Tool: ' + expected)

    def test_text_only_session_and_recent_moves(self):
        self.copy.write_bytes(b'')
        for minute in range(7):
            append_line(self.copy, record('assistant', str(minute) * 80, f'2026-10-19T10:0{minute}:00Z'))
        f = read_transcript(self.copy)
        self.assertEqual(f.doing, '6' * 60)
        self.assertEqual(f.last_said, '6' * 80)
        self.assertEqual([label for _, label in f.moves], ['said: ' + str(n) * 60 for n in (6, 5, 4, 3, 2)])

    def test_multibyte_partial_line_and_noop_reads(self):
        first = read_transcript(self.copy)
        line = json.dumps(record('assistant', 'Café ☕'), ensure_ascii=False).encode('utf-8')
        split = line.index('☕'.encode('utf-8')) + 1
        with open(self.copy, 'ab') as fh:
            fh.write(line[:split])
        partial = read_transcript(self.copy, first)
        self.assertEqual(partial.offset, first.offset)
        with open(self.copy, 'ab') as fh:
            fh.write(line[split:] + b'\n')
        complete = read_transcript(self.copy, partial)
        self.assertEqual(complete.last_said, 'Café ☕')
        self.assertEqual(complete.offset, self.copy.stat().st_size)
        self.assertEqual(read_transcript(self.copy, complete), complete)


if __name__ == '__main__':
    unittest.main()
