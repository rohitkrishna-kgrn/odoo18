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

/* ---- Countries List ---- */
const COUNTRIES = [
    'Afghanistan','Albania','Algeria','Andorra','Angola','Antigua and Barbuda','Argentina',
    'Armenia','Australia','Austria','Azerbaijan','Bahamas','Bahrain','Bangladesh','Barbados',
    'Belarus','Belgium','Belize','Benin','Bhutan','Bolivia','Bosnia and Herzegovina',
    'Botswana','Brazil','Brunei','Bulgaria','Burkina Faso','Burundi','Cabo Verde','Cambodia',
    'Cameroon','Canada','Central African Republic','Chad','Chile','China','Colombia','Comoros',
    'Congo (Republic)','Congo (Democratic Republic)','Costa Rica',"Côte d'Ivoire",'Croatia',
    'Cuba','Cyprus','Czech Republic','Denmark','Djibouti','Dominica','Dominican Republic',
    'Ecuador','Egypt','El Salvador','Equatorial Guinea','Eritrea','Estonia','Eswatini',
    'Ethiopia','Fiji','Finland','France','Gabon','Gambia','Georgia','Germany','Ghana',
    'Greece','Grenada','Guatemala','Guinea','Guinea-Bissau','Guyana','Haiti','Honduras',
    'Hungary','Iceland','India','Indonesia','Iran','Iraq','Ireland','Israel','Italy',
    'Jamaica','Japan','Jordan','Kazakhstan','Kenya','Kiribati','Kuwait','Kyrgyzstan','Laos',
    'Latvia','Lebanon','Lesotho','Liberia','Libya','Liechtenstein','Lithuania','Luxembourg',
    'Madagascar','Malawi','Malaysia','Maldives','Mali','Malta','Marshall Islands',
    'Mauritania','Mauritius','Mexico','Micronesia','Moldova','Monaco','Mongolia','Montenegro',
    'Morocco','Mozambique','Myanmar','Namibia','Nauru','Nepal','Netherlands','New Zealand',
    'Nicaragua','Niger','Nigeria','North Korea','North Macedonia','Norway','Oman','Pakistan',
    'Palau','Panama','Papua New Guinea','Paraguay','Peru','Philippines','Poland','Portugal',
    'Qatar','Romania','Russia','Rwanda','Saint Kitts and Nevis','Saint Lucia',
    'Saint Vincent and the Grenadines','Samoa','San Marino','Sao Tome and Principe',
    'Saudi Arabia','Senegal','Serbia','Seychelles','Sierra Leone','Singapore','Slovakia',
    'Slovenia','Solomon Islands','Somalia','South Africa','South Korea','South Sudan',
    'Spain','Sri Lanka','Sudan','Suriname','Sweden','Switzerland','Syria','Taiwan',
    'Tajikistan','Tanzania','Thailand','Timor-Leste','Togo','Tonga','Trinidad and Tobago',
    'Tunisia','Turkey','Turkmenistan','Tuvalu','Uganda','Ukraine','United Arab Emirates',
    'United Kingdom','United States','Uruguay','Uzbekistan','Vanuatu','Vatican City',
    'Venezuela','Vietnam','Yemen','Zambia','Zimbabwe'
];

/* ============================================================
   Main Form Controller
   ============================================================ */
const amlForm = (function () {

    let currentPage = 0;
    let signaturePad = null;
    let kyc_type = 'entity';
    let accessToken = '';
    let formData = {};   // accumulated field data per page
    let directorRows = [];
    let shareholderRows = [];
    let docLines = [];
    let dirRowCounter = 0;
    let shRowCounter = 0;
    let supplierCountries = [];
    let customerCountries = [];

    // Page sequences per KYC type
    const ENTITY_PAGES    = ['page-0', 'page-1-entity',      'page-2', 'page-3', 'page-4', 'page-5', 'page-6'];
    const INDIVIDUAL_PAGES = ['page-0', 'page-1-individual',  'page-5', 'page-6'];

    function getPages()      { return kyc_type === 'entity' ? ENTITY_PAGES : INDIVIDUAL_PAGES; }
    function totalPages()    { return getPages().length; }

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

        // Hide entity-only sidebar steps for individual KYC and renumber visible steps
        if (kyc_type === 'individual') {
            document.querySelectorAll('.aml-step[data-entity-only]').forEach(el => {
                el.style.display = 'none';
            });
            let num = 1;
            document.querySelectorAll('.aml-step').forEach(el => {
                if (el.style.display === 'none') return;
                const numEl = el.querySelector('.step-num');
                if (numEl) numEl.textContent = num++;
            });
        }

        // Populate country pickers
        initCountryPickers();

        // Restore saved field values from server
        try {
            const savedData = JSON.parse(document.getElementById('aml-saved-fields').textContent || '{}');
            restoreFields(savedData);
            Object.assign(formData, savedData);
        } catch(e) {}

        // Restore last visited page from localStorage, else start at page 0
        const storageKey = 'aml_page_' + accessToken;
        const savedPage = parseInt(localStorage.getItem(storageKey) || '0', 10);
        showPage(isNaN(savedPage) ? 0 : Math.max(0, Math.min(savedPage, totalPages() - 1)));
    }

    // ---- Restore saved field values into form inputs ----
    function restoreFields(data) {
        if (!data || !Object.keys(data).length) return;
        Object.entries(data).forEach(([name, value]) => {
            if (value === null || value === undefined || value === false || value === '') return;
            // Checkboxes (by name)
            const cb = document.querySelector(`input[type="checkbox"][name="${name}"]`);
            if (cb) { cb.checked = Boolean(value); return; }
            // Radio buttons
            const radios = document.querySelectorAll(`input[type="radio"][name="${name}"]`);
            if (radios.length) {
                radios.forEach(r => { r.checked = r.value === String(value); });
                return;
            }
            // Text / textarea / date / select
            const el = document.querySelector(`input[name="${name}"], textarea[name="${name}"], select[name="${name}"]`);
            if (el) el.value = value;
        });
        // Country pickers (stored as "Country1, Country2, ...")
        if (data.ent_top5_suppliers) {
            supplierCountries = data.ent_top5_suppliers.split(', ').filter(Boolean);
            renderCountryTags('supplier');
            updateCountryHidden('supplier');
        }
        if (data.ent_top5_customers) {
            customerCountries = data.ent_top5_customers.split(', ').filter(Boolean);
            renderCountryTags('customer');
            updateCountryHidden('customer');
        }
        // Declaration date fields (use id, not name)
        if (data.director_declaration_date) {
            const el = document.getElementById('director_declaration_date');
            if (el) el.value = data.director_declaration_date;
        }
        if (data.shareholder_declaration_date) {
            const el = document.getElementById('shareholder_declaration_date');
            if (el) el.value = data.shareholder_declaration_date;
        }
        // Trigger conditional toggles
        const idTypeEl = document.querySelector('select[name="ind_id_type"]');
        if (idTypeEl && idTypeEl.value) toggleIdOther(idTypeEl.value);
        const proofTypeEl = document.querySelector('select[name="ind_proof_address_type"]');
        if (proofTypeEl && proofTypeEl.value) toggleProofOther(proofTypeEl.value);
        const purposeEl = document.querySelector('select[name="ind_purpose_of_relationship"]');
        if (purposeEl && purposeEl.value) togglePurposeOther(purposeEl.value);
        const indDualEl = document.querySelector('input[name="ind_dual_citizenship"]:checked');
        if (indDualEl) toggleIndDualCitizenship(indDualEl.value);
        const dualEl = document.querySelector('input[name="ubo_dual_citizenship"]:checked');
        if (dualEl) toggleEl('ubo-dual-detail', dualEl.value === 'yes');
    }

    // ---- Page Navigation ----
    function getPageId(idx) { return getPages()[idx] || null; }

    function showPage(idx) {
        // Hide all pages
        document.querySelectorAll('.aml-page').forEach(p => p.classList.remove('active'));
        // Show current
        const pageEl = document.getElementById(getPageId(idx));
        if (pageEl) { pageEl.classList.add('active'); pageEl.scrollIntoView({ behavior: 'smooth', block: 'start' }); }

        // Update sidebar — only count visible steps
        let visibleIdx = 0;
        document.querySelectorAll('.aml-step').forEach(el => {
            if (el.style.display === 'none') return;
            el.classList.remove('active', 'done');
            if (visibleIdx < idx) el.classList.add('done');
            else if (visibleIdx === idx) el.classList.add('active');
            visibleIdx++;
        });

        // Progress bar
        const pct = (idx / (totalPages() - 1)) * 100;
        const bar = document.getElementById('aml-progress-bar');
        if (bar) bar.style.width = pct + '%';

        // If review page – build review and pre-fill today's date
        if (getPageId(idx) === 'page-6') {
            buildReview();
            const signedOnEl = document.getElementById('signed_on');
            if (signedOnEl && !signedOnEl.value) {
                signedOnEl.value = new Date().toISOString().split('T')[0];
            }
        }

        // Persist current page so refresh resumes here
        if (accessToken) localStorage.setItem('aml_page_' + accessToken, idx);

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

        // Mandatory document upload check on page-5
        if (valid && getPageId(currentPage) === 'page-5') {
            const ANY_ONE_KEYS = ['cert_incumbency'];
            const missing = docLines.filter(doc => {
                if (!doc.is_mandatory) return false;
                if (ANY_ONE_KEYS.includes(doc.doc_key)) return false;
                const el = document.getElementById('doc-item-' + doc.id);
                return el && !el.classList.contains('uploaded');
            });
            if (missing.length > 0) {
                const names = missing.map(d => d.doc_name).join(', ');
                showToast('Please upload all mandatory documents before proceeding: ' + names, 'error');
                const firstMissing = document.getElementById('doc-item-' + missing[0].id);
                if (firstMissing) firstMissing.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return false;
            }
        }

        return valid;
    }

    async function nextPage() {
        if (!validateCurrentPage()) return;
        await saveCurrentPage();
        if (currentPage < totalPages() - 1) showPage(currentPage + 1);
    }

    async function savePage() {
        const pageEl = document.getElementById(getPageId(currentPage));
        const btn = pageEl ? pageEl.querySelector('.aml-btn-save') : null;
        if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
        try {
            await saveCurrentPage();
            showToast('Progress saved successfully.', 'info');
        } catch (e) {
            showToast('Save failed: ' + e.message, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '&#10003; Save Progress'; }
        }
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
        const pageId = getPageId(currentPage);
        if (pageId === 'page-3') return await saveDirectors();
        if (pageId === 'page-4') return await saveShareholders();
        if (pageId === 'page-5') return;  // documents saved on upload
        if (pageId === 'page-6') return;  // submit handles this

        let page_key = '';
        if (pageId === 'page-0')            page_key = 'instructions';
        else if (pageId === 'page-1-entity')      page_key = 'kyc_entity';
        else if (pageId === 'page-1-individual')  page_key = 'kyc_individual';
        else if (pageId === 'page-2')             page_key = 'ubo';

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
        dirRowCounter++;
        const rowId = 'dir-' + dirRowCounter;
        const idx = tbody.querySelectorAll('tr.dir-main-row').length + 1;
        const d = prefill || {};

        const tr = document.createElement('tr');
        tr.className = 'dir-main-row';
        tr.dataset.rowId = rowId;
        tr.innerHTML = `
            <td>${idx}</td>
            <td><input type="text" name="dir_full_name" placeholder="Full Name" required value="${esc(d.full_name||'')}"/></td>
            <td><input type="text" name="dir_position" placeholder="Director / Manager" required value="${esc(d.position||'')}"/></td>
            <td><input type="text" name="dir_nationality" placeholder="Nationality" required value="${esc(d.nationality||'')}"/></td>
            <td><input type="text" name="dir_id_passport" placeholder="ID / Passport" required value="${esc(d.id_passport_no||'')}"/></td>
            <td><input type="date" name="dir_appointment_date" required value="${esc(d.appointment_date||'')}"/></td>
            <td><input type="date" name="dir_resignation_date" value="${esc(d.resignation_date||'')}"/></td>
            <td>
                <select name="dir_status" required>
                    <option value="active" ${(d.status||'active')==='active'?'selected':''}>Active</option>
                    <option value="resigned" ${d.status==='resigned'?'selected':''}>Resigned</option>
                </select>
            </td>
            <td><button type="button" class="del-row-btn" onclick="amlForm.removeDirectorRow('${rowId}')">✕</button></td>
        `;
        tbody.appendChild(tr);

        // Document upload sub-row
        const dtLabels = { passport: 'Passport Copy', proof_of_residence: 'Proof of Residence', emirates_id: 'Emirates ID' };
        const docsHtml = ['passport', 'proof_of_residence', 'emirates_id'].map(dt => `
            <div style="display:flex;flex-direction:column;gap:4px;min-width:140px;">
                <span style="font-size:11px;color:#555;font-weight:600;">${dtLabels[dt]}</span>
                <label style="display:inline-flex;align-items:center;gap:6px;cursor:pointer;background:#e3f2fd;border:1px solid #90caf9;border-radius:4px;padding:4px 8px;font-size:11px;font-weight:500;color:#1565c0;">
                    &#128206; Upload
                    <input type="file" accept=".pdf,.jpg,.jpeg,.png,.doc,.docx" style="display:none;"
                        onchange="amlForm.uploadDirectorDoc(this,'${rowId}','${dt}')"/>
                </label>
                <span id="dir-doc-status-${rowId}-${dt}" style="font-size:11px;color:#2e7d32;"></span>
            </div>
        `).join('');
        const docsTr = document.createElement('tr');
        docsTr.className = 'dir-docs-row';
        docsTr.dataset.rowId = rowId;
        docsTr.innerHTML = `
            <td colspan="9" style="background:#f5f9ff;padding:8px 16px;border-top:none;">
                <div style="display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap;">
                    <span style="font-size:12px;font-weight:600;color:#555;padding-top:6px;white-space:nowrap;">Documents:</span>
                    ${docsHtml}
                </div>
            </td>
        `;
        tbody.appendChild(docsTr);
    }

    function removeDirectorRow(rowId) {
        const tbody = document.getElementById('directors-tbody');
        if (!tbody) return;
        tbody.querySelectorAll('[data-row-id="' + rowId + '"]').forEach(tr => tr.remove());
        window.renumberRows('directors-tbody');
    }

    async function saveDirectors() {
        const tbody = document.getElementById('directors-tbody');
        const rows = [];
        if (tbody) {
            tbody.querySelectorAll('tr.dir-main-row').forEach(tr => {
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

    async function uploadDirectorDoc(input, rowId, docType) {
        if (!input.files || !input.files[0]) return;
        const statusEl = document.getElementById('dir-doc-status-' + rowId + '-' + docType);
        if (statusEl) statusEl.textContent = 'Uploading…';
        const tbody = document.getElementById('directors-tbody');
        let dirName = '';
        let dirIdx = 1;
        if (tbody) {
            const mainRows = Array.from(tbody.querySelectorAll('tr.dir-main-row'));
            const mainRow = mainRows.find(tr => tr.dataset.rowId === rowId);
            if (mainRow) {
                dirIdx = mainRows.indexOf(mainRow) + 1;
                const nameInput = mainRow.querySelector('[name="dir_full_name"]');
                if (nameInput) dirName = nameInput.value;
            }
        }
        const fd = new FormData();
        fd.append('access_token', accessToken);
        fd.append('dir_index', String(dirIdx));
        fd.append('dir_name', dirName);
        fd.append('doc_type', docType);
        fd.append('file', input.files[0]);
        try {
            const resp = await fetch('/aml/form/upload_director_doc', { method: 'POST', body: fd });
            const result = await resp.json();
            if (result.success) {
                if (statusEl) statusEl.textContent = '✔ ' + result.filename;
            } else {
                if (statusEl) statusEl.textContent = 'Failed';
                showToast('Upload failed: ' + (result.error || ''), 'error');
            }
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Error';
            showToast('Upload error: ' + e.message, 'error');
        }
    }

    // ---- Shareholders Table ----
    function _buildShDocItem(rowId, dt, label) {
        return `
            <div style="display:flex;flex-direction:column;gap:4px;min-width:160px;">
                <span style="font-size:11px;color:#555;font-weight:600;">${label}</span>
                <label style="display:inline-flex;align-items:center;gap:6px;cursor:pointer;background:#e3f2fd;border:1px solid #90caf9;border-radius:4px;padding:4px 8px;font-size:11px;font-weight:500;color:#1565c0;">
                    &#128206; Upload
                    <input type="file" accept=".pdf,.jpg,.jpeg,.png,.doc,.docx" style="display:none;"
                        onchange="amlForm.uploadShareholderDoc(this,'${rowId}','${dt}')"/>
                </label>
                <span id="sh-doc-status-${rowId}-${dt}" style="font-size:11px;color:#2e7d32;"></span>
            </div>
        `;
    }

    function _buildShDocsContent(rowId, shType) {
        const IND = { passport: 'Passport Copy', proof_of_residence: 'Proof of Residence', emirates_id: 'Emirates ID' };
        const CORP = { trade_license: 'Trade License', memorandum: 'Memorandum of Association / Articles of Association' };
        let inner = '';
        if (shType === 'individual') {
            inner = Object.entries(IND).map(([dt, lbl]) => _buildShDocItem(rowId, dt, lbl)).join('');
        } else if (shType === 'corporate') {
            inner = Object.entries(CORP).map(([dt, lbl]) => _buildShDocItem(rowId, dt, lbl)).join('');
        } else {
            inner = '<span style="font-size:12px;color:#999;padding-top:6px;">Select a type above to see upload options.</span>';
        }
        return `<span style="font-size:12px;font-weight:600;color:#555;padding-top:6px;white-space:nowrap;">Documents:</span>${inner}`;
    }

    function addShareholderRow(prefill = null) {
        const tbody = document.getElementById('shareholders-tbody');
        if (!tbody) return;
        shRowCounter++;
        const rowId = 'sh-' + shRowCounter;
        const idx = tbody.querySelectorAll('tr.sh-main-row').length + 1;
        const s = prefill || {};
        const shType = s.shareholder_type || '';

        const tr = document.createElement('tr');
        tr.className = 'sh-main-row';
        tr.dataset.rowId = rowId;
        tr.innerHTML = `
            <td>${idx}</td>
            <td><input type="text" name="sh_name" placeholder="Shareholder Name" required value="${esc(s.shareholder_name||'')}"/></td>
            <td><input type="text" name="sh_nationality" placeholder="Nationality" required value="${esc(s.nationality||'')}"/></td>
            <td>
                <select name="sh_type" required onchange="amlForm.updateShareholderDocs('${rowId}', this.value)">
                    <option value="">– Select –</option>
                    <option value="individual" ${shType==='individual'?'selected':''}>Individual</option>
                    <option value="corporate" ${shType==='corporate'?'selected':''}>Corporate</option>
                </select>
            </td>
            <td><input type="text" name="sh_passport" placeholder="Passport No. / Corp. Reg. No." required value="${esc(s.passport_no||'')}"/></td>
            <td>
                <select name="sh_share_class" required>
                    <option value="">– –</option>
                    <option value="ordinary" ${s.share_class==='ordinary'?'selected':''}>Ordinary</option>
                    <option value="preference" ${s.share_class==='preference'?'selected':''}>Preference</option>
                </select>
            </td>
            <td><input type="number" name="sh_num_shares" min="0" required value="${s.num_shares||0}" style="width:80px"/></td>
            <td><input type="number" name="sh_pct" min="0" max="100" step="0.01" required value="${s.percentage_holding||0}" style="width:70px"/></td>
            <td><input type="date" name="sh_date_entry" required value="${esc(s.date_of_entry||'')}"/></td>
            <td><button type="button" class="del-row-btn" onclick="amlForm.removeShareholderRow('${rowId}')">✕</button></td>
        `;
        tbody.appendChild(tr);

        const docsTr = document.createElement('tr');
        docsTr.className = 'sh-docs-row';
        docsTr.dataset.rowId = rowId;
        docsTr.innerHTML = `
            <td colspan="10" style="background:#f5f9ff;padding:8px 16px;border-top:none;">
                <div style="display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap;" id="sh-docs-content-${rowId}">
                    ${_buildShDocsContent(rowId, shType)}
                </div>
            </td>
        `;
        tbody.appendChild(docsTr);
    }

    function updateShareholderDocs(rowId, shType) {
        const el = document.getElementById('sh-docs-content-' + rowId);
        if (el) el.innerHTML = _buildShDocsContent(rowId, shType);
    }

    function removeShareholderRow(rowId) {
        const tbody = document.getElementById('shareholders-tbody');
        if (!tbody) return;
        tbody.querySelectorAll('[data-row-id="' + rowId + '"]').forEach(tr => tr.remove());
        window.renumberRows('shareholders-tbody');
    }

    async function uploadShareholderDoc(input, rowId, docType) {
        if (!input.files || !input.files[0]) return;
        const statusEl = document.getElementById('sh-doc-status-' + rowId + '-' + docType);
        if (statusEl) statusEl.textContent = 'Uploading…';
        const tbody = document.getElementById('shareholders-tbody');
        let shName = '';
        let shIdx = 1;
        if (tbody) {
            const mainRows = Array.from(tbody.querySelectorAll('tr.sh-main-row'));
            const mainRow = mainRows.find(tr => tr.dataset.rowId === rowId);
            if (mainRow) {
                shIdx = mainRows.indexOf(mainRow) + 1;
                const nameInput = mainRow.querySelector('[name="sh_name"]');
                if (nameInput) shName = nameInput.value;
            }
        }
        const fd = new FormData();
        fd.append('access_token', accessToken);
        fd.append('sh_index', String(shIdx));
        fd.append('sh_name', shName);
        fd.append('doc_type', docType);
        fd.append('file', input.files[0]);
        try {
            const resp = await fetch('/aml/form/upload_shareholder_doc', { method: 'POST', body: fd });
            const result = await resp.json();
            if (result.success) {
                if (statusEl) statusEl.textContent = '✔ ' + result.filename;
            } else {
                if (statusEl) statusEl.textContent = 'Failed';
                showToast('Upload failed: ' + (result.error || ''), 'error');
            }
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Error';
            showToast('Upload error: ' + e.message, 'error');
        }
    }

    async function saveShareholders() {
        const tbody = document.getElementById('shareholders-tbody');
        const rows = [];
        if (tbody) {
            tbody.querySelectorAll('tr.sh-main-row').forEach(tr => {
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
                    'Place of Incorporation': formData['ent_place_of_incorporation'],
                    'Registration Authority': formData['ent_registration_authority'],
                    'License Number': formData['ent_license_number'],
                    'License Expiry': formData['ent_license_expiry'],
                    'Registered Address': formData['ent_registered_address'],
                    'Business Address': formData['ent_business_address'],
                    'Industry Type': formData['ent_industry_type'],
                    'List of Business Activities': formData['ent_nature_of_business'],
                    'Source of Wealth': formData['ent_source_of_wealth'],
                    'Ownership Complexity': formData['ent_ownership_complexity'],
                    'Cash Payment Transactions': formData['ent_countries_commercial'],
                    'High-Risk Jurisdiction': formData['ent_high_risk_jurisdiction'],
                    'Channel – Cash': formData['ent_channel_cash'] ? 'Yes' : '',
                    'Channel – Wire Transfer': formData['ent_channel_wire'] ? 'Yes' : '',
                    'Channel – Cheque': formData['ent_channel_cheque'] ? 'Yes' : '',
                    'Channel – Credit Card': formData['ent_channel_credit'] ? 'Yes' : '',
                    'Channel – Crypto': formData['ent_channel_crypto'] ? 'Yes' : '',
                    'Channel – Debit Card': formData['ent_channel_debit'] ? 'Yes' : '',
                    'Cash Payment < AED 50K': formData['ent_cash_less_50k'] ? 'Yes' : '',
                    'Cash Payment > AED 50K': formData['ent_cash_more_50k'] ? 'Yes' : '',
                    'Cash Payment N/A': formData['ent_cash_na'] ? 'Yes' : '',
                    'Top 5 Suppliers': formData['ent_top5_suppliers'],
                    'Top 5 Customers': formData['ent_top5_customers'],
                    'Contact Person': formData['ent_contact_name'],
                    'Contact Designation': formData['ent_contact_designation'],
                    'Contact Email': formData['ent_contact_email'],
                    'Contact Mobile': formData['ent_contact_mobile'],
                    'Manager Name as per License': formData['ent_manager_name'],
                    'Parent Company / Head Office': formData['ent_parent_company_name'],
                    'Parent Company Address': formData['ent_parent_company_address'],
                    'Subject to International Sanctions': formData['ent_international_sanctions'],
                    'PEP – Shareholder': formData['ent_pep_shareholder'],
                    'PEP – Director': formData['ent_pep_director'],
                    'PEP – Owner / Partner': formData['ent_pep_owner'],
                    'PEP – Local Sponsor': formData['ent_pep_local_sponsor'],
                    'PEP – Key Management': formData['ent_pep_key_management'],
                    'PEP – Officer': formData['ent_pep_officer'],
                    'PEP – Agent': formData['ent_pep_agent'],
                },
            });

            sections.push({
                title: 'UBO',
                fields: {
                    'Full Name': formData['ubo_full_name'],
                    'Gender': formData['ubo_gender'],
                    'Nationality': formData['ubo_nationality'],
                    'Date of Birth': formData['ubo_date_of_birth'],
                    'Place of Birth': formData['ubo_place_of_birth'],
                    'Dual Citizenship': formData['ubo_dual_citizenship'],
                    'Source of Income': formData['ubo_source_of_income'],
                    'Holds Shares on Behalf of Another': formData['ubo_hold_shares_behalf'],
                    'High-Risk Jurisdiction': formData['ubo_high_risk_jurisdiction'],
                    'Home Country Address': formData['ubo_home_country_address'],
                    'UAE Address': formData['ubo_uae_address'],
                    'Mobile': formData['ubo_mobile'],
                    'Email': formData['ubo_email'],
                    'High Net Worth Individual': formData['ubo_high_net_worth'],
                    'Bank Name': formData['ubo_bank_name'],
                    'Bank Branch Address': formData['ubo_bank_branch_address'],
                    'IBAN / Account Number': formData['ubo_iban'],
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
                    'Place of Birth': formData['ind_place_of_birth'],
                    'ID Type': formData['ind_id_type'],
                    'ID Number': formData['ind_id_number'],
                    'Issuing Country': formData['ind_issuing_country'],
                    'Valid Until': formData['ind_valid_until'],
                    'Permanent Address': formData['ind_permanent_address'],
                    'UAE Address': formData['ind_uae_address'],
                    'City': formData['ind_city'],
                    'Country': formData['ind_country'],
                    'Mobile': formData['ind_mobile'],
                    'Email': formData['ind_email'],
                    'Proof of Address Type': formData['ind_proof_address_type'],
                    'Document Date': formData['ind_document_date'],
                    'Purpose of Relationship': formData['ind_purpose_of_relationship'],
                    'Expected Transactions': formData['ind_expected_transactions'],
                    'Monthly Turnover': formData['ind_monthly_turnover'],
                    'Source of Funds': formData['ind_source_of_funds'],
                    'Holds Shares on Behalf of Another': formData['ind_hold_shares_behalf'],
                    'High-Risk Jurisdiction': formData['ind_high_risk_jurisdiction'],
                    'Anticipated Origin of Funds': formData['ind_anticipated_origin'],
                    'Dual Citizenship': formData['ind_dual_citizenship'],
                    'High Net Worth Individual': formData['ind_high_net_worth'],
                },
            });
        }

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
        // Check mandatory documents are uploaded before submitting
        const ANY_ONE_KEYS = ['cert_incumbency'];
        const missingDocs = docLines.filter(doc => {
            if (!doc.is_mandatory) return false;
            if (ANY_ONE_KEYS.includes(doc.doc_key)) return false;
            const el = document.getElementById('doc-item-' + doc.id);
            return el && !el.classList.contains('uploaded');
        });
        if (missingDocs.length > 0) {
            const names = missingDocs.map(d => '• ' + d.doc_name).join('\n');
            showToast(
                'Please attach the following mandatory documents before submitting:\n' + names,
                'error'
            );
            // Navigate to the documents page so the user can upload
            const docPageIdx = getPages().indexOf('page-5');
            if (docPageIdx !== -1) showPage(docPageIdx);
            const firstEl = document.getElementById('doc-item-' + missingDocs[0].id);
            if (firstEl) firstEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
        }

        // Validate review page
        const acceptBox = document.getElementById('accept_declaration');
        if (!acceptBox || !acceptBox.checked) {
            showToast('Please accept the declaration.', 'error');
            return;
        }
        const signatoryName = (document.getElementById('signatory_name') || {}).value || '';
        if (!signatoryName.trim()) {
            showToast('Please enter the signatory name.', 'error');
            return;
        }
        const signedOn = (document.getElementById('signed_on') || {}).value || '';
        if (!signedOn) {
            showToast('Please enter the signed on date.', 'error');
            return;
        }
        const signatoryDesignation = (document.getElementById('signatory_designation') || {}).value || '';
        if (!signatoryDesignation.trim()) {
            showToast('Please enter the designation.', 'error');
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
                signatory_designation: signatoryDesignation,
                signed_on: signedOn,
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

    function togglePurposeOther(val) {
        const wrap = document.getElementById('ind-purpose-other-wrap');
        const input = document.getElementById('ind_purpose_of_relationship_other');
        if (!wrap) return;
        const show = val === 'other';
        wrap.style.display = show ? '' : 'none';
        if (input) input.required = show;
    }

    function toggleIndDualCitizenship(val) {
        const wrap = document.getElementById('ind-dual-citizenship-wrap');
        const input = document.getElementById('ind_dual_citizenship_detail');
        if (!wrap) return;
        const show = val === 'yes';
        wrap.style.display = show ? '' : 'none';
        if (input) input.required = show;
    }

    function toggleEl(id, show) {
        const el = document.getElementById(id);
        if (el) el.style.display = show ? '' : 'none';
    }

    // ---- Country Picker ----
    function initCountryPickers() {
        ['supplier_country_select', 'customer_country_select', 'ubo_nationality', 'ubo_place_of_birth', 'ind_nationality', 'ind_place_of_birth'].forEach(id => {
            const sel = document.getElementById(id);
            if (!sel) return;
            COUNTRIES.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c;
                opt.textContent = c;
                sel.appendChild(opt);
            });
        });
    }

    function addCountry(type) {
        const selId = type === 'supplier' ? 'supplier_country_select' : 'customer_country_select';
        const sel = document.getElementById(selId);
        if (!sel || !sel.value) { showToast('Please select a country first.', 'error'); return; }
        const country = sel.value;
        const arr = type === 'supplier' ? supplierCountries : customerCountries;
        if (arr.includes(country)) { showToast(country + ' is already added.', 'error'); return; }
        arr.push(country);
        sel.value = '';
        renderCountryTags(type);
        updateCountryHidden(type);
    }

    function removeCountry(type, country) {
        const arr = type === 'supplier' ? supplierCountries : customerCountries;
        const idx = arr.indexOf(country);
        if (idx > -1) arr.splice(idx, 1);
        renderCountryTags(type);
        updateCountryHidden(type);
    }

    function renderCountryTags(type) {
        const tagsId = type === 'supplier' ? 'supplier_country_tags' : 'customer_country_tags';
        const container = document.getElementById(tagsId);
        if (!container) return;
        const arr = type === 'supplier' ? supplierCountries : customerCountries;
        container.innerHTML = arr.map(c =>
            `<span class="aml-country-tag">${esc(c)}<button type="button" class="aml-country-tag-remove" onclick="amlForm.removeCountry('${type}','${esc(c)}')" title="Remove">&#x2715;</button></span>`
        ).join('');
    }

    function updateCountryHidden(type) {
        const hiddenId = type === 'supplier' ? 'ent_top5_suppliers_val' : 'ent_top5_customers_val';
        const hidden = document.getElementById(hiddenId);
        const arr = type === 'supplier' ? supplierCountries : customerCountries;
        if (hidden) hidden.value = arr.join(', ');
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
    return { init, nextPage, prevPage, savePage, addDirectorRow, removeDirectorRow, addShareholderRow, removeShareholderRow, updateShareholderDocs, uploadShareholderDoc, handleDocUpload, clearSignature, switchSigTab, uploadSignatureImage, submitForm, toggleIdOther, toggleProofOther, togglePurposeOther, toggleIndDualCitizenship, toggleEl, addCountry, removeCountry, uploadDirectorDoc };

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
            div.className = 'aml-doc-item';
            div.id = 'hit-doc-item-' + doc.id;
            div.innerHTML = `
                <div class="aml-doc-num">${i + 1}</div>
                <div class="aml-doc-info">
                    <span class="aml-doc-name">${esc(doc.document_name)}</span>
                    <span class="aml-doc-badge mandatory">Required</span>
                    <div id="hit-doc-names-${doc.id}"></div>
                </div>
                <div class="aml-doc-upload-btn">
                    <label>
                        📎 Upload
                        <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
                            onchange="amlAdditional.handleUpload(this, ${doc.id})"/>
                    </label>
                    <span class="aml-upload-status" id="hit-doc-status-${doc.id}"></span>
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
        // Validate all required documents are uploaded in this session
        const missingDocs = hitDocs.filter(doc => {
            const el = document.getElementById('hit-doc-item-' + doc.id);
            return el && !el.classList.contains('uploaded');
        });
        if (missingDocs.length > 0) {
            const names = missingDocs.map(d => '• ' + d.document_name).join('\n');
            showToast('Please attach the following required documents before submitting:\n' + names, 'error');
            const firstEl = document.getElementById('hit-doc-item-' + missingDocs[0].id);
            if (firstEl) firstEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
        }

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
    let num = 1;
    tbody.querySelectorAll('tr').forEach(tr => {
        if (tr.classList.contains('dir-docs-row') || tr.classList.contains('sh-docs-row')) return;
        const firstTd = tr.querySelector('td:first-child');
        if (firstTd && !firstTd.querySelector('input') && !firstTd.querySelector('select')) {
            firstTd.textContent = num++;
        }
    });
};
