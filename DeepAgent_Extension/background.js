const TOKEN_STORAGE_KEY = 'deepagent_token';

function getToken() {
  return new Promise((resolve) => {
    chrome.storage.local.get(TOKEN_STORAGE_KEY, (res) => {
      resolve(res[TOKEN_STORAGE_KEY] || '');
    });
  });
}

async function bridgeFetch(endpoint, body) {
  const token = await getToken();
  const url = `http://localhost:8765${endpoint}`;
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-DeepAgent-Token': token,
    },
    body: JSON.stringify(body),
  });
  return resp.json();
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'execute') {
    bridgeFetch('/execute', { command: request.command })
      .then(sendResponse)
      .catch((e) => sendResponse({ error: e.message }));
    return true;
  }
  if (request.action === 'ping') {
    fetch('http://localhost:8765/ping', { signal: AbortSignal.timeout(3000) })
      .then((r) => r.json())
      .then(sendResponse)
      .catch(() => sendResponse({ status: 'dead', shell_alive: false }));
    return true;
  }
  if (request.action === 'reset') {
    bridgeFetch('/execute', { command: '__RESET__' })
      .then(sendResponse)
      .catch((e) => sendResponse({ error: e.message }));
    return true;
  }
});
