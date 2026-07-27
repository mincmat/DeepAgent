#!/usr/bin/env python3
import ctypes
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import uuid

PORT = 8765

ALLOWED_ORIGINS = [
    'https://chat.deepseek.com',
    'https://chat.deepseek.com/',
    'chrome-extension://',
]

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
        origin = self.headers.get('Origin', '')
        if not origin:
            return True
        return any(origin.startswith(a) for a in ALLOWED_ORIGINS)

    def _cors(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS, GET')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_GET(self):
        self._cors()
        if self.path == '/ping':
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            term = get_terminal()
            alive = term.proc is not None and term.proc.poll() is None
            self.wfile.write(json.dumps({
                'status': 'ok' if alive else 'dead',
                'pid': os.getpid(),
                'shell_pid': term.proc.pid if term.proc else 0,
                'shell_alive': alive,
            }, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'not found'}).encode('utf-8'))

    def do_OPTIONS(self):
        self._cors()
        self.end_headers()

    def do_POST(self):
        if not self._check_origin():
            self._cors()
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'origin not allowed'}, ensure_ascii=False).encode('utf-8'))
            return

        length = int(self.headers.get('Content-Length', 0))
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
            self._cors()
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'stdout': 'Terminal restarted', 'stderr': '', 'returncode': 0}, ensure_ascii=False).encode('utf-8'))
            return

        print(f'[DeepAgent] > {command[:120]}')
        sys.stdout.flush()

        result = self._run(command)

        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def _run(self, command):
        try:
            cmd = command.strip()
            if not cmd:
                return {'stdout': '', 'stderr': 'empty command', 'returncode': -1}

            stripped_sudo = False
            if cmd.lower().startswith('sudo '):
                cmd = cmd[5:].strip()
                stripped_sudo = True

            term = get_terminal()
            result = term.execute(cmd)

            if stripped_sudo:
                result['stderr'] = (
                    'ℹ️ Windows does not use "sudo": ignored it and ran the rest of the command as is.\n'
                    + result['stderr']
                ).strip()

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
