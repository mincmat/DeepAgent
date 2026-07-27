(function () {
  'use strict';

  const PROMPT_SIGNATURE = 'DeepAgent, an AI assistant with FULL control';

  const AGENT_PROMPT = `You are DeepAgent, an AI assistant with FULL control over a Linux computer.

You have a PERSISTENT terminal session (bash). Each command runs in the SAME shell, so state (cd, variables, aliases, etc.) persists between commands. To execute a command, output it in a code block with triple backticks:

\`\`\`json
{"action": "execute", "command": "the-command-here"}
\`\`\`

CRITICAL: Use \`\`\` triple backticks. Never write "json" on its own line.

## How it works
- Send ONE command per message. Multiple commands per message will be ignored.
- Wait for the output before sending the next command. Do NOT send a new command until you receive the result.
- The output you receive is the raw terminal output (stdout + stderr).

## Available action
\`{"action": "execute", "command": "<shell-command>"}\` — runs the command and returns stdout, stderr and exit code.

## Capabilities
- cd, sudo, export, file read/write/edit, package management, services, scripts, git, python, etc.

## Notes
- Commands time out after 30s
- sudo may require interactive authentication (fingerprint/password) — if so, the command will be stopped and you'll receive a message saying so
- The terminal is persistent: environment variables, working directory, and shell state persist between commands
- You can break complex tasks into multiple sequential commands

Reply to the user conversationally. Execute commands as needed to fulfill their request — you don't need to ask permission for each step. Break down complex tasks into multiple commands, one per message.`;

  const STORAGE_KEY = 'deepagent_state';

  let _userStopped = false;

  const state = {
    observer: null,
    panel: null,
    commandQueue: [],
    processing: false,
    executedHashes: new Set(),
    _urlCheckTimer: null,
    _lastUrl: '',
    abortController: null,
    _statusInterval: null,
    _currentCommand: null,
  };

  /* ── Persistence (hashes only) ─────────────────────────── */

  let _saveTimer = null;

  function persist() {
    if (_saveTimer) clearTimeout(_saveTimer);
    _saveTimer = setTimeout(() => {
      chrome.storage.local.set({
        [STORAGE_KEY]: { hashes: Array.from(state.executedHashes).slice(-200) },
      });
    }, 300);
  }

  function loadHashes() {
    return new Promise((resolve) => {
      chrome.storage.local.get(STORAGE_KEY, (res) => {
        const data = res[STORAGE_KEY];
        if (data && Array.isArray(data.hashes)) {
          state.executedHashes = new Set(data.hashes);
        }
        resolve();
      });
    });
  }

  /* ── Utils ─────────────────────────────────────────────── */

  function hashCommand(command) {
    let hash = 0;
    for (let i = 0; i < command.length; i++) {
      hash = ((hash << 5) - hash) + command.charCodeAt(i);
      hash |= 0;
    }
    return hash.toString(36);
  }

  function tryParseJSON(str) {
    try {
      return JSON.parse(str);
    } catch {
      return null;
    }
  }

  function getInput() {
    let el = document.querySelector('textarea');
    if (el) return el;
    el = document.querySelector('[contenteditable="true"], [contenteditable=""]');
    if (el) return el;
    el = document.querySelector('[contenteditable]:not([contenteditable="false"])');
    if (el) return el;
    el = document.querySelector('[class*="input"] [contenteditable]');
    if (el) return el;
    el = document.querySelector('[role="textbox"]');
    if (el) return el;
    console.warn('[DeepAgent] No chat input element found');
    return null;
  }

  function setInputValue(el, value) {
    if (el.tagName === 'TEXTAREA') {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype,
        'value',
      ).set;
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    } else if (el.isContentEditable) {
      el.focus();
      el.textContent = '';
      document.execCommand('insertText', false, value);
    }
  }

  function promptInDOM() {
    return document.body.innerText.includes(PROMPT_SIGNATURE);
  }

  /* ── Expert mode ───────────────────────────────────────── */

  function clickExpert() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const t = node.textContent.trim().toLowerCase();
      if (t === 'expert' || (t.includes('expert') && t.length < 10)) {
        const parent = node.parentElement;
        if (parent && parent.offsetParent !== null && typeof parent.click === 'function') {
          parent.click();
          console.log('[DeepAgent] Expert activated');
          return true;
        }
      }
    }
    console.warn('[DeepAgent] Expert not found');
    return false;
  }

  /* ── Bridge relay (through background.js) ─────────────── */

  function bridgeSend(msg, retries = 2) {
    return new Promise((resolve, reject) => {
      function trySend(attempt) {
        chrome.runtime.sendMessage(msg, (response) => {
          if (chrome.runtime.lastError) {
            if (attempt < retries) {
              setTimeout(() => trySend(attempt + 1), 200);
            } else {
              reject(new Error(chrome.runtime.lastError.message));
            }
          } else {
            resolve(response);
          }
        });
      }
      trySend(0);
    });
  }

  /* ── Ping check ────────────────────────────────────────── */

  async function checkBridgeHealth() {
    try {
      const data = await bridgeSend({ action: 'ping' });
      return data && data.status === 'ok' && data.shell_alive;
    } catch {
      return false;
    }
  }

  /* ── Send message ──────────────────────────────────────── */

  function findSendButton() {
    const ta = getInput();
    if (!ta) return null;
    const container =
      ta.closest('[class*="input"]') ||
      ta.closest('[class*="footer"]') ||
      ta.closest('[class*="composer"]') ||
      ta.closest('form') ||
      ta.parentElement;
    const area = container || document.body;
    const candidates = area.querySelectorAll(
      'div[role="button"], button, [class*="icon-button"]',
    );
    let last = null;
    for (const el of candidates) {
      if (el.querySelector('svg') || el.innerHTML.includes('<svg')) last = el;
    }
    return last;
  }

  async function sendMessage() {
    for (let i = 0; i < 5; i++) {
      const btn = findSendButton();
      if (btn && !btn.disabled) {
        btn.click();
        return;
      }
      const ta = getInput();
      if (ta) {
        ta.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }),
        );
        await new Promise(r => setTimeout(r, 200));
      } else {
        await new Promise(r => setTimeout(r, 500));
      }
    }
  }

  /* ── Command queue ─────────────────────────────────────── */

  async function executeCommand(command) {
    state._currentCommand = command;
    updatePanelStatus();
    const ta = getInput();
    if (!ta) return;
    console.log('[DeepAgent] Executing:', command.slice(0, 80));

    const preview = command.length > 60 ? command.slice(0, 57) + '...' : command;
    setInputValue(ta, `\u2699\ufe0f Running: ${preview}`);

    const controller = new AbortController();
    state.abortController = controller;

    try {
      const resp = await Promise.race([
        bridgeSend({ action: 'execute', command }),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Timeout — command took too long')), 35000)
        ),
      ]);
      let output = '';
      if (resp.error) {
        output = `[Error] ${resp.error}`;
      } else {
        const parts = [];
        if (resp.stdout) parts.push(resp.stdout);
        if (resp.stderr) parts.push(resp.stderr);
        if (resp.returncode !== 0 && resp.returncode !== undefined) {
          parts.push(`[Exit code: ${resp.returncode}]`);
        }
        output = parts.join('\n') || '(no output)';
      }
      setInputValue(ta, output);
      await new Promise((r) => setTimeout(r, 400));
      await sendMessage();
    } catch (err) {
      if (err.name === 'AbortError') {
        console.log('[DeepAgent] Command aborted by user');
        return;
      }
      console.error('[DeepAgent] Error:', err);
      setInputValue(ta, `[Error] ${err.message}`);
      await new Promise((r) => setTimeout(r, 400));
      await sendMessage();
    } finally {
      state.abortController = null;
      state._currentCommand = null;
      updatePanelStatus();
    }
  }

  async function processQueue() {
    if (state.processing || state.commandQueue.length === 0) return;
    state.processing = true;
    while (state.commandQueue.length > 0) {
      if (!state.observer) break;
      await executeCommand(state.commandQueue.shift());
    }
    state.processing = false;
    updatePanelStatus();
  }

  function queueCommand(command) {
    state.commandQueue.push(command);
    processQueue();
  }

  /* ── JSON extraction ───────────────────────────────────── */

  function parseJSONFromText(text) {
    let data = tryParseJSON(text);
    if (!data) {
      const start = text.indexOf('{');
      if (start !== -1) {
        let depth = 0;
        let end = -1;
        for (let i = start; i < text.length; i++) {
          if (text[i] === '{') depth++;
          else if (text[i] === '}') {
            depth--;
            if (depth === 0) { end = i; break; }
          }
        }
        if (end !== -1) data = tryParseJSON(text.slice(start, end + 1));
      }
    }
    if (data && data.action === 'execute' && typeof data.command === 'string' && data.command) return data;
    return null;
  }

  function queueIfValid(data) {
    const h = hashCommand(data.command);
    if (state.executedHashes.has(h)) return;
    state.executedHashes.add(h);
    console.log('[DeepAgent] Command:', data.command.slice(0, 100));
    queueCommand(data.command);
    persist();
  }

  function extractCommands() {
    let count = 0;
    for (const block of document.querySelectorAll('pre code')) {
      const text = block.textContent;
      if (block.dataset.daText === text) continue;
      block.dataset.daText = text;
      const data = parseJSONFromText(text);
      if (data) { queueIfValid(data); count++; }
    }
    const msg = findLastAssistant();
    if (msg) {
      const text = msg.textContent;
      if (msg.dataset.daText !== text) {
        msg.dataset.daText = text;
        const data = parseJSONFromText(text);
        if (data) { queueIfValid(data); count++; }
      }
    }
    if (count > 0) console.log('[DeepAgent] Queued', count, 'command(s)');
  }

  function findLastAssistant() {
    for (const sel of ['[data-role="assistant"]', '[class*="assistant"]', '[class*="answer"]', '.ds-message']) {
      const els = document.querySelectorAll(sel);
      if (els.length > 0) return els[els.length - 1];
    }
    return document.querySelector('[class*="message"]:last-child') ||
           document.querySelector('main article:last-child') || null;
  }

  /* ── Agent lifecycle (per-chat aware) ──────────────────── */

  function startAgent() {
    if (state.observer) return;
    console.log('[DeepAgent] Starting agent');
    clickExpert();
    state.observer = new MutationObserver(() => extractCommands());
    state.observer.observe(document.body, { childList: true, subtree: true });
    extractCommands();
    updatePanel(true);
  }

  function stopAgent() {
    if (state.abortController) {
      state.abortController.abort();
      state.abortController = null;
    }
    if (state.observer) {
      state.observer.disconnect();
      state.observer = null;
    }
    state.commandQueue = [];
    state._currentCommand = null;
    state.processing = false;
    updatePanel(false);
    console.log('[DeepAgent] Agent stopped');
  }

  function checkChatState() {
    if (_userStopped) return;
    const hasPrompt = promptInDOM();
    if (hasPrompt && !state.observer) {
      console.log('[DeepAgent] Prompt detected — auto-starting');
      startAgent();
    } else if (!hasPrompt && state.observer) {
      console.log('[DeepAgent] No prompt in this chat — stopping');
      stopAgent();
    }
  }

  /* ── URL change detection (SPA navigation) ────────────── */

  function watchUrl() {
    if (state._urlCheckTimer) return;
    state._urlCheckTimer = setInterval(() => {
      const urlChanged = location.href !== state._lastUrl;
      if (urlChanged) {
        state._lastUrl = location.href;
        console.log('[DeepAgent] URL changed — rechecking chat');
        setTimeout(checkChatState, 500);
      } else if (!state.observer) {
        checkChatState();
      }
    }, 1500);
  }

  /* ── Panel UI ──────────────────────────────────────────── */

  function updatePanelStatus() {
    const status = state.panel?.querySelector('.da-status');
    if (!status) return;
    if (state._currentCommand) {
      const cmd = state._currentCommand.length > 30
        ? state._currentCommand.slice(0, 30) + '…'
        : state._currentCommand;
      const q = state.commandQueue.length;
      status.textContent = q > 0 ? `▶ ${cmd} (+${q})` : `▶ ${cmd}`;
    } else if (state.commandQueue.length > 0) {
      status.textContent = `⏳ ${state.commandQueue.length} queued`;
    } else {
      status.textContent = '';
    }
  }

  let _healthTimer = null;

  function startHealthCheck() {
    stopHealthCheck();
    _healthTimer = setInterval(async () => {
      const alive = await checkBridgeHealth();
      const dot = state.panel?.querySelector('.da-dot');
      const label = state.panel?.querySelector('.da-label');
      if (dot) {
        if (!alive) {
          dot.className = 'da-dot error';
          dot.title = 'Bridge server not responding';
          if (label && !state.observer) label.textContent = 'Bridge offline';
        } else {
          dot.className = 'da-dot on';
          dot.title = 'Bridge connected';
          if (label && !state.observer) label.textContent = 'Bridge connected';
        }
      }
    }, 3000);
  }

  function stopHealthCheck() {
    if (_healthTimer) {
      clearInterval(_healthTimer);
      _healthTimer = null;
    }
  }

  function updatePanel(active) {
    const label = state.panel?.querySelector('.da-label');
    const btn = state.panel?.querySelector('.da-btn');
    if (!btn) return;
    if (active) {
      btn.textContent = 'Stop';
      btn.classList.add('active');
      if (label) label.textContent = 'Agent Running';
    } else {
      btn.textContent = 'Start';
      btn.classList.remove('active');
      if (label) label.textContent = 'Agent Stopped';
    }
    updatePanelStatus();
  }

  async function resetTerminal() {
    try {
      await bridgeSend({ action: 'reset' });
    } catch {}
  }

  function injectPromptAndStart() {
    const ta = getInput();
    if (!ta) return;
    const hasPrompt = promptInDOM();
    if (!hasPrompt) {
      document.body.dataset.daPromptSent = '1';
      resetTerminal();
      setInputValue(ta, AGENT_PROMPT);
      setTimeout(sendMessage, 400);
      console.log('[DeepAgent] Prompt injected');
    } else {
      console.log('[DeepAgent] Prompt already in this chat');
    }
    _userStopped = false;
    startAgent();
  }

  function createPanel() {
    const styleId = 'deepagent-style';
    if (!document.getElementById(styleId)) {
      const s = document.createElement('style');
      s.id = styleId;
      s.textContent = [
        '#deepagent-panel{all:initial;position:fixed;top:20px;right:20px;z-index:2147483647;background:#0f0f1a;border:1px solid #2a2a4a;border-radius:14px;padding:12px 18px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:13px;color:#d0d0e0;box-shadow:0 8px 40px rgba(0,0,0,.5);display:flex;flex-direction:column;gap:6px;min-width:220px;user-select:none;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}',
        '#deepagent-panel .da-row{display:flex;align-items:center;gap:10px}',
        '#deepagent-panel .da-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;transition:background .3s}',
        '#deepagent-panel .da-dot.off{background:#ef4444;box-shadow:0 0 8px #ef444488}',
        '#deepagent-panel .da-dot.on{background:#22c55e;box-shadow:0 0 8px #22c55e88}',
        '#deepagent-panel .da-dot.error{background:#f59e0b;box-shadow:0 0 8px #f59e0b88}',
        '#deepagent-panel .da-label{flex:1;font-size:13px;font-weight:500}',
        '#deepagent-panel .da-btn{background:#2a2a4a;border:none;color:#d0d0e0;padding:6px 16px;border-radius:8px;cursor:pointer;font-size:12px;font-weight:600;transition:background .2s}',
        '#deepagent-panel .da-btn:hover{background:#3a3a5a}',
        '#deepagent-panel .da-btn.active{background:#22c55e;color:#0a0a12}',
        '#deepagent-panel .da-btn.active:hover{background:#1da34e}',
        '#deepagent-panel .da-status{font-size:11px;color:#8888aa;padding:0 2px;min-height:16px;word-break:break-all}',
      ].join('');
      document.head.appendChild(s);
    }
    const panel = document.createElement('div');
    panel.id = 'deepagent-panel';
    panel.innerHTML =
      '<div class="da-row">' +
        '<div class="da-dot off"></div>' +
        '<span class="da-label">Agent Stopped</span>' +
        '<button class="da-btn">Start</button>' +
      '</div>' +
      '<div class="da-status"></div>';
    document.body.appendChild(panel);
    state.panel = panel;
    console.log('[DeepAgent] Panel injected');

    panel.querySelector('.da-btn').addEventListener('click', () => {
      if (state.observer) {
        _userStopped = true;
        stopAgent();
      } else {
        injectPromptAndStart();
      }
    });
  }

  /* ── Bootstrap ─────────────────────────────────────────── */

  async function bootstrap() {
    if (document.readyState === 'loading') {
      await new Promise((r) => document.addEventListener('DOMContentLoaded', r));
    }
    await loadHashes();
    createPanel();
    startHealthCheck();
    watchUrl();
    state._lastUrl = location.href;
    checkChatState();
  }

  bootstrap();
})();
