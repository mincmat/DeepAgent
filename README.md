# DeepAgent 🧠

**Turn DeepSeek into an AI that can control your computer.**

DeepAgent connects DeepSeek (a website like ChatGPT) to your computer's terminal. Instead of just chatting, DeepSeek can run commands on your PC — list files, install software, run scripts, and more.

---

## How it works

```
[DeepSeek website] ←→ [Chrome extension] ←→ [Python bridge] ←→ [Your terminal]
```

1. A Chrome extension injects a special instruction into the DeepSeek chat.
2. When DeepSeek replies with a command like `{"action": "execute", "command": "ls -la"}`, the extension detects it.
3. The command goes to a small Python program running on your computer, which executes it in your terminal.
4. The output is sent back to DeepSeek, so it can see the result and decide what to do next.

---

## What you need

- **Google Chrome**
- **Python 3** (the script will check for it)
- An account at [chat.deepseek.com](https://chat.deepseek.com) (free)

---

## Setup step by step

### 1. Load the Chrome extension

1. Open Chrome and type `chrome://extensions` in the address bar.
2. Turn on **Developer mode** (toggle in the top-right corner).
3. Click **Load unpacked**.
4. Navigate to the `DeepAgent_Extension` folder **inside** your OS folder (Linux, macOS, or Windows).

### 2. Start the bridge

Open the launcher for your system:

| Your OS | File to run |
|---|---|
| Linux | `DeepAgent_Linux/start.sh` (double-click or run in terminal) |
| macOS | `DeepAgent_macOS/start.command` (double-click) |
| Windows | `DeepAgent_Windows/start.bat` (double-click) |

A terminal window will open with the bridge running. **Keep it open.**

### 3. Use it

1. Go to [chat.deepseek.com](https://chat.deepseek.com).
2. You'll see a small floating panel in the top-right corner of the page.
3. Click **Start**.
4. DeepSeek can now run commands on your computer.

---

## How to talk to DeepSeek

Just chat normally. DeepSeek will use commands automatically when needed. For example:

- *"What files are in my Documents folder?"* → DeepSeek runs `ls ~/Documents`
- *"Install the Python requests library"* → DeepSeek runs `pip install requests`
- *"Create a backup of my project"* → DeepSeek runs `cp -r project/ backup/`

The panel shows a **green dot** when connected and **red** when offline.

---

## What it can do

- Browse your files and folders
- Create, edit, and delete files
- Install software and packages
- Run Python, bash, and other scripts
- Search the web via curl or wget
- Anything you can do in a terminal

---

## Safety

- The bridge **only** listens to requests from DeepSeek's website — nobody else can send commands.
- If DeepSeek tries to use `sudo` (a command that asks for your password), the system blocks it automatically.
- You can see every command DeepSeek runs in real time.

---

## Troubleshooting

- **Panel shows red dot** → Make sure the bridge terminal window is still open.
- **Nothing happens** → Refresh the DeepSeek page and click Start again.
- **Extension not loading** → Make sure you selected the right `DeepAgent_Extension` folder (inside your OS folder).

---

## License

Free to use.
