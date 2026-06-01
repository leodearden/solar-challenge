// SPDX-License-Identifier: AGPL-3.0-or-later
// AI Assistant chat UI — vanilla JS, no framework.
// Reads endpoint URLs from data-* attributes on #assistant-chat.
// Uses fetch() + response.body.getReader() for SSE streaming (not EventSource,
// because the chat POSTs a message body).

(function () {
  'use strict';

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const chatRoot = document.getElementById('assistant-chat');
  if (!chatRoot) return;

  const chatMessages = document.getElementById('chat-messages');
  const chatInput = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send');

  const chatUrl = chatRoot.dataset.chatUrl;
  const historyUrl = chatRoot.dataset.historyUrl;

  // ── Helpers ──────────────────────────────────────────────────────────────

  /** Append a message bubble to the chat pane. */
  function appendBubble(role, text) {
    const isUser = role === 'user';
    const wrapper = document.createElement('div');
    wrapper.className = 'flex items-start gap-3' + (isUser ? ' flex-row-reverse' : '');

    const avatar = document.createElement('div');
    avatar.className = 'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ' +
      (isUser
        ? 'bg-amber-500 text-white'
        : 'bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400');
    avatar.textContent = isUser ? 'You' : 'AI';

    const bubble = document.createElement('div');
    bubble.className = 'flex-1 rounded-lg px-4 py-3 text-sm ' +
      (isUser
        ? 'bg-amber-500 text-white'
        : 'bg-slate-50 dark:bg-slate-700/50 text-slate-700 dark:text-slate-200');
    bubble.textContent = text;

    wrapper.appendChild(avatar);
    wrapper.appendChild(bubble);
    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return bubble;
  }

  /** Show an error notice in the chat pane. */
  function showError(message) {
    const div = document.createElement('div');
    div.className = 'rounded-lg border border-red-200 bg-red-50 dark:bg-red-900/20 dark:border-red-700 px-4 py-2 text-sm text-red-700 dark:text-red-300';
    div.textContent = '⚠ ' + message;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // ── Load history on page load ─────────────────────────────────────────────

  async function loadHistory() {
    if (!historyUrl) return;
    try {
      const resp = await fetch(historyUrl);
      if (!resp.ok) return;
      const data = await resp.json();
      const messages = data.messages || [];
      // Remove intro placeholder if there is actual history
      if (messages.length > 0) {
        const intro = chatMessages.querySelector('.flex.items-start.gap-3');
        if (intro) intro.remove();
        for (const msg of messages) {
          appendBubble(msg.role, msg.content);
        }
      }
    } catch (_e) {
      // History load failure is non-fatal
    }
  }

  // ── Send a message ────────────────────────────────────────────────────────

  async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;

    chatInput.value = '';
    sendBtn.disabled = true;

    appendBubble('user', text);

    // Placeholder bubble for the streaming reply
    const replyBubble = appendBubble('assistant', '');

    try {
      const resp = await fetch(chatUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });

      if (!resp.ok) {
        replyBubble.textContent = 'Error: server returned ' + resp.status;
        sendBtn.disabled = false;
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let accumulated = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE frames from buffer — frames are separated by \n\n
        const frames = buffer.split('\n\n');
        buffer = frames.pop(); // last element may be incomplete

        for (const frame of frames) {
          let eventType = 'message';
          let dataLine = '';

          for (const line of frame.split('\n')) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              dataLine = line.slice(6);
            }
          }

          if (!dataLine) continue;

          if (eventType === 'delta') {
            try {
              const payload = JSON.parse(dataLine);
              if (payload.text) {
                accumulated += payload.text;
                replyBubble.textContent = accumulated;
                chatMessages.scrollTop = chatMessages.scrollHeight;
              }
            } catch (_e) { /* ignore malformed */ }
          } else if (eventType === 'done') {
            // Stream complete
          } else if (eventType === 'error') {
            try {
              const payload = JSON.parse(dataLine);
              replyBubble.remove();
              showError(payload.message || 'Unknown error');
            } catch (_e) {
              replyBubble.remove();
              showError('Unknown streaming error');
            }
          }
        }
      }
    } catch (err) {
      replyBubble.textContent = 'Error: ' + err.message;
    } finally {
      sendBtn.disabled = false;
      chatInput.focus();
    }
  }

  // ── Event bindings ────────────────────────────────────────────────────────

  sendBtn.addEventListener('click', sendMessage);

  chatInput.addEventListener('keydown', function (e) {
    // Ctrl+Enter or Cmd+Enter sends
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ── Initialise ────────────────────────────────────────────────────────────

  loadHistory();
})();
