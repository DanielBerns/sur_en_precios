/* ==========================================================================
   Sur en Precios — Visual Color Palette Editor Controller (editor.js)
   --------------------------------------------------------------------------
   Zero inline style mutations: uses Constructable Stylesheets (CSSStyleSheet)
   on the same-origin preview iframe and native <input type="color"> swatches.
   ========================================================================== */

(function () {
    "use strict";

    const HEX_RE = /^#[0-9a-fA-F]{6}$/;

    const bootstrapEl = document.getElementById("initial_palette_data");
    if (!bootstrapEl) return;
    const bootstrap = JSON.parse(bootstrapEl.textContent || "{}");

    // State
    let savedValues = Object.assign({}, bootstrap.palette.values);
    let savedColorScheme = bootstrap.palette.color_scheme || "dark";
    let currentValues = Object.assign({}, bootstrap.palette.values);
    let colorSchemeMode = "auto"; // "auto" | "dark" | "light"
    let isComparingBefore = false;
    let isInspectMode = false;
    let inspectedTokenFilter = null; // Set of token names when element inspected

    const undoStack = [];
    const redoStack = [];
    const MAX_HISTORY = 60;

    // Map of group_id -> array of token names, and token_name -> selectors
    const groupTokensMap = {};
    const tokenSelectorsMap = {};
    const presetsMap = {};

    (bootstrap.palette.groups || []).forEach(function (group) {
        groupTokensMap[group.id] = [];
        (group.tokens || []).forEach(function (tok) {
            groupTokensMap[group.id].push(tok.name);
            tokenSelectorsMap[tok.name] = tok.selectors || [];
        });
    });

    (bootstrap.presets || []).forEach(function (p) {
        presetsMap[p.slug] = p;
    });

    const contrastPairs = bootstrap.contrast_pairs || [];

    // Group HSL baseline snapshot while dragging sliders
    const hslBaseSnapshots = {};

    // DOM Elements
    const previewIframe = document.getElementById("preview_iframe");
    const previewRouteSelect = document.getElementById("preview_route_select");
    const previewCurrentUrl = document.getElementById("preview_current_url");
    const previewHoverHint = document.getElementById("preview_hover_hint");
    const btnReloadPreview = document.getElementById("btn_reload_preview");

    const presetSelect = document.getElementById("preset_select");
    const btnOpenSavePreset = document.getElementById("btn_open_save_preset");
    const btnDeletePreset = document.getElementById("btn_delete_preset");
    const btnOpenImport = document.getElementById("btn_open_import");

    const btnUndo = document.getElementById("btn_undo");
    const btnRedo = document.getElementById("btn_redo");
    const btnCompareToggle = document.getElementById("btn_compare_toggle");
    const btnResetSaved = document.getElementById("btn_reset_saved");

    const btnExportCss = document.getElementById("btn_export_css");
    const btnExportYaml = document.getElementById("btn_export_yaml");
    const btnSaveCss = document.getElementById("btn_save_css");
    const unsavedBadge = document.getElementById("unsaved_badge");

    const tokenFilterInput = document.getElementById("token_filter_input");
    const btnClearFilter = document.getElementById("btn_clear_filter");
    const inspectModeToggle = document.getElementById("inspect_mode_toggle");
    const inspectActiveBanner = document.getElementById("inspect_active_banner");
    const btnShowAllTokens = document.getElementById("btn_show_all_tokens");
    const colorSchemeSelect = document.getElementById("color_scheme_select");
    const btnToggleAllGroups = document.getElementById("btn_toggle_all_groups");

    const contrastSummaryBadge = document.getElementById("contrast_summary_badge");
    const contrastChecksList = document.getElementById("contrast_checks_list");

    const statusToast = document.getElementById("status_toast");
    const statusToastIcon = document.getElementById("status_toast_icon");
    const statusToastText = document.getElementById("status_toast_text");
    const statusToastClose = document.getElementById("status_toast_close");

    const savePresetDialog = document.getElementById("save_preset_dialog");
    const savePresetForm = document.getElementById("save_preset_form");
    const presetNameInput = document.getElementById("preset_name_input");
    const presetDescInput = document.getElementById("preset_desc_input");

    const importPaletteDialog = document.getElementById("import_palette_dialog");
    const importPaletteForm = document.getElementById("import_palette_form");
    const importFileInput = document.getElementById("import_file_input");
    const importTextArea = document.getElementById("import_text_area");

    let toastTimer = null;

    // -------------------------------------------------------------------------
    // Color Math & WCAG 2.1 Contrast Utilities
    // -------------------------------------------------------------------------

    function hexToRgb(hex) {
        const clean = hex.trim().toLowerCase();
        return [
            parseInt(clean.slice(1, 3), 16),
            parseInt(clean.slice(3, 5), 16),
            parseInt(clean.slice(5, 7), 16)
        ];
    }

    function rgbToHex(r, g, b) {
        const clamp = function (n) {
            return Math.max(0, Math.min(255, Math.round(n)));
        };
        const toHex = function (n) {
            return clamp(n).toString(16).padStart(2, "0");
        };
        return "#" + toHex(r) + toHex(g) + toHex(b);
    }

    function hexToHsl(hex) {
        const rgb = hexToRgb(hex);
        const r = rgb[0] / 255;
        const g = rgb[1] / 255;
        const b = rgb[2] / 255;

        const max = Math.max(r, g, b);
        const min = Math.min(r, g, b);
        let h = 0;
        let s = 0;
        const l = (max + min) / 2;

        if (max !== min) {
            const d = max - min;
            s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
            switch (max) {
                case r:
                    h = (g - b) / d + (g < b ? 6 : 0);
                    break;
                case g:
                    h = (b - r) / d + 2;
                    break;
                case b:
                    h = (r - g) / d + 4;
                    break;
            }
            h /= 6;
        }
        return [h * 360, s * 100, l * 100];
    }

    function hslToHex(h, s, l) {
        const normH = (((h % 360) + 360) % 360) / 360;
        const normS = Math.max(0, Math.min(100, s)) / 100;
        const normL = Math.max(0, Math.min(100, l)) / 100;

        if (normS === 0) {
            const gray = Math.round(normL * 255);
            return rgbToHex(gray, gray, gray);
        }

        const hue2rgb = function (p, q, t) {
            let tt = t;
            if (tt < 0) tt += 1;
            if (tt > 1) tt -= 1;
            if (tt < 1 / 6) return p + (q - p) * 6 * tt;
            if (tt < 1 / 2) return q;
            if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
            return p;
        };

        const q = normL < 0.5 ? normL * (1 + normS) : normL + normS - normL * normS;
        const p = 2 * normL - q;
        const r = hue2rgb(p, q, normH + 1 / 3) * 255;
        const g = hue2rgb(p, q, normH) * 255;
        const b = hue2rgb(p, q, normH - 1 / 3) * 255;
        return rgbToHex(r, g, b);
    }

    function computeRelativeLuminance(hex) {
        const rgb = hexToRgb(hex);
        const lin = rgb.map(function (c) {
            const s = c / 255;
            return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
    }

    function computeContrastRatio(hexA, hexB) {
        const lumA = computeRelativeLuminance(hexA);
        const lumB = computeRelativeLuminance(hexB);
        const lighter = Math.max(lumA, lumB);
        const darker = Math.min(lumA, lumB);
        return (lighter + 0.05) / (darker + 0.05);
    }

    function resolveEffectiveColorScheme(values) {
        if (colorSchemeMode === "dark" || colorSchemeMode === "light") {
            return colorSchemeMode;
        }
        const bgHex = values["--color-bg"] || "#0b132b";
        return computeRelativeLuminance(bgHex) > 0.35 ? "light" : "dark";
    }

    // -------------------------------------------------------------------------
    // Same-Origin Iframe Constructable Stylesheet Injection (60fps, Zero Inline CSS)
    // -------------------------------------------------------------------------

    let iframePaletteSheet = null;
    let iframeInspectorSheet = null;

    function ensureIframeSheets() {
        if (!previewIframe || !previewIframe.contentDocument) return null;
        const doc = previewIframe.contentDocument;
        const win = previewIframe.contentWindow;
        if (!win || typeof win.CSSStyleSheet === "undefined") return null;

        try {
            if (!iframePaletteSheet || iframePaletteSheet._ownerDoc !== doc) {
                iframePaletteSheet = new win.CSSStyleSheet();
                iframePaletteSheet._ownerDoc = doc;
                iframeInspectorSheet = new win.CSSStyleSheet();
                iframeInspectorSheet._ownerDoc = doc;
                doc.adoptedStyleSheets = [].concat(
                    Array.from(doc.adoptedStyleSheets || []),
                    [iframePaletteSheet, iframeInspectorSheet]
                );
            }
            return {
                doc: doc,
                paletteSheet: iframePaletteSheet,
                inspectorSheet: iframeInspectorSheet
            };
        } catch (_err) {
            return null;
        }
    }

    function buildRootVariablesCssText(values) {
        const scheme = isComparingBefore
            ? savedColorScheme
            : resolveEffectiveColorScheme(values);
        const lines = ["  color-scheme: " + scheme + ";"];
        Object.keys(values).forEach(function (tokenName) {
            lines.push("  " + tokenName + ": " + values[tokenName] + ";");
        });
        return ":root {\n" + lines.join("\n") + "\n}";
    }

    function applyLivePaletteToPreview() {
        const sheets = ensureIframeSheets();
        if (!sheets) return;
        const activeValues = isComparingBefore ? savedValues : currentValues;
        const cssText = buildRootVariablesCssText(activeValues);
        sheets.paletteSheet.replaceSync(cssText);
    }

    function highlightTokenInPreview(tokenName) {
        const sheets = ensureIframeSheets();
        if (!sheets) return;
        if (!tokenName) {
            sheets.inspectorSheet.replaceSync(
                "[data-ed-inspect-hover='true'] { outline: 3px dashed var(--color-accent) !important; outline-offset: 2px !important; cursor: crosshair !important; }"
            );
            return;
        }

        const selectors = [
            "[data-tokens~='" + tokenName + "']"
        ];
        const cssSelectors = tokenSelectorsMap[tokenName] || [];
        cssSelectors.forEach(function (sel) {
            // Strip pseudo-elements/states that could prevent resting element highlight
            const baseSel = sel
                .replace(/::[a-zA-Z-]+/g, "")
                .replace(/:(hover|focus|focus-visible|active)\b/g, "")
                .trim();
            if (baseSel && !baseSel.startsWith("@") && baseSel !== "body" && baseSel !== ":root") {
                selectors.push(baseSel);
            }
        });

        const combinedSelector = selectors.join(",\n");
        const rule =
            combinedSelector +
            " {\n" +
            "  outline: 3px solid var(--color-accent) !important;\n" +
            "  outline-offset: 2px !important;\n" +
            "  box-shadow: 0 0 0 5px color-mix(in srgb, var(--color-accent) 30%, transparent) !important;\n" +
            "  transition: outline 0.12s ease !important;\n" +
            "}";
        try {
            sheets.inspectorSheet.replaceSync(rule);
        } catch (_err) {
            sheets.inspectorSheet.replaceSync(
                "[data-tokens~='" + tokenName + "'] { outline: 3px solid var(--color-accent) !important; outline-offset: 2px !important; }"
            );
        }
    }

    // -------------------------------------------------------------------------
    // Bidirectional Element -> Token Inspector inside Preview Iframe
    // -------------------------------------------------------------------------

    let lastHoveredPreviewEl = null;

    function clearHoveredPreviewEl() {
        if (lastHoveredPreviewEl) {
            lastHoveredPreviewEl.removeAttribute("data-ed-inspect-hover");
            lastHoveredPreviewEl = null;
        }
    }

    function detectTokensForElement(el, doc) {
        const detected = new Set();

        // 1. Explicit data-tokens on the element or its closest semantic ancestors
        let cur = el;
        let depth = 0;
        while (cur && cur !== doc.documentElement && depth < 4) {
            const attr = cur.getAttribute && cur.getAttribute("data-tokens");
            if (attr) {
                attr.split(/\s+/).forEach(function (t) {
                    if (t.startsWith("--color-")) detected.add(t);
                });
            }
            cur = cur.parentElement;
            depth += 1;
        }

        // 2. Match against extracted style.css selectors for each token
        Object.keys(tokenSelectorsMap).forEach(function (tokenName) {
            const selList = tokenSelectorsMap[tokenName] || [];
            for (let i = 0; i < selList.length; i += 1) {
                const cleanSel = selList[i]
                    .replace(/::[a-zA-Z-]+/g, "")
                    .replace(/:(hover|focus|focus-visible|active)\b/g, "")
                    .trim();
                if (!cleanSel || cleanSel === "body" || cleanSel === ":root") continue;
                try {
                    if (el.matches(cleanSel) || el.closest(cleanSel)) {
                        detected.add(tokenName);
                        break;
                    }
                } catch (_err) {
                    // Ignore complex pseudo selectors
                }
            }
        });

        if (detected.size === 0) {
            detected.add("--color-bg");
            detected.add("--color-text");
        }
        return detected;
    }

    function attachIframeInspectorListeners() {
        if (!previewIframe || !previewIframe.contentDocument) return;
        const doc = previewIframe.contentDocument;

        doc.addEventListener(
            "mouseover",
            function (e) {
                if (!isInspectMode) return;
                const target = e.target;
                if (!target || target === doc.body || target === doc.documentElement) return;
                clearHoveredPreviewEl();
                lastHoveredPreviewEl = target;
                target.setAttribute("data-ed-inspect-hover", "true");
            },
            true
        );

        doc.addEventListener(
            "mouseout",
            function () {
                if (!isInspectMode) return;
                clearHoveredPreviewEl();
            },
            true
        );

        doc.addEventListener(
            "click",
            function (e) {
                if (!isInspectMode) return;
                e.preventDefault();
                e.stopPropagation();

                const target = e.target;
                if (!target) return;

                const matchedTokens = detectTokensForElement(target, doc);
                inspectedTokenFilter = matchedTokens;
                applyTokenSearchFilter();

                const firstToken = Array.from(matchedTokens)[0];
                if (firstToken) {
                    const rowEl = document.getElementById("row_" + firstToken);
                    if (rowEl) {
                        rowEl.scrollIntoView({ behavior: "smooth", block: "center" });
                    }
                }
                showToast(
                    "Inspeccionado <" +
                        target.tagName.toLowerCase() +
                        ">: " +
                        matchedTokens.size +
                        " tokens relacionados",
                    false
                );
            },
            true
        );
    }

    // -------------------------------------------------------------------------
    // UI Synchronization: Controls, Dirty State, History, & Contrast Panel
    // -------------------------------------------------------------------------

    function isPaletteDirty() {
        const keys = Object.keys(currentValues);
        for (let i = 0; i < keys.length; i += 1) {
            const k = keys[i];
            if (currentValues[k] !== savedValues[k]) return true;
        }
        return false;
    }

    function pushUndoSnapshot() {
        const snapshot = Object.assign({}, currentValues);
        undoStack.push(snapshot);
        if (undoStack.length > MAX_HISTORY) {
            undoStack.shift();
        }
        redoStack.length = 0;
        updateHistoryButtons();
    }

    function updateHistoryButtons() {
        if (btnUndo) btnUndo.disabled = undoStack.length === 0;
        if (btnRedo) btnRedo.disabled = redoStack.length === 0;
        const dirty = isPaletteDirty();
        if (btnResetSaved) btnResetSaved.disabled = !dirty;
        if (unsavedBadge) unsavedBadge.hidden = !dirty;
    }

    function syncSidebarInputsFromState() {
        Object.keys(currentValues).forEach(function (tokenName) {
            const val = currentValues[tokenName];
            const isModified = val !== savedValues[tokenName];

            const picker = document.getElementById("picker_" + tokenName);
            if (picker && picker.value !== val) {
                picker.value = val;
            }

            const hexInput = document.getElementById("hex_" + tokenName);
            if (hexInput && document.activeElement !== hexInput) {
                hexInput.value = val;
                hexInput.classList.remove("is-invalid");
            }

            const dot = document.querySelector("[data-modified-for='" + tokenName + "']");
            if (dot) dot.hidden = !isModified;

            const resetBtn = document.querySelector("[data-reset-token='" + tokenName + "']");
            if (resetBtn) resetBtn.hidden = !isModified;
        });

        updateHistoryButtons();
        renderContrastPanel();
        applyLivePaletteToPreview();
    }

    function renderContrastPanel() {
        if (!contrastChecksList) return;
        const activeValues = isComparingBefore ? savedValues : currentValues;

        let passCount = 0;
        let totalCount = 0;
        const itemsHtml = [];

        contrastPairs.forEach(function (pair) {
            const fgHex = activeValues[pair.fg];
            const bgHex = activeValues[pair.bg];
            if (!fgHex || !bgHex) return;

            totalCount += 1;
            const ratio = computeContrastRatio(fgHex, bgHex);
            const minRatio = pair.min_ratio || 4.5;
            const passesAa = ratio >= minRatio;
            const aaaThreshold = minRatio >= 4.5 ? 7.0 : 4.5;
            const passesAaa = ratio >= aaaThreshold;

            let level = "FAIL";
            let badgeClass = "contrast-badge contrast-badge-fail";
            let badgeIcon = "⚠";

            if (passesAaa) {
                level = "AAA";
                badgeClass = "contrast-badge contrast-badge-aaa";
                badgeIcon = "✓";
                passCount += 1;
            } else if (passesAa) {
                level = "AA";
                badgeClass = "contrast-badge contrast-badge-aa";
                badgeIcon = "✓";
                passCount += 1;
            }

            itemsHtml.push(
                '<div class="contrast-item" data-fg="' +
                    pair.fg +
                    '" data-bg="' +
                    pair.bg +
                    '" title="Clic para ir a ' +
                    pair.fg +
                    " y " +
                    pair.bg +
                    '">' +
                    '<div class="contrast-item-left">' +
                    '<div class="contrast-swatches">' +
                    '<input type="color" class="contrast-swatch" value="' +
                    fgHex +
                    '" disabled aria-label="Color texto ' +
                    pair.fg +
                    '">' +
                    '<input type="color" class="contrast-swatch" value="' +
                    bgHex +
                    '" disabled aria-label="Color fondo ' +
                    pair.bg +
                    '">' +
                    "</div>" +
                    '<div class="contrast-pair-info">' +
                    '<span class="contrast-pair-label">' +
                    pair.label +
                    "</span>" +
                    '<span class="contrast-pair-tokens">' +
                    pair.fg.replace("--color-", "") +
                    " / " +
                    pair.bg.replace("--color-", "") +
                    "</span>" +
                    "</div>" +
                    "</div>" +
                    '<span class="' +
                    badgeClass +
                    '">' +
                    badgeIcon +
                    " " +
                    ratio.toFixed(1) +
                    ":1 " +
                    level +
                    "</span>" +
                    "</div>"
            );
        });

        contrastChecksList.innerHTML = itemsHtml.join("");

        if (contrastSummaryBadge) {
            contrastSummaryBadge.textContent =
                passCount + "/" + totalCount + " pares cumplen AA";
        }
    }

    // -------------------------------------------------------------------------
    // Filtering & Search
    // -------------------------------------------------------------------------

    function applyTokenSearchFilter() {
        const query = (tokenFilterInput ? tokenFilterInput.value : "").trim().toLowerCase();
        if (btnClearFilter) {
            btnClearFilter.hidden = query.length === 0 && !inspectedTokenFilter;
        }
        if (inspectActiveBanner) {
            inspectActiveBanner.hidden = !isInspectMode && !inspectedTokenFilter;
        }

        const groups = document.querySelectorAll(".token-group");
        groups.forEach(function (groupEl) {
            const rows = groupEl.querySelectorAll(".token-row");
            let visibleInGroup = 0;

            rows.forEach(function (row) {
                const tokenName = row.getAttribute("data-token") || "";
                const searchBlob = row.getAttribute("data-search") || "";
                const matchesQuery = !query || searchBlob.indexOf(query) !== -1;
                const matchesInspect =
                    !inspectedTokenFilter || inspectedTokenFilter.has(tokenName);

                const isVisible = matchesQuery && matchesInspect;
                row.hidden = !isVisible;
                row.classList.toggle(
                    "is-inspected",
                    Boolean(inspectedTokenFilter && inspectedTokenFilter.has(tokenName))
                );
                if (isVisible) visibleInGroup += 1;
            });

            groupEl.hidden = visibleInGroup === 0;
            if (visibleInGroup > 0 && (query || inspectedTokenFilter)) {
                groupEl.open = true;
            }
        });
    }

    // -------------------------------------------------------------------------
    // Toast Helper
    // -------------------------------------------------------------------------

    function showToast(message, isError) {
        if (!statusToast || !statusToastText) return;
        statusToastText.textContent = message;
        statusToast.classList.toggle("is-error", Boolean(isError));
        if (statusToastIcon) {
            statusToastIcon.textContent = isError ? "⚠" : "✔";
        }
        statusToast.hidden = false;

        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            statusToast.hidden = true;
        }, 4000);
    }

    if (statusToastClose) {
        statusToastClose.addEventListener("click", function () {
            statusToast.hidden = true;
        });
    }

    // -------------------------------------------------------------------------
    // Event Listeners: Token Pickers, Hex Inputs, Reset & Hover Highlighting
    // -------------------------------------------------------------------------

    document.querySelectorAll(".token-color-picker").forEach(function (picker) {
        const tokenName = picker.getAttribute("data-token");
        let pushedForDrag = false;

        picker.addEventListener("pointerdown", function () {
            pushedForDrag = false;
        });

        picker.addEventListener("input", function () {
            if (!tokenName) return;
            const newVal = picker.value.trim().toLowerCase();
            if (!HEX_RE.test(newVal)) return;
            if (!pushedForDrag) {
                pushUndoSnapshot();
                pushedForDrag = true;
            }
            if (isComparingBefore) {
                isComparingBefore = false;
                if (btnCompareToggle) btnCompareToggle.setAttribute("aria-pressed", "false");
            }
            currentValues[tokenName] = newVal;
            syncSidebarInputsFromState();
        });

        picker.addEventListener("change", function () {
            pushedForDrag = false;
        });
    });

    document.querySelectorAll(".token-hex-input").forEach(function (hexInput) {
        const tokenName = hexInput.getAttribute("data-token");

        hexInput.addEventListener("input", function () {
            if (!tokenName) return;
            let raw = hexInput.value.trim().toLowerCase();
            if (raw.length === 6 && /^[0-9a-f]{6}$/.test(raw)) {
                raw = "#" + raw;
            }
            if (HEX_RE.test(raw)) {
                hexInput.classList.remove("is-invalid");
                if (currentValues[tokenName] !== raw) {
                    pushUndoSnapshot();
                    currentValues[tokenName] = raw;
                    syncSidebarInputsFromState();
                }
            } else {
                hexInput.classList.add("is-invalid");
            }
        });

        hexInput.addEventListener("blur", function () {
            if (!tokenName) return;
            hexInput.classList.remove("is-invalid");
            hexInput.value = currentValues[tokenName];
        });
    });

    document.querySelectorAll(".btn-token-reset").forEach(function (btn) {
        btn.addEventListener("click", function () {
            const tokenName = btn.getAttribute("data-reset-token");
            if (!tokenName || currentValues[tokenName] === savedValues[tokenName]) return;
            pushUndoSnapshot();
            currentValues[tokenName] = savedValues[tokenName];
            syncSidebarInputsFromState();
        });
    });

    // Hovering a token row highlights affected elements in the preview
    document.querySelectorAll(".token-row").forEach(function (row) {
        const tokenName = row.getAttribute("data-token");
        row.addEventListener("mouseenter", function () {
            highlightTokenInPreview(tokenName);
            if (previewHoverHint && tokenName) {
                previewHoverHint.textContent = "Resaltando en vista previa: " + tokenName;
            }
        });
        row.addEventListener("mouseleave", function () {
            highlightTokenInPreview(null);
            if (previewHoverHint) {
                previewHoverHint.textContent =
                    "Pasá el cursor sobre un token para resaltar dónde se usa";
            }
        });
    });

    // Clicking a contrast item highlights and scrolls to its foreground token
    if (contrastChecksList) {
        contrastChecksList.addEventListener("click", function (e) {
            const item = e.target.closest(".contrast-item");
            if (!item) return;
            const fg = item.getAttribute("data-fg");
            const bg = item.getAttribute("data-bg");
            if (fg) {
                highlightTokenInPreview(fg);
                const row = document.getElementById("row_" + fg);
                if (row) {
                    const details = row.closest("details.token-group");
                    if (details) details.open = true;
                    row.scrollIntoView({ behavior: "smooth", block: "center" });
                }
                showToast("Par de contraste: " + fg + " sobre " + bg, false);
            }
        });
    }

    // -------------------------------------------------------------------------
    // Group HSL Batch Sliders
    // -------------------------------------------------------------------------

    document.querySelectorAll(".group-hsl-panel").forEach(function (panel) {
        const groupId = panel.getAttribute("data-hsl-group");
        if (!groupId) return;

        const sliders = panel.querySelectorAll(".hsl-slider");
        const applyBtn = panel.querySelector(".btn-hsl-apply");
        const cancelBtn = panel.querySelector(".btn-hsl-cancel");

        function resetSlidersUi() {
            sliders.forEach(function (sl) {
                sl.value = "0";
                const channel = sl.getAttribute("data-hsl-channel");
                const out = sl.parentElement.querySelector(".hsl-output");
                if (out) {
                    out.textContent = channel === "h" ? "0°" : "0%";
                }
            });
            delete hslBaseSnapshots[groupId];
        }

        sliders.forEach(function (slider) {
            slider.addEventListener("input", function () {
                if (!hslBaseSnapshots[groupId]) {
                    const snap = {};
                    (groupTokensMap[groupId] || []).forEach(function (tName) {
                        snap[tName] = currentValues[tName];
                    });
                    hslBaseSnapshots[groupId] = snap;
                }

                let dH = 0;
                let dS = 0;
                let dL = 0;
                sliders.forEach(function (sl) {
                    const ch = sl.getAttribute("data-hsl-channel");
                    const val = parseFloat(sl.value || "0");
                    const out = sl.parentElement.querySelector(".hsl-output");
                    const sign = val > 0 ? "+" : "";
                    if (ch === "h") {
                        dH = val;
                        if (out) out.textContent = sign + val + "°";
                    } else if (ch === "s") {
                        dS = val;
                        if (out) out.textContent = sign + val + "%";
                    } else if (ch === "l") {
                        dL = val;
                        if (out) out.textContent = sign + val + "%";
                    }
                });

                const baseSnap = hslBaseSnapshots[groupId];
                Object.keys(baseSnap).forEach(function (tName) {
                    const hsl = hexToHsl(baseSnap[tName]);
                    currentValues[tName] = hslToHex(
                        hsl[0] + dH,
                        hsl[1] + dS,
                        hsl[2] + dL
                    );
                });
                syncSidebarInputsFromState();
            });
        });

        if (applyBtn) {
            applyBtn.addEventListener("click", function () {
                if (hslBaseSnapshots[groupId]) {
                    undoStack.push(Object.assign({}, currentValues, hslBaseSnapshots[groupId]));
                    redoStack.length = 0;
                    resetSlidersUi();
                    updateHistoryButtons();
                    showToast("Ajuste HSL aplicado al grupo", false);
                }
            });
        }

        if (cancelBtn) {
            cancelBtn.addEventListener("click", function () {
                if (hslBaseSnapshots[groupId]) {
                    Object.assign(currentValues, hslBaseSnapshots[groupId]);
                    resetSlidersUi();
                    syncSidebarInputsFromState();
                }
            });
        }
    });

    // -------------------------------------------------------------------------
    // Topbar & Sidebar Global Controls
    // -------------------------------------------------------------------------

    if (previewRouteSelect && previewIframe) {
        previewRouteSelect.addEventListener("change", function () {
            const targetUrl = previewRouteSelect.value;
            previewIframe.src = targetUrl;
            if (previewCurrentUrl) previewCurrentUrl.textContent = targetUrl;
        });
    }

    if (btnReloadPreview && previewIframe) {
        btnReloadPreview.addEventListener("click", function () {
            if (previewIframe.contentWindow) {
                previewIframe.contentWindow.location.reload();
            }
        });
    }

    if (previewIframe) {
        previewIframe.addEventListener("load", function () {
            iframePaletteSheet = null;
            iframeInspectorSheet = null;
            applyLivePaletteToPreview();
            highlightTokenInPreview(null);
            attachIframeInspectorListeners();
            try {
                if (previewCurrentUrl && previewIframe.contentWindow) {
                    previewCurrentUrl.textContent =
                        previewIframe.contentWindow.location.pathname +
                        previewIframe.contentWindow.location.search;
                }
            } catch (_err) {
                // Keep existing path pill
            }
        });
    }

    if (tokenFilterInput) {
        tokenFilterInput.addEventListener("input", applyTokenSearchFilter);
    }

    if (btnClearFilter) {
        btnClearFilter.addEventListener("click", function () {
            if (tokenFilterInput) tokenFilterInput.value = "";
            inspectedTokenFilter = null;
            applyTokenSearchFilter();
        });
    }

    if (inspectModeToggle) {
        inspectModeToggle.addEventListener("change", function () {
            isInspectMode = inspectModeToggle.checked;
            if (!isInspectMode) {
                clearHoveredPreviewEl();
            }
            highlightTokenInPreview(null);
            if (inspectActiveBanner) {
                inspectActiveBanner.hidden = !isInspectMode && !inspectedTokenFilter;
            }
        });
    }

    if (btnShowAllTokens) {
        btnShowAllTokens.addEventListener("click", function () {
            inspectedTokenFilter = null;
            if (inspectModeToggle) inspectModeToggle.checked = false;
            isInspectMode = false;
            clearHoveredPreviewEl();
            applyTokenSearchFilter();
        });
    }

    if (colorSchemeSelect) {
        colorSchemeSelect.addEventListener("change", function () {
            colorSchemeMode = colorSchemeSelect.value;
            applyLivePaletteToPreview();
        });
    }

    if (btnToggleAllGroups) {
        btnToggleAllGroups.addEventListener("click", function () {
            const isExpanded = btnToggleAllGroups.getAttribute("aria-expanded") === "true";
            const nextOpen = !isExpanded;
            document.querySelectorAll("details.token-group").forEach(function (d) {
                d.open = nextOpen;
            });
            btnToggleAllGroups.setAttribute("aria-expanded", String(nextOpen));
            btnToggleAllGroups.textContent = nextOpen ? "Contraer grupos" : "Expandir grupos";
        });
    }

    // Undo / Redo / Compare / Reset
    function performUndo() {
        if (undoStack.length === 0) return;
        redoStack.push(Object.assign({}, currentValues));
        currentValues = undoStack.pop();
        syncSidebarInputsFromState();
    }

    function performRedo() {
        if (redoStack.length === 0) return;
        undoStack.push(Object.assign({}, currentValues));
        currentValues = redoStack.pop();
        syncSidebarInputsFromState();
    }

    if (btnUndo) btnUndo.addEventListener("click", performUndo);
    if (btnRedo) btnRedo.addEventListener("click", performRedo);

    document.addEventListener("keydown", function (e) {
        if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z") {
            if (document.activeElement && document.activeElement.tagName === "INPUT") return;
            e.preventDefault();
            performUndo();
        } else if (
            ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") ||
            ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "z")
        ) {
            if (document.activeElement && document.activeElement.tagName === "INPUT") return;
            e.preventDefault();
            performRedo();
        }
    });

    if (btnCompareToggle) {
        btnCompareToggle.addEventListener("click", function () {
            isComparingBefore = !isComparingBefore;
            btnCompareToggle.setAttribute("aria-pressed", String(isComparingBefore));
            btnCompareToggle.textContent = isComparingBefore
                ? "👁️ Viendo Original (Antes)"
                : "👁️ Antes / Después";
            applyLivePaletteToPreview();
            renderContrastPanel();
        });
    }

    if (btnResetSaved) {
        btnResetSaved.addEventListener("click", function () {
            if (!isPaletteDirty()) return;
            pushUndoSnapshot();
            currentValues = Object.assign({}, savedValues);
            isComparingBefore = false;
            if (btnCompareToggle) {
                btnCompareToggle.setAttribute("aria-pressed", "false");
                btnCompareToggle.textContent = "👁️ Antes / Después";
            }
            syncSidebarInputsFromState();
            showToast("Paleta restaurada a los valores guardados en style.css", false);
        });
    }

    // -------------------------------------------------------------------------
    // Presets, Direct Save to style.css, Export & Import
    // -------------------------------------------------------------------------

    if (presetSelect) {
        presetSelect.addEventListener("change", function () {
            const slug = presetSelect.value;
            if (!slug || !presetsMap[slug]) {
                if (btnDeletePreset) btnDeletePreset.hidden = true;
                return;
            }
            const preset = presetsMap[slug];
            if (btnDeletePreset) {
                btnDeletePreset.hidden = Boolean(preset.builtin);
            }
            pushUndoSnapshot();
            currentValues = Object.assign({}, preset.tokens);
            if (colorSchemeSelect && preset.color_scheme) {
                colorSchemeMode = preset.color_scheme;
                colorSchemeSelect.value = preset.color_scheme;
            }
            syncSidebarInputsFromState();
            showToast("Preset aplicado: " + preset.name, false);
        });
    }

    // Dialog light-dismiss fallback where closedBy is not natively supported
    if (typeof HTMLDialogElement !== "undefined" && !("closedBy" in HTMLDialogElement.prototype)) {
        const isOutsideDialog = function (e, dialog) {
            const r = dialog.getBoundingClientRect();
            return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
        };
        document.querySelectorAll('dialog[closedby="any"]').forEach(function (dialog) {
            let pressedOutside = false;
            dialog.addEventListener("pointerdown", function (e) {
                pressedOutside = isOutsideDialog(e, dialog);
            });
            dialog.addEventListener("pointerup", function (e) {
                if (pressedOutside && isOutsideDialog(e, dialog)) dialog.close();
            });
        });
    }

    if (btnOpenSavePreset && savePresetDialog) {
        btnOpenSavePreset.addEventListener("click", function () {
            if (presetNameInput) presetNameInput.value = "";
            if (presetDescInput) presetDescInput.value = "";
            savePresetDialog.returnValue = "";
            savePresetDialog.showModal();
        });

        savePresetDialog.addEventListener("close", function () {
            const action = savePresetDialog.returnValue;
            savePresetDialog.returnValue = "";
            if (action !== "save") return;

            const name = (presetNameInput ? presetNameInput.value : "").trim();
            const description = (presetDescInput ? presetDescInput.value : "").trim();
            if (!name) return;

            fetch("/api/presets", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: name,
                    description: description,
                    color_scheme: resolveEffectiveColorScheme(currentValues),
                    tokens: currentValues
                })
            })
                .then(function (r) {
                    return r.json().then(function (data) {
                        if (!r.ok) throw new Error(data.error || "Error al guardar preset");
                        return data;
                    });
                })
                .then(function (data) {
                    const preset = data.preset;
                    presetsMap[preset.slug] = preset;
                    if (presetSelect) {
                        let opt = presetSelect.querySelector('option[value="' + preset.slug + '"]');
                        if (!opt) {
                            opt = document.createElement("option");
                            opt.value = preset.slug;
                            presetSelect.appendChild(opt);
                        }
                        opt.textContent = "👤 " + preset.name;
                        presetSelect.value = preset.slug;
                    }
                    if (btnDeletePreset) btnDeletePreset.hidden = false;
                    showToast("Preset guardado: " + preset.name, false);
                })
                .catch(function (err) {
                    showToast(err.message, true);
                });
        });
    }

    if (btnDeletePreset && presetSelect) {
        btnDeletePreset.addEventListener("click", function () {
            const slug = presetSelect.value;
            const preset = presetsMap[slug];
            if (!slug || !preset || preset.builtin) return;

            fetch("/api/presets/" + encodeURIComponent(slug), {
                method: "DELETE"
            })
                .then(function (r) {
                    return r.json().then(function (data) {
                        if (!r.ok) throw new Error(data.error || "No se pudo eliminar el preset");
                        return data;
                    });
                })
                .then(function () {
                    delete presetsMap[slug];
                    const opt = presetSelect.querySelector('option[value="' + slug + '"]');
                    if (opt) opt.remove();
                    presetSelect.value = "";
                    btnDeletePreset.hidden = true;
                    showToast("Preset eliminado: " + preset.name, false);
                })
                .catch(function (err) {
                    showToast(err.message, true);
                });
        });
    }

    if (btnOpenImport && importPaletteDialog) {
        btnOpenImport.addEventListener("click", function () {
            if (importFileInput) importFileInput.value = "";
            if (importTextArea) importTextArea.value = "";
            importPaletteDialog.returnValue = "";
            importPaletteDialog.showModal();
        });

        if (importFileInput && importTextArea) {
            importFileInput.addEventListener("change", function () {
                const file = importFileInput.files && importFileInput.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = function (evt) {
                    importTextArea.value = String(evt.target.result || "");
                };
                reader.readAsText(file, "utf-8");
            });
        }

        importPaletteDialog.addEventListener("close", function () {
            const action = importPaletteDialog.returnValue;
            importPaletteDialog.returnValue = "";
            if (action !== "import") return;

            const content = (importTextArea ? importTextArea.value : "").trim();
            if (!content) return;

            fetch("/api/palette/parse-import", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content: content })
            })
                .then(function (r) {
                    return r.json().then(function (data) {
                        if (!r.ok) throw new Error(data.error || "Formato de paleta inválido");
                        return data;
                    });
                })
                .then(function (data) {
                    pushUndoSnapshot();
                    currentValues = Object.assign({}, data.tokens);
                    if (data.color_scheme && colorSchemeSelect) {
                        colorSchemeMode = data.color_scheme;
                        colorSchemeSelect.value = data.color_scheme;
                    }
                    syncSidebarInputsFromState();
                    showToast("Paleta importada exitosamente", false);
                })
                .catch(function (err) {
                    showToast(err.message, true);
                });
        });
    }

    if (btnSaveCss) {
        btnSaveCss.addEventListener("click", function () {
            btnSaveCss.disabled = true;
            fetch("/api/palette/save-css", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    color_scheme: resolveEffectiveColorScheme(currentValues),
                    tokens: currentValues
                })
            })
                .then(function (r) {
                    return r.json().then(function (data) {
                        if (!r.ok) throw new Error(data.error || "Error al guardar style.css");
                        return data;
                    });
                })
                .then(function (data) {
                    savedValues = Object.assign({}, data.palette.values);
                    savedColorScheme = data.palette.color_scheme;
                    currentValues = Object.assign({}, data.palette.values);
                    syncSidebarInputsFromState();
                    showToast("¡Guardado en style.css con respaldo automático!", false);
                })
                .catch(function (err) {
                    showToast(err.message, true);
                })
                .finally(function () {
                    btnSaveCss.disabled = false;
                });
        });
    }

    function triggerDownloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    if (btnExportCss) {
        btnExportCss.addEventListener("click", function () {
            fetch("/api/export/style.css", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    color_scheme: resolveEffectiveColorScheme(currentValues),
                    tokens: currentValues
                })
            })
                .then(function (r) {
                    if (!r.ok) throw new Error("Error al generar style.css");
                    return r.blob();
                })
                .then(function (blob) {
                    triggerDownloadBlob(blob, "style.css");
                    showToast("Descargado style.css", false);
                })
                .catch(function (err) {
                    showToast(err.message, true);
                });
        });
    }

    if (btnExportYaml) {
        btnExportYaml.addEventListener("click", function () {
            fetch("/api/export/palette.yaml", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    color_scheme: resolveEffectiveColorScheme(currentValues),
                    tokens: currentValues
                })
            })
                .then(function (r) {
                    if (!r.ok) throw new Error("Error al generar archivo YAML");
                    return r.blob();
                })
                .then(function (blob) {
                    triggerDownloadBlob(blob, "paleta_sur_en_precios.yaml");
                    showToast("Descargada paleta en formato YAML", false);
                })
                .catch(function (err) {
                    showToast(err.message, true);
                });
        });
    }

    // Initial render
    renderContrastPanel();
    updateHistoryButtons();
})();
