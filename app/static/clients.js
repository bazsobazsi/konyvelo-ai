/**
 * Ügyfél profilok + threshold riasztások
 */
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('client-form');
    const clearBtn = document.getElementById('client-clear');

    // Edit client
    document.querySelectorAll('.edit-client').forEach(btn => {
        btn.addEventListener('click', function() {
            const item = this.closest('.client-item');
            loadClient(item.dataset.id);
        });
    });

    // Delete client
    document.querySelectorAll('.delete-client').forEach(btn => {
        btn.addEventListener('click', async function() {
            if (!confirm('Biztosan törlöd?')) return;
            const item = this.closest('.client-item');
            try {
                const resp = await fetch(`/clients/api/delete/${item.dataset.id}`, {method: 'DELETE'});
                const data = await resp.json();
                if (data.ok) location.reload();
            } catch (err) {
                alert('Hiba a törléskor');
            }
        });
    });

    // Save form
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        const data = {
            id: document.getElementById('client-id').value || null,
            name: document.getElementById('client-name').value.trim(),
            tax_number: document.getElementById('client-tax').value.trim(),
            profile_type: document.getElementById('client-type').value,
            annual_revenue: parseInt(document.getElementById('client-revenue').value) || 0,
            employee_count: parseInt(document.getElementById('client-employees').value) || 0,
            vat_quarterly: document.getElementById('client-vat-quarterly').checked,
            vat_exempt: document.getElementById('client-vat-exempt').checked,
            kiva_elective: document.getElementById('client-kiva').checked,
        };

        try {
            const resp = await fetch('/clients/api/save', {
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

    // Clear form
    clearBtn.addEventListener('click', function() {
        form.reset();
        document.getElementById('client-id').value = '';
        document.getElementById('client-form-title').textContent = 'Új ügyfél';
    });
});

function loadClient(id) {
    const item = document.querySelector(`.client-item[data-id="${id}"]`);
    if (!item) return;

    document.getElementById('client-form-title').textContent = 'Ügyfél szerkesztése';
    document.getElementById('client-id').value = id;

    // We need to fetch the data
    fetch('/clients/api/list')
        .then(r => r.json())
        .then(clients => {
            const c = clients.find(x => x.id == id);
            if (!c) return;
            document.getElementById('client-name').value = c.name;
            document.getElementById('client-tax').value = c.tax_number;
            document.getElementById('client-type').value = c.profile_type;
            document.getElementById('client-revenue').value = c.annual_revenue;
            document.getElementById('client-employees').value = c.employee_count;
            document.getElementById('client-vat-quarterly').checked = c.vat_quarterly;
            document.getElementById('client-vat-exempt').checked = c.vat_exempt;
            document.getElementById('client-kiva').checked = c.kiva_elective;
            window.scrollTo({top: 0, behavior: 'smooth'});
        });
}

async function dismissAlert(id) {
    try {
        const resp = await fetch(`/clients/api/alerts/dismiss/${id}`, {method: 'POST'});
        const data = await resp.json();
        if (data.ok) {
            const card = document.querySelector(`.alert-card[data-id="${id}"]`);
            if (card) card.remove();
            // If no alerts left, show empty state
            if (document.querySelectorAll('.alert-card').length === 0) {
                document.getElementById('alert-list').innerHTML = '<p class="empty-state">✅ Nincs függő riasztás</p>';
            }
        }
    } catch (err) {
        console.error('Dismiss error:', err);
    }
}