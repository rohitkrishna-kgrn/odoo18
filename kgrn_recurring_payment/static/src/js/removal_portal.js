/**
 * KGRN Recurring Payment – Card Removal Request Portal
 * Handles the customer-facing "Request Cancellation" flow.
 */
(function () {
    'use strict';

    var TOKEN = window.KGRN_TOKEN || location.pathname.split('/card/')[1] || '';

    var toggleBtn  = document.getElementById('toggleRemovalForm');
    var removalForm = document.getElementById('removalForm');
    var submitBtn  = document.getElementById('submitRemoval');

    if (toggleBtn && removalForm) {
        toggleBtn.addEventListener('click', function () {
            var isVisible = removalForm.style.display !== 'none';
            removalForm.style.display = isVisible ? 'none' : 'flex';
            toggleBtn.textContent = isVisible
                ? 'Request Service Cancellation'
                : 'Hide Cancellation Form';
        });
    }

    if (submitBtn) {
        submitBtn.addEventListener('click', function () {
            var reason = (document.getElementById('removalReason').value || '').trim();
            var errorEl   = document.getElementById('removalError');
            var successEl = document.getElementById('removalSuccess');

            errorEl.style.display = 'none';
            successEl.style.display = 'none';
            submitBtn.disabled = true;
            submitBtn.textContent = 'Submitting…';

            fetch('/kgrn/recurring/card/' + TOKEN + '/request-removal', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: reason }),
            })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Submit Cancellation Request';
                if (data.error) {
                    errorEl.textContent = data.error;
                    errorEl.style.display = 'block';
                    return;
                }
                successEl.textContent = data.message || 'Request submitted successfully.';
                successEl.style.display = 'block';
                submitBtn.disabled = true;
                if (toggleBtn) toggleBtn.disabled = true;
                // Reload after delay to show updated state
                setTimeout(function () { window.location.reload(); }, 2500);
            })
            .catch(function () {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Submit Cancellation Request';
                errorEl.textContent = 'Network error. Please try again.';
                errorEl.style.display = 'block';
            });
        });
    }

})();
