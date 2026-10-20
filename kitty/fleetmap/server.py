from __future__ import annotations

"""Serve a cached fleet snapshot and terminal actions over authenticated loopback."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .actions import ActionError, Actions
from .clusters import CONFIG_PATH, load, move, promote, save_assign, update_stage
from .model import Collector
from .orca import OrcaClient
from .projection import STAGES
from .providers import providers_from_config

PAGE = Path(__file__).with_name('page.html')
SERVER_INFO = Path.home() / '.config' / 'nekotron' / 'fleet-map.server.json'


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # URLs contain the launch key; never put request paths in access logs.
        pass

    def parse_request(self):
        if not super().parse_request():
            return False
        fleet = self.server.fleet
        with fleet._lock:
            fleet._last_request = time.monotonic()
        self.route = urlsplit(self.path)
        self.query = parse_qs(self.route.query)
        candidates = self.query.get('key', []) + [self.headers.get('X-Fleet-Key', '')]
        # Gate every method before dispatch, including unsupported HTTP methods.
        if not any(secrets.compare_digest(key.encode(), fleet.key.encode()) for key in candidates):
            self._json({'ok': False, 'error': 'Forbidden'}, status=403)
            return False
        return True

    def _respond(self, data, content_type, status=200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value, status=200):
        self._respond(json.dumps(value, ensure_ascii=False).encode('utf-8'),
                      'application/json; charset=utf-8', status)

    def _node(self, node_id):
        if not isinstance(node_id, str) or not node_id:
            raise ValueError('node must be a nonempty string')
        for node in self.server.fleet._snapshot_copy().get('nodes', []):
            if node['id'] == node_id:
                return node
        raise ValueError('node_not_found')

    def do_GET(self):
        # parse_request has checked the key before any route is reached.
        fleet = self.server.fleet
        if self.route.path == '/':
            try:
                page = fleet.page_path.read_bytes()
            except OSError:
                self._json({'ok': False, 'error': 'Page not found'}, status=404)
            else:
                self._respond(page, 'text/html; charset=utf-8')
        elif self.route.path == '/api/state':
            self._json(dict(fleet._snapshot_copy(), poll_seconds=fleet.poll_seconds))
        elif self.route.path == '/api/confirm':
            try:
                node = self._node(self.query.get('node', [''])[0])
                result = {'text': fleet.actions.describe_close(node),
                          'token': fleet.confirm(node)}
            except Exception as error:
                result = {'ok': False, 'error': str(error)}
            self._json(result)
        else:
            self._json({'ok': False, 'error': 'Not found'}, status=404)

    def _body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 1024 * 1024:
            raise ValueError('JSON body must be between 1 byte and 1 MiB')
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError('JSON body must be an object')
        return value

    def do_POST(self):
        # Authentication precedes body reads and all side effects.
        fleet = self.server.fleet
        if self.route.path not in ('/api/action', '/api/assign', '/api/promote',
                                   '/api/move', '/api/stage', '/api/broadcast', '/api/open-plan'):
            self._json({'ok': False, 'error': 'Not found'}, status=404)
            return
        try:
            body = self._body()
            if self.route.path == '/api/action':
                action = body.get('action')
                if action not in ('peek', 'jump', 'send', 'close'):
                    raise ValueError('Unknown action')
                node = self._node(body.get('node'))
                if action == 'close':
                    fleet.validate_confirmation(body.get('token'), node)
                args = [node]
                if action == 'send':
                    text = body.get('text', '')
                    if not isinstance(text, str):
                        raise ValueError('text must be a string')
                    args.append(text)
                if action == 'peek':
                    try:
                        output = fleet.actions.peek(node)
                    except ActionError as error:
                        self._json({'ok': False, 'error': str(error), 'reason': error.reason})
                        return
                    result = {'ok': True, 'output': output or '',
                              'reason': None if output else 'empty'}
                else:
                    output = getattr(fleet.actions, action)(*args)
                    result = {'ok': True, 'output': output or ''}
            elif self.route.path in ('/api/promote', '/api/move', '/api/stage'):
                node = self._node(body.get('node'))
                fields = {'/api/promote': ('project', 'slice', 'stage'),
                          '/api/move': ('cluster',), '/api/stage': ('stage',)}[self.route.path]
                for field in fields:
                    if not isinstance(body.get(field), str) or not body[field].strip():
                        raise ValueError(f'{field} must be a nonempty string')
                if 'stage' in fields and body['stage'] not in STAGES:
                    raise ValueError('Unknown stage')
                with fleet._assign_lock:
                    if self.route.path == '/api/promote':
                        promote(node['id'], body['project'], body['slice'], body['stage'],
                                path=fleet.config_path)
                    elif self.route.path == '/api/stage':
                        if node.get('run') in fleet._snapshot_copy().get('runs', {}):
                            raise ValueError('Stage is controlled by a run projection')
                        update_stage(node['id'], body['stage'], path=fleet.config_path)
                    else:
                        move(node['id'], body['cluster'], path=fleet.config_path)
                result = {'ok': True}
            elif self.route.path == '/api/broadcast':
                cluster, text = body.get('cluster'), body.get('text')
                include = body.get('include_terminals', False)
                if not isinstance(cluster, str) or not cluster:
                    raise ValueError('cluster must be a nonempty string')
                if not isinstance(text, str) or type(include) is not bool:
                    raise ValueError('text must be a string and include_terminals a boolean')
                kinds = ('claude', 'terminal') if include else ('claude',)
                nodes = [node for node in fleet._snapshot_copy().get('nodes', [])
                         if node.get('cluster') == cluster and node.get('kind') in kinds]
                result = {'ok': True, 'results': fleet.actions.broadcast(nodes, text)}
            elif self.route.path == '/api/open-plan':
                run_id = body.get('run')
                if not isinstance(run_id, str) or not run_id:
                    raise ValueError('run must be a nonempty string')
                run = fleet._snapshot_copy().get('runs', {}).get(run_id)
                if run is None:
                    raise ValueError('run_not_found')
                plan = run['run_plan']
                fleet.actions.open_plan(str(Path(plan['worktree']) / plan['path']))
                result = {'ok': True}
            else:
                node_id, initiative = body.get('node'), body.get('initiative')
                if not isinstance(node_id, str) or not node_id:
                    raise ValueError('node must be a nonempty string')
                if not isinstance(initiative, str):
                    raise ValueError('initiative must be a string')
                # save_assign is a read/modify/write operation; serialize pins.
                with fleet._assign_lock:
                    save_assign(node_id, initiative, path=fleet.config_path)
                result = {'ok': True}
        except Exception as error:
            result = {'ok': False, 'error': str(error)}
        self._json(result)


class FleetMapServer:
    def __init__(self, collector, actions, *, page_path=PAGE, idle_minutes=30, poll_seconds=3):
        if idle_minutes <= 0 or poll_seconds <= 0:
            raise ValueError('idle_minutes and poll_seconds must be positive')
        self.collector = collector
        self.actions = actions
        self.page_path = Path(page_path)
        self.config_path = getattr(collector, 'config_path', CONFIG_PATH)
        self.poll_seconds = poll_seconds
        self._idle_seconds = idle_minutes * 60
        self._lock = threading.Lock()
        self._assign_lock = threading.Lock()
        self._confirm_lock = threading.Lock()
        self._confirmations = {}
        self._lifecycle_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._stopped = threading.Event()
        self._serving = False
        self._http = None
        self._snapshot = {'generated_at': None, 'hosts': [], 'nodes': [], 'edges': [],
                          'runs': {}, 'clusters': {}, 'decisions': [], 'rejected_projections': {}}
        self._snapshot_ready = threading.Event()

    def confirm(self, node):
        now = time.monotonic()
        destination = Actions.destination(node)
        token = secrets.token_urlsafe(32)
        with self._confirm_lock:
            self._confirmations = {key: value for key, value in self._confirmations.items()
                                   if now - value[0] <= 300}
            self._confirmations[token] = (now, destination)
        return token

    def validate_confirmation(self, token, node):
        with self._confirm_lock:
            stored = self._confirmations.pop(token, None) if isinstance(token, str) else None
        try:
            destination = Actions.destination(node)
        except ActionError:
            destination = None
        if (stored is None or time.monotonic() - stored[0] > 300
                or stored[1] != destination):
            raise ValueError('destination changed, confirm again')

    def _snapshot_copy(self):
        with self._lock:
            return self._snapshot.copy()

    def _refresh(self):
        while not self._stopped.is_set():
            deadline = time.monotonic() + self.poll_seconds
            try:
                snapshot = self.collector.snapshot()
            except Exception:
                # A failed refresh must not replace the last completed snapshot.
                pass
            else:
                with self._lock:
                    self._snapshot = snapshot
                self._snapshot_ready.set()
            if self._stopped.wait(max(0, deadline - time.monotonic())):
                return

    def _refresh_slow(self):
        while not self._snapshot_ready.wait(0.1):
            if self._stopped.is_set():
                return
        refresh = getattr(self.collector, 'refresh_slow', None)
        if refresh is None:
            return
        while not self._stopped.is_set():
            deadline = time.monotonic() + self.poll_seconds
            try:
                refresh()
            except Exception:
                # Keep the prior probe results on a failed pass.
                pass
            if self._stopped.wait(max(0, deadline - time.monotonic())):
                return

    def _watch_idle(self):
        while not self._stopped.wait(min(1, self._idle_seconds / 4)):
            with self._lock:
                expired = time.monotonic() - self._last_request >= self._idle_seconds
            if expired:
                self.stop()
                return

    def _write_info(self):
        self._info_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=self._info_path.parent, delete=False) as output:
                temporary = output.name
                os.fchmod(output.fileno(), 0o600)
                json.dump(self._info, output)
                output.write('\n')
            os.replace(temporary, self._info_path)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def start(self):
        with self._lifecycle_lock:
            if self._http is not None or self._stopped.is_set():
                raise RuntimeError('Server can only be started once')
            self.key = secrets.token_hex(32)
            self._http = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
            self._http.fleet = self
            self._info_path = Path(SERVER_INFO)
            self._info = {'port': self._http.server_port, 'key': self.key, 'pid': os.getpid()}
            try:
                self._write_info()
            except Exception:
                self._http.server_close()
                raise
            self._last_request = time.monotonic()
            threading.Thread(target=self._refresh, name='fleetmap-collector', daemon=True).start()
            threading.Thread(target=self._refresh_slow, name='fleetmap-probes', daemon=True).start()
            threading.Thread(target=self._watch_idle, name='fleetmap-idle', daemon=True).start()
            return self._http.server_port, self.key

    def serve_forever(self):
        with self._lifecycle_lock:
            if self._stopped.is_set():
                return
            if self._http is None or self._serving:
                raise RuntimeError('Call start once before serve_forever')
            self._serving = True
        try:
            self._http.serve_forever(poll_interval=0.05)
        finally:
            with self._lifecycle_lock:
                self._serving = False
            self.stop()

    def stop(self):
        with self._stop_lock:
            with self._lifecycle_lock:
                if self._stopped.is_set():
                    return
                self._stopped.set()
                serving = self._serving
            if self._http is None:
                return
            # shutdown waits for serve_forever; never call it before serving starts.
            if serving:
                self._http.shutdown()
            self._http.server_close()
            try:
                if json.loads(self._info_path.read_text()) == self._info:
                    self._info_path.unlink()
            except (OSError, ValueError):
                pass


def main():
    providers = providers_from_config(load())
    fleet = FleetMapServer(Collector(OrcaClient(), providers=providers), Actions(OrcaClient()))
    try:
        port, key = fleet.start()
        print(json.dumps({'url': f'http://127.0.0.1:{port}/?key={key}'}), flush=True)
        fleet.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        fleet.stop()


if __name__ == '__main__':
    main()
