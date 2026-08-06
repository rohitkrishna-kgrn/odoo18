/* ============================================================
   KGRN Client Discovery Form — front-end controller
   Vanilla JS (page is served outside the web-client asset bundle).
   ============================================================ */
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        var form = document.querySelector(".disc-form");
        if (!form) { return; }

        var PREFILL = readJSON(".disc-prefill-json", {});
        var SUBMITTED = readJSON(".disc-submitted-json", {});

        var sections = Array.prototype.slice.call(form.querySelectorAll(".disc-section"));
        var steps = Array.prototype.slice.call(document.querySelectorAll(".disc-step"));
        var progressFill = document.querySelector(".disc-progress-fill");
        var btnPrev = form.querySelector(".disc-prev");
        var btnNext = form.querySelector(".disc-next");
        var btnSubmit = form.querySelector(".disc-submit");
        var current = 0;

        // --- init ----------------------------------------------------
        setupFieldInteractions(document);
        setupConditionals(document);
        applyPrefill();
        restoreTopLevel();
        setupEntities();
        showSection(0, true);

        btnNext.addEventListener("click", function () {
            if (!validateSection(sections[current])) { return; }
            if (current < sections.length - 1) { showSection(current + 1); }
        });
        btnPrev.addEventListener("click", function () {
            if (current > 0) { showSection(current - 1); }
        });
        steps.forEach(function (step, idx) {
            step.addEventListener("click", function () {
                if (idx <= current) { showSection(idx); }
            });
        });

        form.addEventListener("submit", function (ev) {
            for (var i = 0; i < sections.length; i++) {
                if (!validateSection(sections[i])) {
                    showSection(i);
                    ev.preventDefault();
                    return;
                }
            }
            syncSignatures();
            form.querySelector(".disc-payload").value = JSON.stringify(serialize());
        });

        // ============================================================
        // Section navigation
        // ============================================================
        function showSection(idx, instant) {
            current = idx;
            sections.forEach(function (sec, i) { sec.classList.toggle("is-active", i === idx); });
            steps.forEach(function (step, i) {
                step.classList.toggle("is-active", i === idx);
                step.classList.toggle("is-done", i < idx);
            });
            var pct = sections.length > 1 ? (idx / (sections.length - 1)) * 100 : 100;
            if (progressFill) { progressFill.style.width = pct + "%"; }

            btnPrev.style.display = idx === 0 ? "none" : "";
            var last = idx === sections.length - 1;
            btnNext.style.display = last ? "none" : "";
            btnSubmit.style.display = last ? "" : "none";

            sections[idx].querySelectorAll(".disc-sign-canvas").forEach(initSignature);
            if (!instant) { window.scrollTo({ top: 0, behavior: "smooth" }); }
        }

        // ============================================================
        // Entities sub-form — count driven by the "entityCount" field
        // ============================================================
        function setupEntities() {
            var wrap = document.querySelector(".disc-entities-wrap");
            if (!wrap) { return; }
            var countField = form.querySelector('.disc-field[data-key="entityCount"]');
            var countInput = countField ? countField.querySelector(".disc-value") : null;

            function desired() {
                var n = parseInt(countInput && countInput.value, 10);
                if (isNaN(n) || n < 1) { n = 1; }
                if (n > 50) { n = 50; }
                return n;
            }
            if (countInput) {
                var sync = function () { generateEntities(wrap, desired()); };
                countInput.addEventListener("input", sync);
                countInput.addEventListener("change", sync);
            }

            if (Array.isArray(SUBMITTED.entities) && SUBMITTED.entities.length) {
                if (countInput && !countInput.value) {
                    countInput.value = SUBMITTED.entities.length;
                }
                generateEntities(wrap, SUBMITTED.entities.length);
                var blocks = wrap.querySelectorAll(".disc-entities .disc-entity");
                SUBMITTED.entities.forEach(function (ent, i) {
                    if (!blocks[i]) { return; }
                    blocks[i].querySelectorAll(".disc-efield").forEach(function (f) {
                        setFieldValue(f, ent[f.getAttribute("data-key")]);
                    });
                    setupConditionals(blocks[i]);
                });
            } else {
                generateEntities(wrap, desired());
            }
        }

        function generateEntities(wrap, n) {
            var container = wrap.querySelector(".disc-entities");
            if (container.querySelectorAll(".disc-entity").length === n) { return; }
            var existing = collectEntities(wrap);
            container.innerHTML = "";
            for (var i = 0; i < n; i++) {
                var tmpl = wrap.querySelector(".disc-entity-template .disc-entity");
                var block = tmpl.cloneNode(true);
                container.appendChild(block);
                setupFieldInteractions(block);
                setupConditionals(block);
                if (existing[i]) {
                    block.querySelectorAll(".disc-efield").forEach(function (f) {
                        setFieldValue(f, existing[i][f.getAttribute("data-key")]);
                    });
                }
            }
            renumberEntities(wrap);
        }

        function collectEntities(wrap) {
            var out = [];
            wrap.querySelectorAll(".disc-entities .disc-entity").forEach(function (block) {
                var ent = {};
                block.querySelectorAll(".disc-efield").forEach(function (f) {
                    ent[f.getAttribute("data-key")] = getFieldValue(f);
                });
                out.push(ent);
            });
            return out;
        }

        function renumberEntities(wrap) {
            wrap.querySelectorAll(".disc-entities .disc-entity").forEach(function (b, i) {
                b.querySelector(".disc-entity-title").textContent = "Entity " + (i + 1);
            });
        }

        // ============================================================
        // Field interactions: choice styling + "Other" manual input
        // ============================================================
        function setupFieldInteractions(scope) {
            scope.querySelectorAll(".disc-choice input").forEach(function (input) {
                input.addEventListener("change", function () {
                    var field = input.closest(".disc-field, .disc-efield");
                    if (input.type === "radio" && field) {
                        field.querySelectorAll(".disc-choice").forEach(function (c) {
                            c.classList.remove("is-selected");
                        });
                    }
                    var label = input.closest(".disc-choice");
                    if (label) { label.classList.toggle("is-selected", input.checked); }
                    if (field) { updateOther(field); }
                });
            });
            scope.querySelectorAll("select.disc-value").forEach(function (sel) {
                sel.addEventListener("change", function () {
                    var field = sel.closest(".disc-field, .disc-efield");
                    if (field) { updateOther(field); }
                });
            });
            scope.querySelectorAll(".disc-other-input").forEach(function (inp) {
                var field = inp.closest(".disc-field, .disc-efield");
                if (field) { updateOther(field); }
            });
        }

        function updateOther(field) {
            var otherInput = field.querySelector(".disc-other-input");
            if (!otherInput) { return; }
            var show = getSelectedValues(field).indexOf("Other") !== -1;
            otherInput.classList.toggle("is-hidden", !show);
            if (!show) { otherInput.value = ""; }
        }

        function setupConditionals(scope) {
            scope.querySelectorAll("[data-showif-field]").forEach(function (field) {
                var srcKey = field.getAttribute("data-showif-field");
                var values = (field.getAttribute("data-showif-values") || "").split("|");
                var block = field.closest(".disc-entity") || field.closest(".disc-form");
                var srcField = block.querySelector('[data-key="' + srcKey + '"]');
                if (!srcField) { return; }
                var evaluate = function () {
                    var selected = readChoiceValues(srcField);
                    var show = values.some(function (v) { return selected.indexOf(v) !== -1; });
                    field.classList.toggle("is-hidden", !show);
                };
                srcField.querySelectorAll(".disc-opt").forEach(function (opt) {
                    opt.addEventListener("change", evaluate);
                });
                evaluate();
            });
        }

        // ============================================================
        // Prefill / restore
        // ============================================================
        function applyPrefill() {
            var map = {
                company_name: "legalCompanyName",
                contact_name: "primaryContactName",
                email: "primaryContactEmail",
                phone: "primaryContactMobile"
            };
            Object.keys(map).forEach(function (src) {
                if (!PREFILL[src]) { return; }
                var field = form.querySelector('.disc-field[data-key="' + map[src] + '"]');
                if (field) {
                    var input = field.querySelector(".disc-value");
                    if (input && !input.value) { input.value = PREFILL[src]; }
                }
            });
        }

        function restoreTopLevel() {
            if (!SUBMITTED || !Object.keys(SUBMITTED).length) { return; }
            form.querySelectorAll(".disc-section > .disc-section-body > .disc-field")
                .forEach(function (field) {
                    setFieldValue(field, SUBMITTED[field.getAttribute("data-key")]);
                });
        }

        // ============================================================
        // Value read / write
        // ============================================================
        function readChoiceValues(field) {
            return Array.prototype.slice
                .call(field.querySelectorAll(".disc-opt:checked"))
                .map(function (o) { return o.value; });
        }

        function getSelectedValues(field) {
            if (field.getAttribute("data-type") === "select") {
                var sel = field.querySelector(".disc-value");
                return sel && sel.value ? [sel.value] : [];
            }
            return readChoiceValues(field);
        }

        function getFieldValue(field) {
            var type = field.getAttribute("data-type");
            var otherInput = field.querySelector(".disc-other-input");
            var otherText = otherInput ? otherInput.value.trim() : "";

            if (type === "radio") {
                var v = readChoiceValues(field);
                if (!v.length) { return ""; }
                return v[0] === "Other" && otherInput ? otherText : v[0];
            }
            if (type === "checkbox") {
                var arr = readChoiceValues(field);
                if (otherInput && arr.indexOf("Other") !== -1) {
                    arr = arr.map(function (x) { return x === "Other" ? otherText : x; })
                             .filter(function (x) { return x !== ""; });
                }
                return arr;
            }
            if (type === "checkbox_single") {
                var cb = field.querySelector(".disc-value");
                return cb ? cb.checked : false;
            }
            if (type === "signature") {
                var pad = field.querySelector(".disc-sign-canvas");
                if (pad) { syncSignatureCanvas(pad); }
                var hidden = field.querySelector(".disc-sign-data");
                return hidden ? hidden.value : "";
            }
            if (type === "select") {
                var s = field.querySelector(".disc-value");
                var val = s ? s.value : "";
                return val === "Other" && otherInput ? otherText : val;
            }
            var el = field.querySelector(".disc-value");
            return el ? el.value.trim() : "";
        }

        function setFieldValue(field, value) {
            if (value === undefined || value === null) { return; }
            var type = field.getAttribute("data-type");
            if (type === "radio") {
                field.querySelectorAll(".disc-opt").forEach(function (o) {
                    o.checked = (o.value === value);
                    o.dispatchEvent(new Event("change"));
                });
            } else if (type === "checkbox") {
                var arr = Array.isArray(value) ? value : [value];
                field.querySelectorAll(".disc-opt").forEach(function (o) {
                    o.checked = arr.indexOf(o.value) !== -1;
                    o.dispatchEvent(new Event("change"));
                });
            } else if (type === "checkbox_single") {
                var cb = field.querySelector(".disc-value");
                if (cb) { cb.checked = !!value; cb.dispatchEvent(new Event("change")); }
            } else if (type === "signature") {
                var hidden = field.querySelector(".disc-sign-data");
                if (hidden && typeof value === "string") {
                    hidden.value = value;
                    field._pendingSig = value;
                }
            } else if (type === "select") {
                var sel = field.querySelector(".disc-value");
                if (!sel) { return; }
                var other = field.querySelector(".disc-other-input");
                var has = Array.prototype.some.call(sel.options, function (o) { return o.value === value; });
                if (!has && other && value) {
                    sel.value = "Other"; other.value = value;
                } else {
                    sel.value = value;
                }
                updateOther(field);
            } else {
                var input = field.querySelector(".disc-value");
                if (input) { input.value = value; }
            }
        }

        // ============================================================
        // Serialization
        // ============================================================
        function serialize() {
            var out = {};
            form.querySelectorAll(".disc-section > .disc-section-body > .disc-field")
                .forEach(function (field) {
                    out[field.getAttribute("data-key")] = getFieldValue(field);
                });
            var wrap = document.querySelector(".disc-entities-wrap");
            if (wrap) { out.entities = collectEntities(wrap); }
            return out;
        }

        // ============================================================
        // Validation
        // ============================================================
        function validateSection(section) {
            var ok = true;
            var fields = Array.prototype.filter.call(
                section.querySelectorAll(".disc-field, .disc-efield"),
                function (field) { return !field.closest(".disc-entity-template"); }
            );
            fields.forEach(function (field) {
                if (field.classList.contains("is-hidden")) { return; }
                if (field.getAttribute("data-required") !== "1") { return; }
                var val = getFieldValue(field);
                var empty = (val === "" || val === false ||
                             (Array.isArray(val) && val.length === 0));
                var msg = "";
                if (empty) {
                    msg = "This field is required.";
                } else {
                    var numInput = field.querySelector('input[type="number"]');
                    if (numInput && numInput.min !== "" &&
                        Number(val) < Number(numInput.min)) {
                        msg = "Enter a value of " + numInput.min + " or more.";
                    }
                }
                var errEl = field.querySelector(".disc-field-error");
                if (errEl) { errEl.textContent = msg; }
                field.classList.toggle("has-error", !!msg);
                if (msg && ok) {
                    ok = false;
                    field.scrollIntoView({ behavior: "smooth", block: "center" });
                }
            });
            return ok;
        }

        // ============================================================
        // Signature pad
        // ============================================================
        function initSignature(canvas) {
            if (canvas._init) { syncSignatureCanvas(canvas); return; }
            canvas._init = true;
            var ratio = window.devicePixelRatio || 1;
            var rect = canvas.getBoundingClientRect();
            canvas.width = Math.max(rect.width, 300) * ratio;
            canvas.height = 170 * ratio;
            var ctx = canvas.getContext("2d");
            ctx.scale(ratio, ratio);
            ctx.lineWidth = 2;
            ctx.lineCap = "round";
            ctx.strokeStyle = "#0d2b45";
            canvas._ctx = ctx;
            canvas._empty = true;

            var drawing = false;
            var field = canvas.closest(".disc-field, .disc-efield");
            var hidden = field.querySelector(".disc-sign-data");

            function pos(e) {
                var r = canvas.getBoundingClientRect();
                var p = e.touches ? e.touches[0] : e;
                return { x: p.clientX - r.left, y: p.clientY - r.top };
            }
            function start(e) { drawing = true; var p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); e.preventDefault(); }
            function move(e) {
                if (!drawing) { return; }
                var p = pos(e); ctx.lineTo(p.x, p.y); ctx.stroke();
                canvas._empty = false; e.preventDefault();
            }
            function end() {
                if (!drawing) { return; }
                drawing = false;
                hidden.value = canvas._empty ? "" : canvas.toDataURL("image/png");
            }
            canvas.addEventListener("mousedown", start);
            canvas.addEventListener("mousemove", move);
            window.addEventListener("mouseup", end);
            canvas.addEventListener("touchstart", start, { passive: false });
            canvas.addEventListener("touchmove", move, { passive: false });
            canvas.addEventListener("touchend", end);

            var clearBtn = field.querySelector(".disc-sign-clear");
            if (clearBtn) {
                clearBtn.addEventListener("click", function () {
                    ctx.clearRect(0, 0, canvas.width, canvas.height);
                    canvas._empty = true; hidden.value = "";
                });
            }
            if (field._pendingSig) { paintDataUrl(canvas, field._pendingSig); }
        }

        function paintDataUrl(canvas, dataUrl) {
            var img = new Image();
            img.onload = function () {
                var r = canvas.getBoundingClientRect();
                canvas._ctx.drawImage(img, 0, 0, r.width, 170);
                canvas._empty = false;
            };
            img.src = dataUrl;
        }

        function syncSignatureCanvas(canvas) {
            if (!canvas._init) { return; }
            var field = canvas.closest(".disc-field, .disc-efield");
            var hidden = field.querySelector(".disc-sign-data");
            if (!canvas._empty) { hidden.value = canvas.toDataURL("image/png"); }
        }

        function syncSignatures() {
            document.querySelectorAll(".disc-sign-canvas").forEach(syncSignatureCanvas);
        }

        // ============================================================
        // Helpers
        // ============================================================
        function readJSON(selector, fallback) {
            var el = document.querySelector(selector);
            if (!el) { return fallback; }
            try { return JSON.parse(el.value || el.textContent || "{}"); }
            catch (e) { return fallback; }
        }
    });
})();
