#!/usr/bin/env python3
import ctypes
import http.server
import json
import os
import re
import secrets
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
    r'\b(sudo|su|runas|gsudo)\b'
    r'|\$\((sudo|su|runas|gsudo)\b'
    r'|`(sudo|su|runas|gsudo)\b'
    r'|\benv\s+(sudo|su|runas|gsudo)\b'
    r')',
    re.IGNORECASE,
)

ADMIN_ERROR_HINTS = [
    'access is denied',
    'acceso denegado',
    'requested operation requires elevation',
    'requiere elevaci',
    'you do not have sufficient privilege',
    'no tiene privilegios suficientes',
    'no dispone de privilegios suficientes',
    'permission denied',
    'se denegó el acceso',
]


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


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def looks_like_permission_error(text):
    lower = text.lower()
    return any(hint in lower for hint in ADMIN_ERROR_HINTS)


class PersistentTerminal:
    def __init__(self):
        self.proc = None
        self._reader_thread = None
        self._buffer = b''
        self._lock = threading.Lock()
        self._cmd_lock = threading.Lock()
        self._ready = threading.Event()
        self._start_shell()

    def _start_shell(self):
        self.proc = subprocess.Popen(
            ['cmd.exe'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        t = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread = t
        t.start()
        time.sleep(0.3)
        self._ready.set()

    def _reader(self):
        while self.proc and self.proc.poll() is None:
            try:
                data = self.proc.stdout.read(4096)
                if not data:
                    break
                with self._lock:
                    self._buffer += data
            except Exception:
                break

    def execute(self, command, timeout=25):
        with self._cmd_lock:
            return self._execute_locked(command, timeout)

    def _execute_locked(self, command, timeout):
        self._ready.wait(timeout=5)

        if self.proc is None or self.proc.poll() is not None:
            self._restart_locked()

        marker = f'__DA_{uuid.uuid4().hex}__'

        cmd_line = (
            f'@chcp 65001>nul\n'
            f'@{command}\n'
            f'@echo {marker}%ERRORLEVEL%\n'
        )

        with self._lock:
            self._buffer = b''

        try:
            self.proc.stdin.write(cmd_line.encode('utf-8', errors='replace'))
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self._restart_locked()
            try:
                self.proc.stdin.write(cmd_line.encode('utf-8', errors='replace'))
                self.proc.stdin.flush()
            except Exception:
                return {'stdout': '', 'stderr': '\u2717 Terminal write failed after restart', 'returncode': -1}

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
                    'stdout': result_output.decode('utf-8', errors='replace'),
                    'stderr': f'\u23f1\ufe0f timeout after {timeout}s',
                    'returncode': -1,
                }

            time.sleep(0.05)

            with self._lock:
                if marker.encode() in self._buffer:
                    idx = self._buffer.find(marker.encode())
                    output = self._buffer[:idx]
                    rest = self._buffer[idx + len(marker):]
                    eol = rest.find(b'\n')
                    if eol >= 0:
                        exit_str = rest[:eol].decode('utf-8', errors='replace').strip()
                        self._buffer = rest[eol + 1:]
                    else:
                        exit_str = rest.decode('utf-8', errors='replace').strip()
                        self._buffer = b''
                    returncode = 0
                    try:
                        returncode = int(exit_str)
                    except ValueError:
                        pass
                    break
                if len(self._buffer) > 0:
                    output = self._buffer

        text = output.decode('utf-8', errors='replace').strip()

        stderr = ''
        if looks_like_permission_error(text):
            stderr = (
                '\n\U0001f512 This command seems to need administrator permissions. '
                'Close this terminal and reopen start.bat with right click \u2192 '
                '"Run as administrator".'
            )

        return {'stdout': text, 'stderr': stderr, 'returncode': returncode}

    def _restart_locked(self):
        """_cmd_lock must be held. Kills old cmd, waits for reader, starts fresh."""
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
            if self.proc and self.proc.poll() is None:
                subprocess.call(
                    ['taskkill', '/F', '/T', '/PID', str(self.proc.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            self.proc = None
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
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            term = get_terminal()
            alive = term.proc is not None and term.proc.poll() is None
            self.wfile.write(json.dumps({
                'status': 'ok' if alive else 'dead',
                'shell_alive': alive,
            }, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'not found'}, ensure_ascii=False).encode('utf-8'))

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
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'stdout': 'Terminal restarted', 'stderr': '', 'returncode': 0}, ensure_ascii=False).encode('utf-8'))
            return

        print(f'[DeepAgent] > {command[:120]}')
        sys.stdout.flush()

        result = self._run(command)

        origin = self.headers.get('Origin', '')
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

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
                    'stderr': '⛔ Privilege-escalation commands (sudo, su, runas...) are blocked by DeepAgent for security.',
                    'returncode': -1,
                }

            term = get_terminal()
            result = term.execute(cmd)
            print(f'[DeepAgent] < exit={result["returncode"]} ({len(result["stdout"] + result["stderr"])} chars)')
            sys.stdout.flush()
            return result

        except Exception as e:
            return {'stdout': '', 'stderr': f'✗ error: {e}', 'returncode': -1}


def main():
    term = get_terminal()
    print('=' * 54)
    print(f'  DeepAgent bridge (Windows) — http://localhost:{PORT}')
    print(f'  Current folder: {os.getcwd()}')
    print(f'  Terminal persistente: cmd.exe (PID {term.proc.pid})')
    print(f'  Administrador: {"SI" if is_admin() else "NO"}')
    print(f'  Security token: {TOKEN}')
    print(f'  Paste this token into the DeepAgent panel in Chrome.')
    print(f'  Privilege-escalation commands (sudo, runas...) are blocked.')
    if not is_admin():
        print('  Tip: if a command asks for admin permissions,')
        print('  close this window and run start.bat as administrator.')
    print('  Keep this window open while using the extension.')
    print('=' * 54)
    sys.stdout.flush()

    try:
        http.server.ThreadingHTTPServer(('localhost', PORT), Handler).serve_forever()
    except OSError as e:
        print(f'[DeepAgent] ✗ Could not start server on port {PORT}: {e}')
        print('[DeepAgent] Is another DeepAgent instance already running?')
        input('Press Enter to exit...')
    except KeyboardInterrupt:
        print('\n[DeepAgent] Stopping...')
    finally:
        term.close()


if __name__ == '__main__':
    main()
