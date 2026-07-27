# DeepAgent 🧠

**Make DeepSeek control your computer automatically.**

DeepAgent is a tool that connects DeepSeek (a website like ChatGPT) directly to your computer's terminal. Instead of just chatting, DeepSeek can open files, run programs, install things, and do pretty much anything you can do from a command line.

Think of it as giving DeepSeek a "remote control" for your PC.

---

## How does it work? 🤔

It's made of two parts that talk to each other:

```
[DeepSeek website] ←→ [Chrome extension] ←→ [Python bridge] ←→ [Your computer's terminal]
```

1. **Chrome extension** — A small program inside your browser that reads what DeepSeek says.
2. **Python bridge** — A tiny server running on your computer that executes commands.
3. When DeepSeek wants to run a command, the extension catches it and sends it to the bridge.
4. The bridge runs the command on your terminal and sends the result back to DeepSeek.
5. DeepSeek reads the result and decides what to do next.

It's a loop: **DeepSeek thinks → runs a command → sees the result → thinks again → runs another command...**

---

## Which platform do you use?

| Your computer | What to open |
|---|---|
| 🐧 Linux | `DeepAgent_Linux/start.sh` |
| 🍎 macOS | `DeepAgent_macOS/start.command` |
| 🪟 Windows | `DeepAgent_Windows/start.bat` |

---

## What do you need? 📋

- **Python 3** — Don't worry, the script will tell you if you don't have it.
- **Google Chrome** — The extension lives here.
- **An account** on [chat.deepseek.com](https://chat.deepseek.com) — It's free.

---

## How to install it step by step 🪜

### Step 1: Load the extension into Chrome

1. Open Chrome.
2. Type `chrome://extensions` in the address bar and press Enter.
3. Toggle on **Developer mode** (top-right corner).
4. Click **Load unpacked**.
5. Navigate to this folder and select the `DeepAgent_Extension` folder **inside** your OS folder (Linux, macOS, or Windows).

### Step 2: Start the bridge

Double-click the launcher file for your system:
- **Linux:** Right-click → Run as program
- **macOS:** Double-click `start.command`
- **Windows:** Double-click `start.bat`

A terminal window will open. Leave it open — that's your bridge running.

### Step 3: Start using it

1. Go to [chat.deepseek.com](https://chat.deepseek.com).
2. You'll see a small floating panel on the page with a **Start** button.
3. Click **Start**.
4. DeepSeek will now be able to run commands on your computer.

---

## Safety first 🛡️

- The bridge **only** listens to DeepSeek's website — no one else can send commands.
- If DeepSeek tries to use `sudo` (the command that asks for your password), the system detects it and blocks it automatically.
- Every command is checked to make sure it doesn't run twice by accident.
- You can see **everything** DeepSeek is doing in real time on the floating panel.

---

## What can DeepSeek do with this?

- 📁 List, create, delete files and folders
- 📦 Install software
- 🔍 Search your computer
- 🐍 Run Python scripts
- 🌐 Download things from the internet
- 🛠️ Fix problems
- Pretty much anything you could type in a terminal

---

## Having trouble? 😕

- Make sure the bridge terminal window is still open (it shows a status dot on the page: 🟢 green = connected, 🔴 red = offline).
- Try closing and reopening the browser tab.
- Restart the bridge by closing the terminal window and running the launcher again.

---

## License

Free to use.
