/**
 * KönyvelőAI — frontend logic
 */

function initChat(sessionId) {
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const messagesEl = document.getElementById('chat-messages');
    const sendBtn = document.getElementById('send-btn');
    const loadingEl = document.getElementById('loading-indicator');
    const titleEl = document.getElementById('chat-title');

    loadSessions();
    scrollToBottom();

    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        const msg = input.value.trim();
        if (!msg) return;

        input.value = '';
        input.disabled = true;
        sendBtn.disabled = true;
        loadingEl.style.display = 'flex';

        // Add user message to UI
        addMessage('user', msg);

        try {
            const resp = await fetch(`/api/chat/${sessionId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: msg}),
            });
            const data = await resp.json();

            if (data.error) {
                addMessage('assistant', '❌ ' + data.error);
                return;
            }

            // Update title if changed
            if (data.title && titleEl) {
                titleEl.textContent = data.title;
            }

            // Build sources HTML
            let responseText = data.reply;
            if (data.sources && data.sources.length > 0) {
                responseText += '\n\n📎 **Források:**';
                for (const s of data.sources) {
                    responseText += `\n- ${s.source}: ${s.title}`;
                }
            }

            addMessage('assistant', responseText, data.sources);
            loadSessions();

        } catch (err) {
            addMessage('assistant', '❌ Hálózati hiba. Ellenőrizd a kapcsolatot.');
        } finally {
            input.disabled = false;
            sendBtn.disabled = false;
            loadingEl.style.display = 'none';
            input.focus();
        }
    });
}

function addMessage(role, content, sources) {
    const messagesEl = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `message message-${role}`;

    // Basic markdown: **bold** and URLs
    let html = content
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/https?:\/\/[^\s]+/g, '<a href="$&" target="_blank">$&</a>')
        .replace(/\n/g, '<br>');

    div.innerHTML = '<div class="msg-content">' + html + '</div>';

    if (sources && sources.length > 0) {
        const sourcesEl = document.createElement('div');
        sourcesEl.className = 'msg-sources';
        let srcHtml = '📎 ';
        srcHtml += sources.map(s => `${s.source}: ${s.title || ''}`).join(' | ');
        sourcesEl.innerHTML = srcHtml;
        div.appendChild(sourcesEl);
    }

    messagesEl.appendChild(div);
    scrollToBottom();

    // Remove welcome message if present
    const welcome = messagesEl.querySelector('.welcome-msg');
    if (welcome) welcome.remove();
}

function scrollToBottom() {
    const messagesEl = document.getElementById('chat-messages');
    if (messagesEl) {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }
}

async function loadSessions() {
    const sidebar = document.getElementById('session-list');
    if (!sidebar) return;

    try {
        const resp = await fetch('/api/sessions');
        const sessions = await resp.json();
        if (!sessions || sessions.length === 0) {
            sidebar.innerHTML = '<div class="empty-state" style="font-size:12px;padding:8px;">Nincs beszélgetés</div>';
            return;
        }
        sidebar.innerHTML = sessions.map(s => {
            const isActive = s.id === SESSION_ID;
            return `<a href="/chat/${s.id}" class="sidebar-item${isActive ? ' active' : ''}">${escapeHtml(s.title)}</a>`;
        }).join('');
    } catch (err) {
        if (sidebar) sidebar.innerHTML = '<div style="font-size:12px;color:var(--danger);padding:8px;">Hiba a betöltéskor</div>';
    }
}

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
}