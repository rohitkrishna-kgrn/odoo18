/**
 * KGRN Recurring Payment – Stripe Card Setup Portal
 *
 * Handles the Stripe Elements card input flow:
 *   1. Initialize Stripe with the publishable key
 *   2. Mount a Card Element
 *   3. On submit: create a SetupIntent via backend, then confirmCardSetup
 *   4. On success: POST the payment method ID to backend to persist card
 */
(function () {
    'use strict';

    // Config injected by the QWeb template
    var STRIPE_KEY  = window.KGRN_STRIPE_KEY  || '';
    var TOKEN       = window.KGRN_TOKEN        || '';
    var CUSTOMER    = window.KGRN_CUSTOMER     || '';

    if (!STRIPE_KEY) {
        showError('formError', 'Payment configuration error. Please contact support.');
        return;
    }

    var stripe = Stripe(STRIPE_KEY);    // eslint-disable-line no-undef
    var elements = stripe.elements({
        fonts: [{ cssSrc: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500&display=swap' }],
    });

    // Stripe card element style
    var cardStyle = {
        base: {
            color: '#111827',
            fontFamily: 'Segoe UI, system-ui, -apple-system, sans-serif',
            fontSize: '15px',
            fontSmoothing: 'antialiased',
            '::placeholder': { color: '#9ca3af' },
        },
        invalid: { color: '#dc2626', iconColor: '#dc2626' },
    };

    var cardElement = elements.create('card', { style: cardStyle, hidePostalCode: false });
    cardElement.mount('#cardElement');

    // Live validation feedback
    cardElement.on('change', function (event) {
        var errorEl = document.getElementById('cardErrors');
        if (event.error) {
            errorEl.textContent = event.error.message;
        } else {
            errorEl.textContent = '';
        }
    });

    // Form submission
    var form     = document.getElementById('paymentForm');
    var submitBtn = document.getElementById('submitBtn');

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        handleSubmit();
    });

    function handleSubmit() {
        var cardholderName = document.getElementById('cardholderName').value.trim();
        if (!cardholderName) {
            showError('formError', 'Please enter the cardholder name.');
            return;
        }

        setLoading(true);
        hideMessage('formError');
        hideMessage('formSuccess');

        // Step 1: Create SetupIntent on backend
        fetch('/kgrn/recurring/card/' + TOKEN + '/create-setup-intent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.error) {
                setLoading(false);
                showError('formError', data.error);
                return;
            }
            // Step 2: Confirm card setup with Stripe
            return stripe.confirmCardSetup(data.client_secret, {
                payment_method: {
                    card: cardElement,
                    billing_details: { name: cardholderName },
                },
            });
        })
        .then(function (result) {
            if (!result) return;  // already handled above
            if (result.error) {
                setLoading(false);
                showError('formError', result.error.message);
                return;
            }
            // Step 3: Send PM ID to backend to persist
            var pm = result.setupIntent.payment_method;
            return fetch('/kgrn/recurring/card/' + TOKEN + '/save-card', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    payment_method_id: pm,
                    card_holder_name: cardholderName,
                }),
            });
        })
        .then(function (res) {
            if (!res) return;
            return res.json();
        })
        .then(function (data) {
            if (!data) return;
            setLoading(false);
            if (data.error) {
                showError('formError', data.error);
                return;
            }
            // Success – reload page to show card-registered state
            showSuccess('formSuccess', 'Card saved successfully! Loading your subscription details…');
            submitBtn.disabled = true;
            setTimeout(function () {
                window.location.reload();
            }, 1800);
        })
        .catch(function (err) {
            setLoading(false);
            showError('formError', 'A network error occurred. Please try again.');
            console.error('KGRN Stripe error:', err);
        });
    }

    // ── Helpers ──────────────────────────────────────────────

    function setLoading(loading) {
        submitBtn.disabled = loading;
        document.getElementById('submitBtnText').style.display = loading ? 'none' : 'inline';
        document.getElementById('submitSpinner').style.display = loading ? 'inline-block' : 'none';
    }

    function showError(id, msg) {
        var el = document.getElementById(id);
        if (el) { el.textContent = msg; el.style.display = 'block'; }
    }

    function showSuccess(id, msg) {
        var el = document.getElementById(id);
        if (el) { el.textContent = msg; el.style.display = 'block'; }
    }

    function hideMessage(id) {
        var el = document.getElementById(id);
        if (el) { el.style.display = 'none'; el.textContent = ''; }
    }

})();
