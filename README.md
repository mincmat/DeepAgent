# DeepAgent 🧠

**DeepAgent** turns DeepSeek (chat.deepseek.com) into an autonomous agent with full terminal access. Through a Chrome extension and a local Python bridge, the AI can execute commands, read/write files, install packages, and more — directly on your machine.

## Architecture

```
DeepSeek Chat ←→ Chrome Extension ←→ Python Bridge ←→ Shell (bash/zsh/cmd)
```

## Supported Platforms

| Platform | Shell | Launcher |
|---|---|---|
| Linux | bash | `DeepAgent_Linux/start.sh` |
| macOS | zsh (default) | `DeepAgent_macOS/start.command` |
| Windows | cmd.exe | `DeepAgent_Windows/start.bat` |

## Requirements

- **Python 3** (standard library only — no external dependencies)
- **Google Chrome** (for the extension)
- An account at [chat.deepseek.com](https://chat.deepseek.com)

## Installation

1. Clone or download this repository.
2. Open Chrome → `chrome://extensions` → Enable **Developer mode** → **Load unpacked**.
3. Select the `DeepAgent_Extension` folder inside your OS folder.
4. Run the launcher for your system:
   - **Linux:** `bash start.sh`
   - **macOS:** Double-click `start.command`
   - **Windows:** Double-click `start.bat`
5. Go to [chat.deepseek.com](https://chat.deepseek.com) and press **Start** on the floating panel.

## How it works

1. The extension injects a **system prompt** into the chat explaining how to use commands.
2. When the AI responds with a JSON block like `{"action": "execute", "command": "ls -la"}`, the extension detects it automatically.
3. The command is sent to the local Python server (`localhost:8765`), which runs it in a persistent shell.
4. The output is captured and pasted back into the chat for the AI to process.
5. The cycle repeats: the AI sees the output and decides the next command.

## Security

- The server only accepts requests from `chat.deepseek.com` and `chrome-extension://` origins.
- `sudo` commands run in an isolated environment that detects authentication prompts (password/fingerprint) and kills them automatically.
- On Windows, missing admin privileges are detected and the user is warned.
- Commands are de-duplicated by hash to prevent accidental re-execution.

## Features

- Zero external Python dependencies (only `http.server`, `subprocess`, `pty`)
- Floating control panel with real-time connection status
- Automatic SPA navigation detection (chat changes)
- Auto-start/stop based on agent prompt presence
- FIFO command queue with sequential execution
- 25-second command timeout with automatic shell restart

## License

This project is open source.
