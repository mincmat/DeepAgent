#!/usr/bin/env python3
import http.server
import json
import os
import pty
import select
import signal
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

SUDO_KEYWORDS = [
    b'huella', b'dedo', b'fingerprint',
    b'contrase', b'password',
    b'passphrase', b'sudo password',
    b'sudo:', b'password for',
    b'touch id', b'finger',
]


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
                    'stdout': result_output.decode(errors='replace'),
                    'stderr': f'\u23f1\ufe0f timeout after {timeout}s',
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
        """_cmd_lock must be held. Kills old bash, waits for reader, starts fresh."""
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
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            term = get_terminal()
            alive = term.proc is not None and term.proc.poll() is None
            self.wfile.write(json.dumps({
                'status': 'ok' if alive else 'dead',
                'pid': os.getpid(),
                'shell_pid': term.proc.pid if term.proc else 0,
                'shell_alive': alive,
            }).encode())
        else:
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'not found'}).encode())

    def do_OPTIONS(self):
        self._cors()
        self.end_headers()

    def do_POST(self):
        if not self._check_origin():
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'origin not allowed'}).encode())
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
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'stdout': 'Terminal restarted', 'stderr': '', 'returncode': 0}).encode())
            return

        print(f'[DeepAgent] > {command[:120]}')
        sys.stdout.flush()

        result = self._run(command)

        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def _run(self, command):
        try:
            cmd = command.strip()
            if not cmd:
                return {'stdout': '', 'stderr': 'empty command', 'returncode': -1}

            if 'sudo' in cmd:
                print(f'[DeepAgent] SUDO (bypass): {cmd[:100]}...')
                sys.stdout.flush()
                return _run_pty(cmd)

            term = get_terminal()
            result = term.execute(cmd)
            print(f'[DeepAgent] < exit={result["returncode"]} ({len(result["stdout"] + result["stderr"])} chars)')
            sys.stdout.flush()
            return result

        except Exception as e:
            return {'stdout': '', 'stderr': f'\u2717 error: {e}', 'returncode': -1}


def _run_pty(command, timeout=30):
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        command, shell=True,
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True, preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    output = b''
    start = time.time()
    timed_out = False
    prompt_detected = False

    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            timed_out = True
            break

        r, _, _ = select.select([master_fd], [], [], max(0.1, timeout - elapsed))
        if r:
            try:
                data = os.read(master_fd, 4096)
                if not data:
                    break
                output += data
            except OSError:
                break

            if not prompt_detected:
                lower = output.lower()
                for kw in SUDO_KEYWORDS:
                    if kw in lower:
                        prompt_detected = True
                        break

            if prompt_detected:
                time.sleep(0.2)
                while True:
                    r2, _, _ = select.select([master_fd], [], [], 0.1)
                    if not r2:
                        break
                    try:
                        d = os.read(master_fd, 4096)
                        if not d:
                            break
                        output += d
                    except OSError:
                        break
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                break

        if proc.poll() is not None:
            while True:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if not r:
                    break
                try:
                    d = os.read(master_fd, 4096)
                    if not d:
                        break
                    output += d
                except OSError:
                    break
            break

    os.close(master_fd)
    out = output.decode(errors='replace')

    if prompt_detected:
        return {
            'stdout': out,
            'stderr': '\u23f8\ufe0f sudo requires interactive authentication (Touch ID / password). The command was stopped.',
            'returncode': -1,
        }
    if timed_out:
        return {'stdout': out, 'stderr': '\u23f1\ufe0f timeout after 30s', 'returncode': -1}
    return {'stdout': out, 'stderr': '', 'returncode': proc.returncode or 0}


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
    print(f'  DeepAgent bridge (macOS) \u2014 http://localhost:{PORT}')
    print(f'  Shell: {shell} (PID {term.proc.pid})')
    print(f'  Homebrew: {brew}')
    print(f'  Xcode CLT: {xcode}')
    print(f'  Persistent terminal active')
    print(f'  Tip: if a command needs sudo, it will run in')
    print(f'  a separate terminal with password detection.')
    print('=' * 54)
    sys.stdout.flush()
    try:
        http.server.ThreadingHTTPServer(('localhost', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\n[DeepAgent] Stopping...')
        term.close()
