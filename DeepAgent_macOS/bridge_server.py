#!/usr/bin/env python3
import http.server
import json
import os
import pty
import re
import secrets
import select
import signal
import subprocess
import sys
import threading
import time
import uuid

PORT = 8765
MAX_BODY = 65536

DEEPSEEK_ORIGIN = 'https://chat.deepseek.com'
CHROME_EXTENSION_PREFIX = 'chrome-extension://'

TOKEN_PATH = os.path.expanduser('~/.deepagent/token')
ALLOWED_EXT_PATH = os.path.expanduser('~/.deepagent/extension_id')

PRIV_CMDS = re.compile(
    r'('
    r'\b(sudo|su|sudoedit|pkexec|doas|gksudo|kdesudo|machinectl|nsenter|systemd-run)\b'
    r'|/usr/bin/(sudo|su|pkexec|doas)'
    r'|\$\((sudo|su|pkexec|doas)\b'
    r'|`(sudo|su|pkexec|doas)\b'
    r'|\benv\s+(sudo|su|pkexec|doas)\b'
    r'|\b(nice|time|strace|ltrace)\s+(sudo|su|pkexec|doas)\b'
    r')',
    re.IGNORECASE,
)


def load_or_create_token():
    try:
        with open(TOKEN_PATH) as f:
            token = f.read().strip()
        if token:
            return token
    except (OSError, IOError):
        pass
    token = secrets.token_urlsafe(32)
    try:
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(token)
    except OSError:
        pass
    return token


TOKEN = load_or_create_token()


def _load_allowed_extension():
    try:
        with open(ALLOWED_EXT_PATH) as f:
            ext_id = f.read().strip()
        if ext_id:
            return ext_id
    except (OSError, IOError):
        pass
    return None


def _save_allowed_extension(ext_id):
    try:
        os.makedirs(os.path.dirname(ALLOWED_EXT_PATH), exist_ok=True)
        fd = os.open(ALLOWED_EXT_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(ext_id)
    except OSError:
        pass


ALLOWED_EXTENSION_ID = _load_allowed_extension()


def _is_privileged(command):
    return bool(PRIV_CMDS.search(command))


class PersistentTerminal:
    def __init__(self):
        self.proc = None
        self._master_fd = None
        self._reader_thread = None
        self._buffer = b''
        self._lock = threading.Lock()
        self._cmd_lock = threading.Lock()
        self._ready = threading.Event()
        self._start_shell()

    def _start_shell(self):
        self._master_fd, slave_fd = pty.openpty()
        shell = os.environ.get('SHELL', '/bin/zsh')
        self.proc = subprocess.Popen(
            [shell, '-f'],
            stdin=subprocess.PIPE,
            stdout=slave_fd, stderr=slave_fd,
            close_fds=True, preexec_fn=os.setsid,
        )
        os.close(slave_fd)
        t = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread = t
        t.start()
        time.sleep(0.2)
        with self._lock:
            self._buffer = b''
        self._ready.set()

    def _reader(self):
        while self.proc and self.proc.poll() is None:
            fd = self._master_fd
            if fd is None:
                break
            try:
                r, _, _ = select.select([fd], [], [], 0.5)
                if r:
                    data = os.read(fd, 65536)
                    if not data:
                        break
                    with self._lock:
                        self._buffer += data
            except (OSError, select.error, TypeError):
                break

    def execute(self, command, timeout=25):
        with self._cmd_lock:
            return self._execute_locked(command, timeout)

    def _execute_locked(self, command, timeout):
        self._ready.wait(timeout=5)

        if self.proc is None or self.proc.poll() is not None:
            self._restart_locked()

        marker = f'__DA_{uuid.uuid4().hex}__'
        cmd_line = f'{command}\necho "{marker}"$?\n'

        with self._lock:
            self._buffer = b''

        try:
            self.proc.stdin.write(cmd_line.encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self._restart_locked()
            try:
                self.proc.stdin.write(cmd_line.encode())
                self.proc.stdin.flush()
            except Exception:
                return {'stdout': '', 'stderr': '✗ Terminal write failed after restart', 'returncode': -1}

        output = b''
        start = time.time()

        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                with self._lock:
                    result_output = self._buffer
                    self._buffer = b''
                self._restart_locked()
                return {
                    'stdout': result_output.decode(errors='replace'),
                    'stderr': f'⏱️ timeout after {timeout}s',
                    'returncode': -1,
                }

            time.sleep(0.03)

            with self._lock:
                if marker.encode() in self._buffer:
                    idx = self._buffer.find(marker.encode())
                    output = self._buffer[:idx]
                    rest = self._buffer[idx + len(marker):]
                    eol = rest.find(b'\n')
                    if eol >= 0:
                        exit_str = rest[:eol].decode(errors='replace').strip()
                        self._buffer = rest[eol + 1:]
                    else:
                        exit_str = rest.decode(errors='replace').strip()
                        self._buffer = b''
                    returncode = 0
                    try:
                        returncode = int(exit_str)
                    except ValueError:
                        pass
                    break
                if len(self._buffer) > 0:
                    output = self._buffer

        text = output.decode(errors='replace').strip()
        return {'stdout': text, 'stderr': '', 'returncode': returncode}

    def _restart_locked(self):
        """_cmd_lock must be held. Kills old shell, waits for reader, starts fresh."""
        self.close()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2)
        with self._lock:
            self._buffer = b''
            self._ready.clear()
        self._start_shell()

    def restart(self):
        with self._cmd_lock:
            self._restart_locked()

    def close(self):
        try:
            if self.proc:
                try:
                    self.proc.stdin.close()
                except Exception:
                    pass
                if self.proc.poll() is None:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            self.proc = None
            if self._master_fd is not None:
                os.close(self._master_fd)
                self._master_fd = None
        except Exception:
            pass


_terminal = None
_terminal_lock = threading.Lock()


def get_terminal():
    global _terminal
    if _terminal is None:
        with _terminal_lock:
            if _terminal is None:
                _terminal = PersistentTerminal()
    return _terminal


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _check_origin(self):
        global ALLOWED_EXTENSION_ID
        origin = self.headers.get('Origin', '')
        if origin == DEEPSEEK_ORIGIN:
            return True
        if origin.startswith(CHROME_EXTENSION_PREFIX) and len(origin) > len(CHROME_EXTENSION_PREFIX):
            ext_id = origin[len(CHROME_EXTENSION_PREFIX):]
            if ALLOWED_EXTENSION_ID is None:
                ALLOWED_EXTENSION_ID = ext_id
                _save_allowed_extension(ext_id)
                return True
            if secrets.compare_digest(ext_id, ALLOWED_EXTENSION_ID):
                return True
        return False

    def _check_host(self):
        return self.headers.get('Host', '') in ('localhost:8765', '127.0.0.1:8765')

    def _check_token(self):
        return secrets.compare_digest(self.headers.get('X-DeepAgent-Token', ''), TOKEN)

    def _authorized(self):
        return self._check_origin() and self._check_host() and self._check_token()

    def _deny(self):
        self.send_response(403)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'error': 'unauthorized'}).encode())

    def do_GET(self):
        if self.path == '/ping':
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            term = get_terminal()
            alive = term.proc is not None and term.proc.poll() is None
            self.wfile.write(json.dumps({
                'status': 'ok' if alive else 'dead',
                'shell_alive': alive,
            }).encode())
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'not found'}).encode())

    def do_OPTIONS(self):
        if not self._check_origin():
            self.send_response(403)
            self.end_headers()
            return
        origin = self.headers.get('Origin', '')
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-DeepAgent-Token')
        self.send_header('Vary', 'Origin')
        self.end_headers()

    def do_POST(self):
        if not self._authorized():
            self._deny()
            return

        try:
            length = int(self.headers.get('Content-Length', 0) or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._deny()
            return

        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}
        command = data.get('command', '')

        if command == '__RESET__':
            print('[DeepAgent] RESET terminal')
            sys.stdout.flush()
            get_terminal().restart()
            origin = self.headers.get('Origin', '')
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'stdout': 'Terminal restarted', 'stderr': '', 'returncode': 0}).encode())
            return

        print(f'[DeepAgent] > {command[:120]}')
        sys.stdout.flush()

        result = self._run(command)

        origin = self.headers.get('Origin', '')
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def _run(self, command):
        try:
            cmd = command.strip()
            if not cmd:
                return {'stdout': '', 'stderr': 'empty command', 'returncode': -1}

            if _is_privileged(cmd):
                print(f'[DeepAgent] BLOCKED privileged command: {cmd[:100]}')
                sys.stdout.flush()
                return {
                    'stdout': '',
                    'stderr': '⛔ Privilege-escalation commands (sudo, su, pkexec, doas...) are blocked by DeepAgent for security.',
                    'returncode': -1,
                }

            term = get_terminal()
            result = term.execute(cmd)
            print(f'[DeepAgent] < exit={result["returncode"]} ({len(result["stdout"] + result["stderr"])} chars)')
            sys.stdout.flush()
            return result

        except Exception as e:
            return {'stdout': '', 'stderr': f'✗ error: {e}', 'returncode': -1}


def _check_homebrew():
    try:
        result = subprocess.run(['brew', '--prefix'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _check_xcode():
    try:
        result = subprocess.run(['xcode-select', '-p'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


if __name__ == '__main__':
    term = get_terminal()
    shell = os.environ.get('SHELL', '/bin/zsh')
    brew = 'Yes' if _check_homebrew() else 'No'
    xcode = 'Yes' if _check_xcode() else 'No'
    print('=' * 54)
    print(f'  DeepAgent bridge (macOS) — http://localhost:{PORT}')
    print(f'  Shell: {shell} (PID {term.proc.pid})')
    print(f'  Homebrew: {brew}')
    print(f'  Xcode CLT: {xcode}')
    print(f'  Security token: {TOKEN}')
    print(f'  Paste this token into the DeepAgent panel in Chrome.')
    print(f'  Privilege-escalation commands (sudo, su, pkexec...) are blocked.')
    print('=' * 54)
    sys.stdout.flush()
    try:
        http.server.ThreadingHTTPServer(('localhost', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\n[DeepAgent] Stopping...')
        term.close()
