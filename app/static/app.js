/**
 * KönyvelőAI — frontend logic
 * Streaming (SSE) chat + Leállítás gomb + beszélgetés törlés
 */

let ABORT_CTRL = null;
let STREAMING = false;

function initChat(sessionId) {
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const loadingEl = document.getElementById('loading-indicator');
    const titleEl = document.getElementById('chat-title');

    loadSessions();
    scrollToBottom();

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const msg = input.value.trim();
        if (!msg || STREAMING) return;

        input.value = '';
        input.disabled = true;
        sendBtn.disabled = true;
        loadingEl.style.display = 'flex';
        setLoadingText('Források keresése…');

        addMessage('user', msg);

        // Placeholder az AI válasznak — ide streamelünk
        const bubble = addMessage('assistant', '', null, true);

        ABORT_CTRL = new AbortController();
        STREAMING = true;
        let acc = '';
        let sources = [];
        let done = false;

        try {
            const resp = await fetch(`/api/chat/${sessionId}/stream`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: msg}),
                signal: ABORT_CTRL.signal,
            });

            if (!resp.ok) {
                let errText = `HTTP ${resp.status}`;
                try {
                    const j = await resp.json();
                    if (j.error) errText = j.error;
                } catch (_) {}
                bubble.remove();
                addMessage('assistant', '❌ ' + errText);
                return;
            }

            const reader = resp.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buf = '';
            let gotAnyDelta = false;

            while (true) {
                const {value, done: rdone} = await reader.read();
                if (rdone) break;
                buf += decoder.decode(value, {stream: true});

                let idx;
                while ((idx = buf.indexOf('\n\n')) !== -1) {
                    const block = buf.slice(0, idx);
                    buf = buf.slice(idx + 2);
                    const parsed = parseSSE(block);
                    if (!parsed) continue;

                    if (parsed.event === 'sources') {
                        sources = parsed.data.sources || [];
                        setLoadingText('Válasz generálása…');
                    } else if (parsed.event === 'delta') {
                        if (!acc) setLoadingText('Válasz generálása…');
                        acc += parsed.data.t || '';
                        gotAnyDelta = true;
                        updateBubble(bubble, acc);
                    } else if (parsed.event === 'done') {
                        done = true;
                        if (parsed.data.title && titleEl) titleEl.textContent = parsed.data.title;
                    } else if (parsed.event === 'error') {
                        done = true;
                        if (!acc) {
                            bubble.remove();
                            addMessage('assistant', '❌ ' + (parsed.data.error || 'Hiba'));
                        } else {
                            acc += `\n\n⚠️ ${parsed.data.error}`;
                            updateBubble(bubble, acc);
                        }
                    }
                }
            }

            // Ha stream közben leállítottuk: jelezzük a részleges választ
            if (acc) {
                if (!done) {
                    acc += '\n\n_(leállítva)_';
                }
                updateBubble(bubble, acc);
                attachSources(bubble, sources);
            } else if (!done && !gotAnyDelta) {
                // A proxy megszakította a streamet, mielőtt bármi jött volna:
                // essünk vissza a nem-streaming végpontra (ugyanaz a user üzenet, nincs duplikáció)
                bubble.remove();
                const okFallback = await fallbackRequest(sessionId, msg, titleEl);
                if (!okFallback) addMessage('assistant', '❌ Hálózati hiba. Ellenőrizd a kapcsolatot.');
            } else if (!done) {
                bubble.remove();
            }
            loadSessions();

        } catch (err) {
            if (err && (err.name === 'AbortError')) {
                if (acc) {
                    updateBubble(bubble, acc + '\n\n_(leállítva)_');
                    attachSources(bubble, sources);
                } else {
                    bubble.remove();
                    addMessage('assistant', '⏹ Leállítva.');
                }
            } else if (!acc) {
                // Hálózati hiba streamelés előtt → nem-streaming fallback
                bubble.remove();
                const okFb = await fallbackRequest(sessionId, msg, titleEl);
                if (!okFb) addMessage('assistant', '❌ Hálózati hiba. Ellenőrizd a kapcsolatot.');
            } else {
                updateBubble(bubble, acc + '\n\n⚠️ A kapcsolat megszakadt.');
                attachSources(bubble, sources);
            }
        } finally {
            STREAMING = false;
            ABORT_CTRL = null;
            input.disabled = false;
            sendBtn.disabled = false;
            loadingEl.style.display = 'none';
            input.focus();
        }
    });
}

function setLoadingText(t) {
    const el = document.getElementById('loading-text');
    if (el) el.textContent = t;
}

/**
 * Nem-streaming tartalék: akkor fut, ha a proxy megszakítja az SSE streamet.
 * A szerver oldali dedupe miatt nem keletkezik dupla user üzenet.
 */
async function fallbackRequest(sessionId, msg, titleEl) {
    try {
        setLoadingText('Újrapróbálás (nem-streaming)…');
        const resp = await fetch(`/api/chat/${sessionId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: msg, retry: true}),
        });
        const data = await resp.json();
        if (data.error) {
            addMessage('assistant', '❌ ' + data.error);
            return true;
        }
        if (data.title && titleEl) titleEl.textContent = data.title;
        addMessage('assistant', data.reply, data.sources);
        return true;
    } catch (e) {
        return false;
    }
}

function stopGeneration() {
    if (ABORT_CTRL) {
        ABORT_CTRL.abort();
        setLoadingText('Leállítás…');
    }
}

// SSE blokk feldolgozása: "event: x\ndata: {...}"
function parseSSE(block) {
    let event = 'message';
    const dataLines = [];
    for (const raw of block.split('\n')) {
        const line = raw.trim();
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) return null;
    try {
        return {event, data: JSON.parse(dataLines.join('\n'))};
    } catch (_) {
        return null;
    }
}

function renderMarkdown(content) {
    return (content || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
        .replace(/\n/g, '<br>');
}

function updateBubble(div, content) {
    let c = div.querySelector('.msg-content');
    if (!c) {
        c = document.createElement('div');
        c.className = 'msg-content';
        div.appendChild(c);
    }
    c.innerHTML = renderMarkdown(content) + '<span class="cursor-blink">▋</span>';
    scrollToBottom();
}

function attachSources(div, sources) {
    if (!sources || !sources.length) return;
    const old = div.querySelector('.msg-sources');
    if (old) old.remove();
    const el = document.createElement('div');
    el.className = 'msg-sources';
    el.innerHTML = '<div class="sources-title">📎 Források (' + sources.length + ')</div>' +
        '<div class="source-chips">' +
        sources.map(s => `<span class="source-chip">${escapeHtml(s.source || '')}${s.year ? ' ' + escapeHtml(s.year) : ''}${s.title ? ' <em>' + escapeHtml(String(s.title).slice(0, 60)) + '</em>' : ''}</span>`).join('') +
        '</div>';
    div.appendChild(el);
}

function addMessage(role, content, sources, isPlaceholder) {
    const messagesEl = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `message message-${role}`;

    if (content || !isPlaceholder) {
        const c = document.createElement('div');
        c.className = 'msg-content';
        c.innerHTML = renderMarkdown(content);
        div.appendChild(c);
    }

    if (sources && sources.length > 0) attachSources(div, sources);

    messagesEl.appendChild(div);
    scrollToBottom();

    const welcome = messagesEl.querySelector('.welcome-msg');
    if (welcome) welcome.remove();

    return div;
}

function scrollToBottom() {
    const messagesEl = document.getElementById('chat-messages');
    if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
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
            return `<div class="sidebar-row${isActive ? ' active' : ''}" data-id="${s.id}">
                <a href="/chat/${s.id}" class="sidebar-item">${escapeHtml(s.title || 'Új beszélgetés')}</a>
                <button class="btn-del-sidebar" title="Törlés" onclick="deleteSession(${s.id}, event)">🗑</button>
            </div>`;
        }).join('');
    } catch (err) {
        sidebar.innerHTML = '<div style="font-size:12px;color:var(--danger);padding:8px;">Hiba a betöltéskor</div>';
    }
}

async function deleteSession(id, ev) {
    if (ev) { ev.preventDefault(); ev.stopPropagation(); }
    if (!confirm('Biztosan törlöd ezt a beszélgetést? Ez nem visszavonható.')) return;

    try {
        const resp = await fetch('/api/sessions/' + id, {method: 'DELETE'});
        if (!resp.ok) { alert('A törlés nem sikerült.'); return; }
        if (id === SESSION_ID) {
            window.location.href = '/';
            return;
        }
        const row = document.querySelector(`.sidebar-row[data-id="${id}"]`);
        if (row) row.remove();
    } catch (err) {
        alert('Hálózati hiba a törléskor.');
    }
}

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
}
