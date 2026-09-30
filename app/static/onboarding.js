/**
 * Onboarding checklist
 */
document.addEventListener('DOMContentLoaded', function() {
    const select = document.getElementById('onboarding-client-select');
    const initBtn = document.getElementById('init-onboarding-btn');

    select.addEventListener('change', function() {
        initBtn.disabled = !this.value;
    });

    initBtn.addEventListener('click', async function() {
        const clientId = select.value;
        if (!clientId) return;
        initBtn.disabled = true;
        initBtn.textContent = '⏳…';

        try {
            const resp = await fetch(`/clients/api/onboarding/init/${clientId}`, {method: 'POST'});
            const data = await resp.json();
            if (data.ok) {
                location.reload();
            }
        } catch (err) {
            alert('Hiba az onboarding létrehozásakor');
        } finally {
            initBtn.disabled = false;
            initBtn.textContent = 'Létrehoz';
        }
    });

    // Step status toggle
    document.querySelectorAll('.onboarding-step').forEach(step => {
        step.addEventListener('click', async function() {
            const stepId = this.dataset.stepId;
            const currentStatus = this.querySelector('.step-status');
            const nextStatus = currentStatus.textContent.trim() === 'pending' ? 'in_progress'
                            : currentStatus.textContent.trim() === 'in_progress' ? 'done'
                            : 'pending';

            try {
                const resp = await fetch(`/clients/api/onboarding/update/${stepId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({status: nextStatus}),
                });
                const data = await resp.json();
                if (data.ok) {
                    currentStatus.textContent = nextStatus;
                    currentStatus.className = 'step-status status-' + nextStatus;
                }
            } catch (err) {
                alert('Hiba a státusz frissítésekor');
            }
        });
    });
});