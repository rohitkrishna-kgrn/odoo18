/* ============================================================
   AML Portal – Multi-Page KYC Form Controller
   ============================================================ */

'use strict';

/* ---- Signature Pad (embedded minimal implementation) ---- */
class SignaturePad {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.drawing = false;
        this.isEmpty = true;
        this._setupEvents();
    }
    _pos(e) {
        const r = this.canvas.getBoundingClientRect();
        const src = e.touches ? e.touches[0] : e;
        return { x: src.clientX - r.left, y: src.clientY - r.top };
    }
    _setupEvents() {
        const c = this.canvas;
        c.addEventListener('mousedown',  e => { this.drawing = true; const p = this._pos(e); this.ctx.beginPath(); this.ctx.moveTo(p.x, p.y); });
        c.addEventListener('mousemove',  e => { if (!this.drawing) return; const p = this._pos(e); this.ctx.lineWidth = 2; this.ctx.lineCap = 'round'; this.ctx.strokeStyle = '#1a237e'; this.ctx.lineTo(p.x, p.y); this.ctx.stroke(); this.isEmpty = false; });
        c.addEventListener('mouseup',    () => { this.drawing = false; });
        c.addEventListener('mouseleave', () => { this.drawing = false; });
        c.addEventListener('touchstart', e => { e.preventDefault(); this.drawing = true; const p = this._pos(e); this.ctx.beginPath(); this.ctx.moveTo(p.x, p.y); });
        c.addEventListener('touchmove',  e => { e.preventDefault(); if (!this.drawing) return; const p = this._pos(e); this.ctx.lineWidth = 2; this.ctx.lineCap = 'round'; this.ctx.strokeStyle = '#1a237e'; this.ctx.lineTo(p.x, p.y); this.ctx.stroke(); this.isEmpty = false; });
        c.addEventListener('touchend',   () => { this.drawing = false; });
    }
    clear() { this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height); this.isEmpty = true; }
    toDataURL() { return this.canvas.toDataURL('image/png'); }
}

/* ============================================================
   Main Form Controller
   ============================================================ */
const amlForm = (function () {

    let currentPage = 0;
    const TOTAL_PAGES = 7;
    let signaturePad = null;
    let kyc_type = 'entity';
    let accessToken = '';
    let formData = {};   // accumulated field data per page
    let directorRows = [];
    let shareholderRows = [];
    let docLines = [];

    // Page mapping index → element ID
    const PAGE_IDS = ['page-0', null /*dynamic kyc*/, 'page-2', 'page-3', 'page-4', 'page-5', 'page-6'];

    function init() {
        accessToken = (document.getElementById('aml-access-token') || {}).value || '';
        kyc_type = (document.getElementById('aml-kyc-type') || {}).value || 'entity';

        // Load server-side JSON data
        try {
            directorRows = JSON.parse(document.getElementById('aml-directors-data').textContent || '[]');
        } catch(e) { directorRows = []; }
        try {
            shareholderRows = JSON.parse(document.getElementById('aml-shareholders-data').textContent || '[]');
        } catch(e) { shareholderRows = []; }
        try {
            docLines = JSON.parse(document.getElementById('aml-doc-lines-data').textContent || '[]');
        } catch(e) { docLines = []; }

        // Render pre-loaded rows
        if (directorRows.length) directorRows.forEach(d => addDirectorRow(d));
        if (shareholderRows.length) shareholderRows.forEach(s => addShareholderRow(s));

        // Render document upload list
        renderDocList();

        // Init signature pad (fixed 600×150 — do NOT resize, keeps coordinates accurate)
        const canvas = document.getElementById('aml-signature-canvas');
        if (canvas) {
            signaturePad = new SignaturePad(canvas);
        }

        // Show first page
        showPage(0);
    }

    // ---- Page Navigation ----
    function getPageId(idx) {
        if (idx === 1) return kyc_type === 'entity' ? 'page-1-entity' : 'page-1-individual';
        return PAGE_IDS[idx];
    }

    function showPage(idx) {
        // Hide all pages
        document.querySelectorAll('.aml-page').forEach(p => p.classList.remove('active'));
        // Show current
        const pageEl = document.getElementById(getPageId(idx));
        if (pageEl) { pageEl.classList.add('active'); pageEl.scrollIntoView({ behavior: 'smooth', block: 'start' }); }

        // Update sidebar
        document.querySelectorAll('.aml-step').forEach((el, i) => {
            el.classList.remove('active', 'done');
            if (i < idx) el.classList.add('done');
            else if (i === idx) el.classList.add('active');
        });

        // Progress bar
        const pct = (idx / (TOTAL_PAGES - 1)) * 100;
        const bar = document.getElementById('aml-progress-bar');
        if (bar) bar.style.width = pct + '%';

        // If review page – build review
        if (idx === TOTAL_PAGES - 1) buildReview();

        currentPage = idx;
    }

    function validateCurrentPage() {
        const pageEl = document.getElementById(getPageId(currentPage));
        if (!pageEl) return true;
        let valid = true;
        // Clear previous validation state
        pageEl.querySelectorAll('.invalid').forEach(el => el.classList.remove('invalid'));

        // Check required inputs
        pageEl.querySelectorAll('[required]').forEach(el => {
            if (el.type === 'radio') {
                // Check if any radio with same name is checked
                const name = el.name;
                const anyChecked = pageEl.querySelector(`input[name="${name}"]:checked`);
                if (!anyChecked) {
                    // Mark all radios in group
                    pageEl.querySelectorAll(`input[name="${name}"]`).forEach(r => r.parentElement.style.outline = '2px solid #c62828');
                    valid = false;
                }
            } else if (el.tagName === 'SELECT') {
                if (!el.value) { el.classList.add('invalid'); valid = false; }
            } else {
                if (!el.value.trim()) { el.classList.add('invalid'); valid = false; }
            }
        });

        if (!valid) {
            const firstInvalid = pageEl.querySelector('.invalid, input[style*="outline"]');
            if (firstInvalid) firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
            showToast('Please fill in all required fields.', 'error');
        }
        return valid;
    }

    async function nextPage() {
        if (!validateCurrentPage()) return;
        await saveCurrentPage();
        if (currentPage < TOTAL_PAGES - 1) showPage(currentPage + 1);
    }

    function prevPage() {
        if (currentPage > 0) showPage(currentPage - 1);
    }

    // ---- Collect form data from current page ----
    function collectPageData(pageIdx) {
        const pageEl = document.getElementById(getPageId(pageIdx));
        if (!pageEl) return {};
        const data = {};
        pageEl.querySelectorAll('input[name], textarea[name], select[name]').forEach(el => {
            const name = el.name;
            if (!name || name.includes('[]')) return;
            if (el.type === 'radio') {
                if (el.checked) data[name] = el.value;
            } else if (el.type === 'checkbox') {
                if (el.checked) data[name] = true;
                else if (!(name in data)) data[name] = false;
            } else {
                data[name] = el.value;
            }
        });
        return data;
    }

    async function saveCurrentPage() {
        if (currentPage === 3) return await saveDirectors();
        if (currentPage === 4) return await saveShareholders();
        if (currentPage === 5) return;  // documents saved on upload
        if (currentPage === 6) return;  // submit handles this

        let page_key = '';
        if (currentPage === 0) page_key = 'instructions';  // nothing to save
        else if (currentPage === 1) page_key = kyc_type === 'entity' ? 'kyc_entity' : 'kyc_individual';
        else if (currentPage === 2) page_key = 'ubo';

        if (!page_key || page_key === 'instructions') return;

        const data = collectPageData(currentPage);
        Object.assign(formData, data);

        try {
            await jsonRpc('/aml/form/save_page', {
                access_token: accessToken,
                page: page_key,
                data: data,
            });
        } catch (e) {
            console.error('Save error:', e);
        }
    }

    // ---- Directors Table ----
    function addDirectorRow(prefill = null) {
        const tbody = document.getElementById('directors-tbody');
        if (!tbody) return;
        const idx = tbody.rows.length + 1;
        const d = prefill || {};
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${idx}</td>
            <td><input type="text" name="dir_full_name" placeholder="Full Name" required value="${esc(d.full_name||'')}"/></td>
            <td><input type="text" name="dir_position" placeholder="Director / Manager" value="${esc(d.position||'')}"/></td>
            <td><input type="text" name="dir_nationality" placeholder="Nationality" value="${esc(d.nationality||'')}"/></td>
            <td><input type="text" name="dir_id_passport" placeholder="ID / Passport" value="${esc(d.id_passport_no||'')}"/></td>
            <td><input type="date" name="dir_appointment_date" value="${esc(d.appointment_date||'')}"/></td>
            <td><input type="date" name="dir_resignation_date" value="${esc(d.resignation_date||'')}"/></td>
            <td>
                <select name="dir_status">
                    <option value="active" ${(d.status||'active')==='active'?'selected':''}>Active</option>
                    <option value="resigned" ${d.status==='resigned'?'selected':''}>Resigned</option>
                </select>
            </td>
            <td><button type="button" class="del-row-btn" onclick="this.closest('tr').remove(); renumberRows('directors-tbody');">✕</button></td>
        `;
        tbody.appendChild(tr);
    }

    async function saveDirectors() {
        const tbody = document.getElementById('directors-tbody');
        const rows = [];
        if (tbody) {
            tbody.querySelectorAll('tr').forEach(tr => {
                rows.push({
                    full_name: val(tr, 'dir_full_name'),
                    position: val(tr, 'dir_position'),
                    nationality: val(tr, 'dir_nationality'),
                    id_passport_no: val(tr, 'dir_id_passport'),
                    appointment_date: val(tr, 'dir_appointment_date') || false,
                    resignation_date: val(tr, 'dir_resignation_date') || false,
                    status: val(tr, 'dir_status') || 'active',
                });
            });
        }
        const declDate = document.getElementById('director_declaration_date');
        try {
            await jsonRpc('/aml/form/save_directors', {
                access_token: accessToken,
                directors: rows,
                declaration_date: declDate ? declDate.value : false,
            });
        } catch (e) { console.error(e); }
    }

    // ---- Shareholders Table ----
    function addShareholderRow(prefill = null) {
        const tbody = document.getElementById('shareholders-tbody');
        if (!tbody) return;
        const idx = tbody.rows.length + 1;
        const s = prefill || {};
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${idx}</td>
            <td><input type="text" name="sh_name" placeholder="Shareholder Name" required value="${esc(s.shareholder_name||'')}"/></td>
            <td><input type="text" name="sh_nationality" placeholder="Nationality" value="${esc(s.nationality||'')}"/></td>
            <td>
                <select name="sh_type">
                    <option value="">– Select –</option>
                    <option value="individual" ${s.shareholder_type==='individual'?'selected':''}>Individual</option>
                    <option value="corporate" ${s.shareholder_type==='corporate'?'selected':''}>Corporate</option>
                </select>
            </td>
            <td><input type="text" name="sh_passport" placeholder="Passport No." value="${esc(s.passport_no||'')}"/></td>
            <td>
                <select name="sh_share_class">
                    <option value="">– –</option>
                    <option value="ordinary" ${s.share_class==='ordinary'?'selected':''}>Ordinary</option>
                    <option value="preference" ${s.share_class==='preference'?'selected':''}>Preference</option>
                </select>
            </td>
            <td><input type="number" name="sh_num_shares" min="0" value="${s.num_shares||0}" style="width:80px"/></td>
            <td><input type="number" name="sh_pct" min="0" max="100" step="0.01" value="${s.percentage_holding||0}" style="width:70px"/></td>
            <td><input type="date" name="sh_date_entry" value="${esc(s.date_of_entry||'')}"/></td>
            <td><button type="button" class="del-row-btn" onclick="this.closest('tr').remove(); renumberRows('shareholders-tbody');">✕</button></td>
        `;
        tbody.appendChild(tr);
    }

    async function saveShareholders() {
        const tbody = document.getElementById('shareholders-tbody');
        const rows = [];
        if (tbody) {
            tbody.querySelectorAll('tr').forEach(tr => {
                rows.push({
                    shareholder_name: val(tr, 'sh_name'),
                    nationality: val(tr, 'sh_nationality'),
                    shareholder_type: val(tr, 'sh_type') || false,
                    passport_no: val(tr, 'sh_passport'),
                    share_class: val(tr, 'sh_share_class') || false,
                    num_shares: parseInt(val(tr, 'sh_num_shares') || 0),
                    percentage_holding: parseFloat(val(tr, 'sh_pct') || 0),
                    date_of_entry: val(tr, 'sh_date_entry') || false,
                });
            });
        }
        const declDate = document.getElementById('shareholder_declaration_date');
        try {
            await jsonRpc('/aml/form/save_shareholders', {
                access_token: accessToken,
                shareholders: rows,
                declaration_date: declDate ? declDate.value : false,
            });
        } catch (e) { console.error(e); }
    }

    // ---- Document Upload ----
    function renderDocList() {
        const container = document.getElementById('aml-doc-upload-list');
        if (!container) return;
        container.innerHTML = '';

        const BADGE = {
            true: '<span class="aml-doc-badge mandatory">Mandatory</span>',
            false: '<span class="aml-doc-badge optional">If Applicable</span>',
            'any': '<span class="aml-doc-badge any-one">Any One</span>',
        };
        const ANY_ONE_KEYS = ['cert_incumbency'];

        docLines.forEach((doc, i) => {
            const badgeType = ANY_ONE_KEYS.includes(doc.doc_key) ? 'any' : String(doc.is_mandatory);
            const div = document.createElement('div');
            div.className = 'aml-doc-item' + (doc.has_attachment ? ' uploaded' : '');
            div.id = 'doc-item-' + doc.id;

            const uploadedNamesHtml = doc.attachment_names && doc.attachment_names.length
                ? `<div class="aml-doc-uploaded-names">✔ ${doc.attachment_names.join(', ')}</div>`
                : '';

            div.innerHTML = `
                <div class="aml-doc-num">${i + 1}</div>
                <div class="aml-doc-info">
                    <span class="aml-doc-name" title="${esc(doc.tooltip || doc.doc_name)}">${esc(doc.doc_name)}</span>
                    ${BADGE[badgeType]}
                    <div id="doc-names-${doc.id}">${uploadedNamesHtml}</div>
                </div>
                <div class="aml-doc-upload-btn">
                    <label>
                        📎 Upload
                        <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
                            onchange="amlForm.handleDocUpload(this, ${doc.id})"/>
                    </label>
                    <span class="aml-upload-status" id="doc-status-${doc.id}">
                        ${doc.has_attachment ? '✔ Uploaded' : ''}
                    </span>
                </div>
            `;
            container.appendChild(div);
        });
    }

    async function handleDocUpload(input, docId) {
        if (!input.files.length) return;
        const statusEl = document.getElementById('doc-status-' + docId);
        const itemEl = document.getElementById('doc-item-' + docId);
        const namesEl = document.getElementById('doc-names-' + docId);
        if (statusEl) statusEl.textContent = 'Uploading...';

        const uploadedNames = [];
        for (const file of Array.from(input.files)) {
            const fd = new FormData();
            fd.append('access_token', accessToken);
            fd.append('doc_id', String(docId));
            fd.append('file', file);
            try {
                const resp = await fetch('/aml/form/upload_doc', { method: 'POST', body: fd });
                const result = await resp.json();
                if (result.success) {
                    uploadedNames.push(result.filename);
                } else {
                    showToast('Upload failed: ' + (result.error || 'Unknown error'), 'error');
                }
            } catch (e) {
                showToast('Upload error: ' + e.message, 'error');
            }
        }
        if (uploadedNames.length) {
            if (statusEl) statusEl.textContent = '✔ Uploaded';
            if (itemEl) itemEl.classList.add('uploaded');
            if (namesEl) namesEl.innerHTML += `<div class="aml-doc-uploaded-names">✔ ${uploadedNames.join(', ')}</div>`;
        }
    }

    // ---- Review Page ----
    function buildReview() {
        const container = document.getElementById('aml-review-content');
        if (!container) return;
        const sections = [];

        if (kyc_type === 'entity') {
            sections.push({
                title: 'KYC – Entity',
                fields: {
                    'Name of Entity': formData['ent_entity_name'],
                    'Legal Type': formData['ent_legal_type'],
                    'Trading Name': formData['ent_trading_name'],
                    'Date of Incorporation': formData['ent_date_of_incorporation'],
                    'Registration Number': formData['ent_license_number'],
                    'License Expiry': formData['ent_license_expiry'],
                    'Registered Address': formData['ent_registered_address'],
                    'Business Address': formData['ent_business_address'],
                    'Industry Type': formData['ent_industry_type'],
                    'Nature of Business': formData['ent_nature_of_business'],
                    'Contact Person': formData['ent_contact_name'],
                    'Contact Email': formData['ent_contact_email'],
                    'Contact Mobile': formData['ent_contact_mobile'],
                },
            });
        } else {
            sections.push({
                title: 'KYC – Individual',
                fields: {
                    'Full Name': formData['ind_full_name'],
                    'Gender': formData['ind_gender'],
                    'Nationality': formData['ind_nationality'],
                    'Date of Birth': formData['ind_date_of_birth'],
                    'ID Type': formData['ind_id_type'],
                    'ID Number': formData['ind_id_number'],
                    'Email': formData['ind_email'],
                    'Mobile': formData['ind_mobile'],
                },
            });
        }

        sections.push({
            title: 'UBO',
            fields: {
                'Full Name': formData['ubo_full_name'],
                'Nationality': formData['ubo_nationality'],
                'Date of Birth': formData['ubo_date_of_birth'],
                'Source of Income': formData['ubo_source_of_income'],
                'Bank': formData['ubo_bank_name'],
                'IBAN': formData['ubo_iban'],
            },
        });

        let html = '';
        sections.forEach(sec => {
            const rows = Object.entries(sec.fields)
                .filter(([, v]) => v)
                .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(String(v))}</td></tr>`)
                .join('');
            if (rows) {
                html += `<div class="aml-review-section"><h4>${esc(sec.title)}</h4>
                          <table class="aml-review-table">${rows}</table></div>`;
            }
        });

        // Director count
        const dTbody = document.getElementById('directors-tbody');
        const dCount = dTbody ? dTbody.rows.length : 0;
        if (dCount) html += `<div class="aml-review-section"><h4>Directors / Managers</h4><p>${dCount} record(s) entered.</p></div>`;

        // Shareholder count
        const sTbody = document.getElementById('shareholders-tbody');
        const sCount = sTbody ? sTbody.rows.length : 0;
        if (sCount) html += `<div class="aml-review-section"><h4>Shareholders</h4><p>${sCount} record(s) entered.</p></div>`;

        // Documents
        const uploaded = docLines.filter(d => document.getElementById('doc-item-' + d.id) &&
            document.getElementById('doc-item-' + d.id).classList.contains('uploaded'));
        html += `<div class="aml-review-section"><h4>Documents</h4><p>${uploaded.length} of ${docLines.length} document slot(s) uploaded.</p></div>`;

        container.innerHTML = html || '<p class="text-muted">No data to review.</p>';
    }

    // ---- Signature ----
    function clearSignature() {
        if (signaturePad) signaturePad.clear();
        const preview = document.getElementById('sig-upload-preview');
        if (preview) preview.innerHTML = '';
    }

    function switchSigTab(tab) {
        const drawPanel = document.getElementById('sig-draw-panel');
        const uploadPanel = document.getElementById('sig-upload-panel');
        const tabDraw = document.getElementById('sig-tab-draw');
        const tabUpload = document.getElementById('sig-tab-upload');
        if (tab === 'draw') {
            if (drawPanel) drawPanel.style.display = '';
            if (uploadPanel) uploadPanel.style.display = 'none';
            if (tabDraw) tabDraw.classList.add('active');
            if (tabUpload) tabUpload.classList.remove('active');
        } else {
            if (drawPanel) drawPanel.style.display = 'none';
            if (uploadPanel) uploadPanel.style.display = '';
            if (tabDraw) tabDraw.classList.remove('active');
            if (tabUpload) tabUpload.classList.add('active');
        }
    }

    function uploadSignatureImage(input) {
        if (!input.files || !input.files[0]) return;
        const file = input.files[0];
        const reader = new FileReader();
        reader.onload = function(e) {
            // Show preview
            const preview = document.getElementById('sig-upload-preview');
            if (preview) preview.innerHTML = '<img src="' + e.target.result + '" alt="Signature Preview"/>';
            // Draw onto canvas (so toDataURL works for submission)
            const canvas = document.getElementById('aml-signature-canvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const img = new Image();
            img.onload = function() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                const scale = Math.min(canvas.width / img.width, canvas.height / img.height);
                const w = img.width * scale;
                const h = img.height * scale;
                const x = (canvas.width - w) / 2;
                const y = (canvas.height - h) / 2;
                ctx.drawImage(img, x, y, w, h);
                if (signaturePad) signaturePad.isEmpty = false;
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    }

    // ---- Final Submit ----
    async function submitForm() {
        // Validate review page
        const acceptBox = document.getElementById('accept_declaration');
        if (!acceptBox || !acceptBox.checked) {
            showToast('Please read and accept the declaration.', 'error');
            return;
        }
        const signatoryName = (document.getElementById('signatory_name') || {}).value || '';
        if (!signatoryName.trim()) {
            showToast('Please enter the signatory name.', 'error');
            return;
        }
        if (!signaturePad || signaturePad.isEmpty) {
            showToast('Please draw your signature.', 'error');
            return;
        }

        const overlay = document.getElementById('aml-loading-overlay');
        if (overlay) overlay.style.display = 'flex';

        const sigData = signaturePad.toDataURL();
        try {
            const result = await jsonRpc('/aml/form/submit', {
                access_token: accessToken,
                signatory_name: signatoryName,
                signature_data: sigData,
            });
            if (result && result.success) {
                window.location.href = '/aml/form/confirmed/' + encodeURIComponent(result.aml_id || '');
            } else {
                if (overlay) overlay.style.display = 'none';
                showToast('Submission failed: ' + (result.error || 'Unknown error'), 'error');
            }
        } catch (e) {
            if (overlay) overlay.style.display = 'none';
            showToast('Error: ' + e.message, 'error');
        }
    }

    // ---- ID / Proof Type toggles ----
    function toggleIdOther(val) {
        const wrap = document.getElementById('ind-id-other-wrap');
        const input = document.getElementById('ind_id_type_other');
        if (!wrap) return;
        const show = val === 'other';
        wrap.style.display = show ? '' : 'none';
        if (input) input.required = show;
    }

    function toggleProofOther(val) {
        const wrap = document.getElementById('ind-proof-other-wrap');
        const input = document.getElementById('ind_proof_address_other');
        if (!wrap) return;
        const show = val === 'other';
        wrap.style.display = show ? '' : 'none';
        if (input) input.required = show;
    }

    function toggleEl(id, show) {
        const el = document.getElementById(id);
        if (el) el.style.display = show ? '' : 'none';
    }

    // ---- Helpers ----
    function esc(str) {
        return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function val(tr, name) {
        const el = tr.querySelector('[name="' + name + '"]');
        return el ? el.value : '';
    }

    function renumberRows(tbodyId) {
        const tbody = document.getElementById(tbodyId);
        if (!tbody) return;
        tbody.querySelectorAll('tr').forEach((tr, i) => {
            const firstTd = tr.querySelector('td:first-child');
            if (firstTd && !firstTd.querySelector('input')) firstTd.textContent = i + 1;
        });
    }

    function showToast(msg, type = 'info') {
        let toast = document.getElementById('aml-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'aml-toast';
            toast.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;padding:14px 22px;border-radius:8px;font-size:14px;font-weight:600;max-width:360px;box-shadow:0 4px 18px rgba(0,0,0,.18);transition:opacity .3s;';
            document.body.appendChild(toast);
        }
        toast.style.background = type === 'error' ? '#c62828' : '#1565c0';
        toast.style.color = '#fff';
        toast.textContent = msg;
        toast.style.opacity = '1';
        clearTimeout(toast._t);
        toast._t = setTimeout(() => { toast.style.opacity = '0'; }, 4000);
    }

    async function jsonRpc(route, params) {
        const resp = await fetch(route, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: params }),
        });
        const json = await resp.json();
        if (json.error) throw new Error(JSON.stringify(json.error));
        return json.result;
    }

    // Public API
    return { init, nextPage, prevPage, addDirectorRow, addShareholderRow, handleDocUpload, clearSignature, switchSigTab, uploadSignatureImage, submitForm, toggleIdOther, toggleProofOther, toggleEl };

})();

// ============================================================
// Additional Info Form Controller
// ============================================================
const amlAdditional = (function () {

    let additionalToken = '';
    let hitDocs = [];

    function init() {
        additionalToken = (document.getElementById('additional-token') || {}).value || '';
        try {
            hitDocs = JSON.parse(document.getElementById('aml-hit-docs-data').textContent || '[]');
        } catch(e) { hitDocs = []; }
        renderHitDocList();
    }

    function renderHitDocList() {
        const container = document.getElementById('additional-doc-upload-list');
        if (!container) return;
        container.innerHTML = '';
        hitDocs.forEach((doc, i) => {
            const div = document.createElement('div');
            div.className = 'aml-doc-item' + (doc.submitted ? ' uploaded' : '');
            div.id = 'hit-doc-item-' + doc.id;
            div.innerHTML = `
                <div class="aml-doc-num">${i + 1}</div>
                <div class="aml-doc-info">
                    <span class="aml-doc-name">${esc(doc.document_name)}</span>
                    <span class="aml-doc-badge mandatory">Required</span>
                    <div id="hit-doc-names-${doc.id}">
                        ${doc.submitted ? '<div class="aml-doc-uploaded-names">✔ Previously uploaded</div>' : ''}
                    </div>
                </div>
                <div class="aml-doc-upload-btn">
                    <label>
                        📎 Upload
                        <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
                            onchange="amlAdditional.handleUpload(this, ${doc.id})"/>
                    </label>
                    <span class="aml-upload-status" id="hit-doc-status-${doc.id}">
                        ${doc.submitted ? '✔ Uploaded' : ''}
                    </span>
                </div>
            `;
            container.appendChild(div);
        });
    }

    async function handleUpload(input, hitDocId) {
        if (!input.files.length) return;
        const statusEl = document.getElementById('hit-doc-status-' + hitDocId);
        const itemEl = document.getElementById('hit-doc-item-' + hitDocId);
        const namesEl = document.getElementById('hit-doc-names-' + hitDocId);
        if (statusEl) statusEl.textContent = 'Uploading...';

        const uploadedNames = [];
        for (const file of Array.from(input.files)) {
            const fd = new FormData();
            fd.append('additional_token', additionalToken);
            fd.append('hit_doc_id', String(hitDocId));
            fd.append('file', file);
            try {
                const resp = await fetch('/aml/additional/upload', { method: 'POST', body: fd });
                const result = await resp.json();
                if (result.success) uploadedNames.push(result.filename);
                else showToast('Upload failed: ' + (result.error || ''), 'error');
            } catch (e) {
                showToast('Upload error: ' + e.message, 'error');
            }
        }
        if (uploadedNames.length) {
            if (statusEl) statusEl.textContent = '✔ Uploaded';
            if (itemEl) itemEl.classList.add('uploaded');
            if (namesEl) namesEl.innerHTML += `<div class="aml-doc-uploaded-names">✔ ${uploadedNames.join(', ')}</div>`;
        }
    }

    async function submit() {
        const notes = (document.getElementById('additional-notes') || {}).value || '';
        const overlay = document.getElementById('aml-loading-overlay');
        if (overlay) overlay.style.display = 'flex';
        try {
            const result = await jsonRpc('/aml/additional/submit', {
                additional_token: additionalToken,
                notes: notes,
            });
            if (result && result.success) {
                document.body.innerHTML = `
                    <div class="aml-confirm-page">
                        <div class="aml-confirm-card">
                            <div class="aml-confirm-icon">✔</div>
                            <h2>Additional Documents Submitted</h2>
                            <p>Thank you. Our AML team will review the submitted documents and contact you if needed.</p>
                        </div>
                    </div>
                `;
            } else {
                if (overlay) overlay.style.display = 'none';
                showToast('Submission failed: ' + (result.error || ''), 'error');
            }
        } catch (e) {
            if (overlay) overlay.style.display = 'none';
            showToast('Error: ' + e.message, 'error');
        }
    }

    function esc(str) {
        return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function showToast(msg, type = 'info') {
        alert((type === 'error' ? 'Error: ' : '') + msg);
    }

    async function jsonRpc(route, params) {
        const resp = await fetch(route, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: params }),
        });
        const json = await resp.json();
        if (json.error) throw new Error(JSON.stringify(json.error));
        return json.result;
    }

    return { init, handleUpload, submit };

})();

// ============================================================
// Auto-initialize on DOM ready
// ============================================================
document.addEventListener('DOMContentLoaded', function () {
    if (document.getElementById('aml-form-wrapper')) {
        if (document.getElementById('aml-access-token')) {
            amlForm.init();
        } else if (document.getElementById('additional-token')) {
            amlAdditional.init();
        }
    }
});

// Expose to inline event handlers
window.amlForm = amlForm;
window.amlAdditional = amlAdditional;
window.renumberRows = function(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    tbody.querySelectorAll('tr').forEach((tr, i) => {
        const firstTd = tr.querySelector('td:first-child');
        if (firstTd && !firstTd.querySelector('input') && !firstTd.querySelector('select')) {
            firstTd.textContent = i + 1;
        }
    });
};
