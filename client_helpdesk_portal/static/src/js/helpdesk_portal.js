/* Client Helpdesk Portal – Public form interactivity */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        initTypeCards();
        initPriorityCards();
        initDropzone();
        initCharCounter();
        initSubmitButton();
    });

    /* ──────────────────────────────────────────────────────────────
       REQUEST TYPE CARDS
    ────────────────────────────────────────────────────────────── */
    function initTypeCards() {
        var cards  = document.querySelectorAll('.hd-type-card');
        var hidden = document.getElementById('request_type_hidden');
        var errBox = document.getElementById('hd-type-error');
        if (!cards.length || !hidden) return;

        // Restore server-side selection on validation-error reload
        if (hidden.value) {
            activateCard(hidden.value);
        }

        cards.forEach(function (card) {
            card.addEventListener('click', function () {
                activateCard(this.getAttribute('data-value'));
                if (errBox) errBox.style.display = 'none';
            });
            card.setAttribute('tabindex', '0');
            card.setAttribute('role', 'radio');
            card.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    card.click();
                }
            });
        });

        function activateCard(value) {
            cards.forEach(function (c) {
                var isTarget = c.getAttribute('data-value') === value;
                c.classList.toggle('active', isTarget);
                c.setAttribute('aria-checked', isTarget ? 'true' : 'false');
            });
            hidden.value = value;
        }
    }

    /* ──────────────────────────────────────────────────────────────
       PRIORITY CARDS
    ────────────────────────────────────────────────────────────── */
    function initPriorityCards() {
        var labels = document.querySelectorAll('.hd-priority-card');
        if (!labels.length) return;

        labels.forEach(function (label) {
            var radio = label.querySelector('input[type="radio"]');
            if (!radio) return;

            // Mark already-checked card active (server-side replay)
            if (radio.checked) label.classList.add('active');

            radio.addEventListener('change', function () {
                labels.forEach(function (l) { l.classList.remove('active'); });
                if (this.checked) this.closest('.hd-priority-card').classList.add('active');
            });
        });
    }

    /* ──────────────────────────────────────────────────────────────
       DRAG-AND-DROP FILE ZONE
    ────────────────────────────────────────────────────────────── */
    function initDropzone() {
        var zone    = document.getElementById('hd-dropzone');
        var input   = document.getElementById('attachment');
        var preview = document.getElementById('hd-file-preview');
        if (!zone || !input || !preview) return;

        // Click anywhere on zone (except the remove button) triggers picker
        zone.addEventListener('click', function (e) {
            if (e.target.closest('.hd-file-remove')) return;
            input.click();
        });

        input.addEventListener('change', function () {
            if (this.files && this.files[0]) showPreview(this.files[0]);
        });

        zone.addEventListener('dragover', function (e) {
            e.preventDefault();
            this.classList.add('dragover');
        });

        zone.addEventListener('dragleave', function (e) {
            if (!zone.contains(e.relatedTarget)) {
                this.classList.remove('dragover');
            }
        });

        zone.addEventListener('drop', function (e) {
            e.preventDefault();
            this.classList.remove('dragover');
            var file = e.dataTransfer.files[0];
            if (!file) return;
            try {
                var dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
            } catch (_) { /* Safari fallback – just show preview, server re-validates */ }
            showPreview(file);
        });

        function showPreview(file) {
            var kb   = file.size / 1024;
            var size = kb >= 1024
                ? (kb / 1024).toFixed(1) + ' MB'
                : kb.toFixed(1) + ' KB';

            preview.innerHTML =
                '<div class="hd-file-item">' +
                  '<i class="fa ' + fileIcon(file.name) + ' hd-file-icon"></i>' +
                  '<div class="hd-file-info">' +
                    '<span class="hd-file-name">' + escHtml(file.name) + '</span>' +
                    '<span class="hd-file-size">' + size + '</span>' +
                  '</div>' +
                  '<button type="button" class="hd-file-remove" aria-label="Remove file">' +
                    '<i class="fa fa-times"></i>' +
                  '</button>' +
                '</div>';

            zone.classList.add('has-file');

            preview.querySelector('.hd-file-remove').addEventListener('click', function (e) {
                e.stopPropagation();
                input.value = '';
                preview.innerHTML = '';
                zone.classList.remove('has-file');
            });
        }

        function fileIcon(name) {
            var ext = (name.split('.').pop() || '').toLowerCase();
            var map = {
                pdf: 'fa-file-pdf-o',
                doc: 'fa-file-word-o', docx: 'fa-file-word-o',
                xls: 'fa-file-excel-o', xlsx: 'fa-file-excel-o',
                jpg: 'fa-file-image-o', jpeg: 'fa-file-image-o',
                png: 'fa-file-image-o', gif: 'fa-file-image-o', webp: 'fa-file-image-o',
                txt: 'fa-file-text-o',
            };
            return map[ext] || 'fa-file-o';
        }
    }

    /* ──────────────────────────────────────────────────────────────
       CHARACTER COUNTER
    ────────────────────────────────────────────────────────────── */
    function initCharCounter() {
        var textarea = document.getElementById('description');
        var counter  = document.getElementById('hd-char-counter');
        var MAX      = 2000;
        if (!textarea || !counter) return;

        function update() {
            var len = textarea.value.length;
            counter.textContent = len + ' / ' + MAX;
            counter.classList.toggle('warn', len > MAX * 0.80 && len <= MAX);
            counter.classList.toggle('over', len > MAX);
        }

        textarea.addEventListener('input', update);
        update();
    }

    /* ──────────────────────────────────────────────────────────────
       SUBMIT BUTTON — loading state + type validation
    ────────────────────────────────────────────────────────────── */
    function initSubmitButton() {
        var form   = document.getElementById('hd-portal-form');
        var btn    = document.getElementById('hd-submit-btn');
        var hidden = document.getElementById('request_type_hidden');
        var errBox = document.getElementById('hd-type-error');
        if (!form || !btn) return;

        form.addEventListener('submit', function (e) {
            // Validate type card selection (not covered by HTML5 required on hidden input)
            if (!hidden || !hidden.value) {
                e.preventDefault();
                if (errBox) {
                    errBox.style.display = 'flex';
                    errBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                return;
            }

            // Show loading state
            btn.disabled = true;
            btn.innerHTML =
                '<span class="spinner-border" role="status" aria-hidden="true"></span>' +
                '<span> Submitting…</span>';
        });
    }

    /* ──────────────────────────────────────────────────────────────
       UTIL
    ────────────────────────────────────────────────────────────── */
    function escHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

})();
