/**
 * Adókód-mapping UI
 */
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('mapping-form');
    const suggestBtn = document.getElementById('suggest-btn');
    const filterSelect = document.getElementById('filter-client');
    const suggestionBox = document.getElementById('suggestion-result');
    const newBtn = document.getElementById('new-mapping-btn');

    // Load audit trail
    loadAudit();

    // Filter mappings
    filterSelect.addEventListener('change', function() {
        const client = this.value;
        document.querySelectorAll('.mapping-item').forEach(item => {
            if (!client || item.dataset.client === client) {
                item.style.display = 'flex';
            } else {
                item.style.display = 'none';
            }
        });
    });

    // Click on mapping item to edit
    document.querySelectorAll('.mapping-item').forEach(item => {
        item.addEventListener('click', function() {
            loadMapping(this.dataset.id);
        });
    });

    // AI suggestion
    suggestBtn.addEventListener('click', async function() {
        const code = document.getElementById('internal-code').value.trim();
        const desc = document.getElementById('desc').value.trim();
        if (!code) {
            alert('Add meg a belső kódot előbb!');
            return;
        }
        suggestBtn.disabled = true;
        suggestBtn.textContent = '⏳ Gondolkodik…';
        suggestionBox.style.display = 'block';
        suggestionBox.innerHTML = '<p>🤖 AI javaslat betöltése…</p>';

        try {
            const resp = await fetch('/mapping/api/suggest', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({internal_code: code, description: desc}),
            });
            const data = await resp.json();
            suggestionBox.innerHTML = '<pre>' + escapeHtml(data.suggestion) + '</pre>';
        } catch (err) {
            suggestionBox.innerHTML = '<p class="error">❌ Hiba a javaslat betöltésekor</p>';
        } finally {
            suggestBtn.disabled = false;
            suggestBtn.textContent = '🤖 AI javaslat';
        }
    });

    // Save mapping
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        const data = {
            internal_code: document.getElementById('internal-code').value.trim(),
            nav_code: document.getElementById('nav-code').value.trim(),
            vat_rate: document.getElementById('vat-rate').value,
            reverse_charge: document.getElementById('reverse-charge').checked,
            description: document.getElementById('desc').value.trim(),
            client_name: document.getElementById('client-select').value,
            reason: document.getElementById('mapping-reason').value.trim(),
            source: 'manual',
        };

        try {
            const resp = await fetch('/mapping/api/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data),
            });
            const result = await resp.json();
            if (result.error) {
                alert(result.error);
            } else {
                location.reload();
            }
        } catch (err) {
            alert('Hiba a mentéskor');
        }
    });

    // New mapping (clear form)
    newBtn.addEventListener('click', function() {
        form.reset();
        suggestionBox.style.display = 'none';
    });
});

function loadMapping(id) {
    // For simplicity, just set filter to all and scroll to form
    document.getElementById('mapping-reason').value = 'módosítás';
    document.getElementById('internal-code').value = document.querySelector(`.mapping-item[data-id="${id}"] .internal-code`).textContent.trim();
    window.scrollTo({top: 0, behavior: 'smooth'});
}

async function loadAudit() {
    const container = document.getElementById('audit-list');
    try {
        const resp = await fetch('/mapping/api/audit?limit=30');
        const logs = await resp.json();
        if (!logs || logs.length === 0) {
            container.innerHTML = '<p class="empty-state">Még nincs audit bejegyzés</p>';
            return;
        }
        container.innerHTML = logs.map(log => {
            const date = log.created_at ? new Date(log.created_at).toLocaleString('hu-HU') : '';
            return `<div class="audit-item">
                <span class="audit-action">${escapeHtml(log.action)}</span>
                <span class="audit-entity">${escapeHtml(log.entity_type)}</span>
                <span class="audit-reason">${escapeHtml(log.reason)}</span>
                <span class="audit-date">${date}</span>
            </div>`;
        }).join('');
    } catch (err) {
        container.innerHTML = '<p class="error">❌ Hiba az audit betöltésekor</p>';
    }
}

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
}