"""The fleet map's subprocess boundary for local and remote Orca runtimes."""
import json
import subprocess


class OrcaError(RuntimeError):
    """An Orca command failed or returned an unreadable response."""


class OrcaClient:
    def __init__(self, binary: str = 'orca', timeout: float = 5.0):
        self.binary = binary
        self.timeout = timeout

    def _run(self, args: list[str]) -> str:
        try:
            process = subprocess.run([self.binary, *args], capture_output=True,
                                     timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            raise OrcaError('timeout') from error
        except OSError as error:
            raise OrcaError(str(error)) from error
        if process.returncode:
            raise OrcaError(process.stderr.decode('utf-8', errors='replace'))
        return process.stdout.decode('utf-8', errors='replace')

    def call(self, args: list[str], env: str | None = None) -> dict:
        output = self._run([*(['--environment', env] if env else []), *args, '--json'])
        try:
            envelope = json.loads(output)
        except ValueError as error:
            raise OrcaError('Orca returned invalid JSON') from error
        if not isinstance(envelope, dict):
            raise OrcaError('Orca returned an invalid envelope')
        if envelope.get('ok') is False:
            error = envelope.get('error')
            diagnostic = (f"{error.get('code', '')}: {error.get('message', '')}"
                          if isinstance(error, dict) else str(error))
            raise OrcaError(diagnostic)
        if envelope.get('ok') is not True or not isinstance(envelope.get('result'), dict):
            raise OrcaError('Orca returned an invalid envelope')
        return envelope['result']

    def environments(self) -> list[str]:
        """List saved environment names, including older CLIs with plain output."""
        try:
            result = self.call(['environment', 'list'])
            return [environment['name'] for environment in result['environments']]
        except (OrcaError, KeyError, TypeError):
            output = self._run(['environment', 'list'])
        names = []
        for line in output.splitlines():
            columns = line.split()
            if (len(columns) < 2 or columns[1].lower() == 'name'
                    or line.strip() == 'No saved environments.'
                    or all(character in '-= ' for character in line)):
                continue
            names.append(columns[1])
        return names

    def terminals(self, env: str | None = None) -> list[dict]:
        terminals = self.call(['terminal', 'list'], env)['terminals']
        normalized = []
        for terminal in terminals:
            item = {key: terminal.get(key) for key in (
                'handle', 'title', 'worktreePath', 'branch', 'connected',
                'tabId', 'leafId', 'agentIdentity')}
            timestamp = float(terminal.get('lastOutputAt') or 0)
            item['lastOutputAt'] = timestamp / 1000 if timestamp > 1e11 else timestamp
            normalized.append(item)
        return normalized

    def runs(self, env: str | None = None) -> list[dict]:
        return self.call(['orchestration', 'run-list'], env)['runs']

    def inbox(self, env: str | None = None) -> list[dict]:
        return self.call(['orchestration', 'inbox'], env)['messages']

    def workers(self, env: str | None = None) -> list[dict]:
        return self.call(['orchestration', 'worker-list'], env)['workers']

    def tasks(self, env: str | None = None) -> list[dict]:
        return self.call(['orchestration', 'task-list'], env)['tasks']

    def screen(self, handle: str, env: str | None = None) -> str:
        result = self.call(['terminal', 'read', '--terminal', handle, '--screen'], env)
        for key in ('screen', 'text', 'preview'):
            if isinstance(result.get(key), str):
                return result[key]
        return ''

    def switch(self, handle: str, env: str | None = None):
        return self.call(['terminal', 'switch', '--terminal', handle], env)

    def send(self, handle: str, text: str, env: str | None = None):
        return self.call(['terminal', 'send', '--terminal', handle,
                          '--text', text, '--enter'], env)

    def close(self, handle: str, env: str | None = None):
        return self.call(['terminal', 'close', '--terminal', handle], env)
