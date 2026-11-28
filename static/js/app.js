(() => {
    "use strict";

    const onReady = (fn) => {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", fn);
        } else {
            fn();
        }
    };

    const initToasts = () => {
        document.querySelectorAll(".toast").forEach((toast) => {
            const close = () => {
                if (toast.classList.contains("is-leaving")) return;
                toast.classList.add("is-leaving");
                window.setTimeout(() => toast.remove(), 200);
            };
            const button = toast.querySelector(".toast-close");
            if (button) button.addEventListener("click", close);
            window.setTimeout(close, 5200);
        });
    };

    const initConfirms = () => {
        document.querySelectorAll("form[data-confirm]").forEach((form) => {
            form.addEventListener("submit", (event) => {
                if (!window.confirm(form.dataset.confirm)) {
                    event.preventDefault();
                }
            });
        });
    };

    const initLoadingForms = () => {
        document.querySelectorAll("form[data-loading]").forEach((form) => {
            form.addEventListener("submit", (event) => {
                const button = event.submitter || form.querySelector("[data-submit]");
                if (!button) return;
                window.setTimeout(() => {
                    button.disabled = true;
                    button.classList.add("is-loading");
                    button.dataset.originalLabel = button.textContent.trim();
                    button.textContent = form.dataset.loading || "Guardando…";
                }, 0);
            });
        });
    };

    const initStatusPolling = () => {
        const badges = Array.from(document.querySelectorAll("[data-worker-badge]"));
        const statusUrl = document.body.dataset.statusUrl;
        if (!badges.length || !statusUrl) return;

        const refresh = async () => {
            try {
                const response = await fetch(statusUrl, {
                    headers: { Accept: "application/json" },
                    credentials: "same-origin",
                });
                if (!response.ok) return;
                const data = await response.json();
                if (!data.worker) return;
                badges.forEach((badge) => {
                    badge.dataset.state = data.worker.tone || "off";
                    badge.title = data.worker.detail || "";
                    const label = badge.querySelector("[data-worker-label]");
                    if (label) label.textContent = data.worker.label || "";
                });
                document.querySelectorAll("[data-pending-count]").forEach((element) => {
                    element.textContent = data.pending;
                });
            } catch (error) {
                /* El panel sigue funcionando aunque falle el sondeo. */
            }
        };

        refresh();
        window.setInterval(refresh, 20000);
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) refresh();
        });
    };

    const parseWallDate = (value) => {
        if (!value) return null;
        const [datePart, timePart] = value.split("T");
        if (!datePart || !timePart) return null;
        const [year, month, day] = datePart.split("-").map(Number);
        const [hour, minute] = timePart.split(":").map(Number);
        if ([year, month, day, hour, minute].some(Number.isNaN)) return null;
        return new Date(Date.UTC(year, month - 1, day, hour, minute));
    };

    const toWallInput = (date) => {
        const pad = (value) => String(value).padStart(2, "0");
        return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
    };

    const formatPreviewDate = (value) => {
        const date = parseWallDate(value);
        if (!date) return "Fecha por definir";
        try {
            return new Intl.DateTimeFormat("es", {
                weekday: "short",
                day: "2-digit",
                month: "short",
                hour: "2-digit",
                minute: "2-digit",
                timeZone: "UTC",
            }).format(date);
        } catch (error) {
            return value.replace("T", " ");
        }
    };

    const initPostForm = () => {
        const form = document.querySelector("[data-post-form]");
        if (!form) return;

        const kindInputs = Array.from(form.querySelectorAll('input[name="kind"]'));
        const textInput = form.querySelector("[data-text-input]");
        const textField = form.querySelector('[data-field="text"]');
        const textLabel = form.querySelector("[data-text-label]");
        const textHelp = form.querySelector("[data-text-help]");
        const counter = form.querySelector("[data-text-counter]");
        const fileField = form.querySelector('[data-field="file"]');
        const fileInput = form.querySelector("[data-file-input]");
        const fileLabel = fileField ? fileField.querySelector("label") : null;
        const fileHelp = form.querySelector("[data-file-help]");
        const formatRow = form.querySelector('[data-field="format"]');
        const previewLinks = form.querySelector('[data-field="preview-links"]');
        const clearCheckbox = form.querySelector("#file-clear_id");
        const scheduleInput = form.querySelector("[data-schedule-input]");
        const channelSelect = form.querySelector("[data-channel-select]");
        const previewChannel = form.querySelector("[data-preview-channel]");
        const previewText = form.querySelector("[data-preview-text]");
        const previewTime = form.querySelector("[data-preview-time]");
        const previewMedia = form.querySelector("[data-preview-media]");
        const previewImage = form.querySelector("[data-preview-img]");
        const previewFile = form.querySelector("[data-preview-label]");

        if (!textInput || !kindInputs.length) return;

        let objectUrl = null;

        const getKind = () => {
            const checked = kindInputs.find((input) => input.checked);
            return checked ? checked.value : "texto";
        };

        const setPreviewImage = (url, isImage, name) => {
            if (!previewMedia) return;
            if (!url && !name) {
                previewMedia.hidden = true;
                if (previewImage) {
                    previewImage.hidden = true;
                    previewImage.removeAttribute("src");
                }
                if (previewFile) previewFile.hidden = true;
                return;
            }
            previewMedia.hidden = false;
            if (isImage && url) {
                if (previewImage) {
                    previewImage.src = url;
                    previewImage.hidden = false;
                }
                if (previewFile) previewFile.hidden = true;
            } else {
                if (previewImage) {
                    previewImage.hidden = true;
                    previewImage.removeAttribute("src");
                }
                if (previewFile) {
                    previewFile.hidden = false;
                    previewFile.textContent = name || "Archivo adjunto";
                }
            }
        };

        const updateCounter = (max) => {
            if (!counter) return;
            const length = textInput.value.length;
            counter.textContent = `${length} / ${max}`;
            counter.classList.toggle("is-over", length > max);
        };

        const update = () => {
            const kind = getKind();
            const isText = kind === "texto";
            const isPhoto = kind === "imagen";
            const isSticker = kind === "sticker";

            if (textField) textField.hidden = isSticker;
            if (fileField) fileField.hidden = isText;
            if (formatRow) formatRow.hidden = isSticker;
            if (previewLinks) previewLinks.hidden = !isText;
            textInput.disabled = isSticker;
            if (fileInput) fileInput.disabled = isText;

            let max = 4096;
            if (isPhoto) {
                max = 1024;
                if (textLabel) textLabel.textContent = "Caption (opcional)";
                if (textHelp) textHelp.textContent = "Máximo 1024 caracteres. La imagen se envía junto con este texto.";
                if (fileLabel) fileLabel.textContent = "Imagen";
                if (fileHelp) fileHelp.textContent = "JPG, PNG o WEBP · máximo 10 MB.";
                if (fileInput) fileInput.setAttribute("accept", "image/jpeg,image/png,image/webp");
            } else if (isSticker) {
                max = 0;
                if (fileLabel) fileLabel.textContent = "Sticker";
                if (fileHelp) fileHelp.textContent = "WEBP estático, TGS animado o WEBM · máximo 512 KB.";
                if (fileInput) fileInput.setAttribute("accept", ".webp,.tgs,.webm,image/webp");
            } else {
                if (textLabel) textLabel.textContent = "Texto del mensaje";
                if (textHelp) textHelp.textContent = "Puedes usar formato HTML si lo seleccionas abajo.";
                if (fileHelp) fileHelp.textContent = "";
            }

            if (isSticker) {
                if (counter) counter.textContent = "";
            } else {
                updateCounter(max);
            }

            if (previewChannel && channelSelect) {
                const option = channelSelect.options[channelSelect.selectedIndex];
                const name = option && option.value ? option.textContent.trim() : "Tu canal";
                previewChannel.textContent = name;
            }

            if (previewText) {
                let message = "";
                if (isSticker) {
                    message = "Sticker (sin texto)";
                } else if (textInput.value.trim()) {
                    message = textInput.value;
                } else {
                    message = isPhoto ? "Caption opcional…" : "Escribe el mensaje…";
                }
                previewText.textContent = message;
                previewText.classList.toggle("is-placeholder", !textInput.value.trim() || isSticker);
            }

            if (previewTime) {
                previewTime.textContent = formatPreviewDate(scheduleInput ? scheduleInput.value : "");
            }

            if (isText) {
                if (objectUrl) {
                    URL.revokeObjectURL(objectUrl);
                    objectUrl = null;
                }
                setPreviewImage("", false, "");
                return;
            }

            const file = fileInput && fileInput.files && fileInput.files[0];
            const cleared = clearCheckbox && clearCheckbox.checked;
            const existingUrl = fileInput ? fileInput.dataset.existingUrl : "";
            const existingName = fileInput ? fileInput.dataset.existingName : "";
            const existingImage = fileInput && fileInput.dataset.existingImage === "1";

            if (file) {
                const extension = file.name.split(".").pop().toLowerCase();
                const canPreview = file.type.startsWith("image/") && extension !== "tgs" && extension !== "webm";
                if (objectUrl) {
                    URL.revokeObjectURL(objectUrl);
                    objectUrl = null;
                }
                if (canPreview) {
                    objectUrl = URL.createObjectURL(file);
                    setPreviewImage(objectUrl, true, file.name);
                } else {
                    setPreviewImage("", false, file.name);
                }
            } else if (existingUrl && !cleared) {
                if (objectUrl) {
                    URL.revokeObjectURL(objectUrl);
                    objectUrl = null;
                }
                setPreviewImage(existingUrl, existingImage, existingName);
            } else {
                if (objectUrl) {
                    URL.revokeObjectURL(objectUrl);
                    objectUrl = null;
                }
                setPreviewImage("", false, "");
            }
        };

        kindInputs.forEach((input) => input.addEventListener("change", update));
        textInput.addEventListener("input", update);
        if (fileInput) fileInput.addEventListener("change", update);
        if (clearCheckbox) clearCheckbox.addEventListener("change", update);
        if (scheduleInput) scheduleInput.addEventListener("input", update);
        if (channelSelect) channelSelect.addEventListener("change", update);

        const panelNow = () => parseWallDate(form.dataset.panelNow) || parseWallDate(scheduleInput ? scheduleInput.value : "");

        form.querySelectorAll("[data-quick]").forEach((button) => {
            button.addEventListener("click", () => {
                if (!scheduleInput) return;
                const base = panelNow();
                if (!base) return;
                let target;
                if (button.dataset.quick === "1h") {
                    target = new Date(base.getTime() + 60 * 60 * 1000);
                } else if (button.dataset.quick === "3h") {
                    target = new Date(base.getTime() + 3 * 60 * 60 * 1000);
                } else {
                    target = new Date(base.getTime());
                    target.setUTCDate(target.getUTCDate() + 1);
                    target.setUTCHours(9, 0, 0, 0);
                }
                scheduleInput.value = toWallInput(target);
                update();
            });
        });

        if (scheduleInput) {
            const base = panelNow();
            if (base) scheduleInput.min = toWallInput(base);
        }

        update();
    };

    const initScheduleForm = () => {
        const form = document.querySelector("[data-schedule-form]");
        if (!form) return;

        const timeInput = form.querySelector("[data-time-input]");
        const clock = form.querySelector("[data-panel-clock]");
        const nowButton = form.querySelector("[data-use-now]");
        const allDaysButton = form.querySelector("[data-all-days]");
        const textInput = form.querySelector("[data-field='text'] textarea");
        const counter = form.querySelector("[data-schedule-counter]");
        const kindInputs = Array.from(form.querySelectorAll('input[name="kind"]'));
        const fileField = form.querySelector("[data-field='file']");
        const formatRow = form.querySelector("[data-field='format']");

        let clockDate = parseWallDate(form.dataset.panelNow);
        const pad = (value) => String(value).padStart(2, "0");
        const clockLabel = () => {
            if (!clockDate) return "--:--:--";
            return `${pad(clockDate.getUTCHours())}:${pad(clockDate.getUTCMinutes())}:${pad(clockDate.getUTCSeconds())}`;
        };
        const tick = () => {
            if (clockDate) clockDate = new Date(clockDate.getTime() + 1000);
            if (clock) clock.textContent = clockLabel();
        };

        if (clockDate) tick();
        if (clockDate) window.setInterval(tick, 1000);

        if (nowButton && timeInput) {
            nowButton.addEventListener("click", () => {
                const value = clockLabel();
                if (value.startsWith("--")) return;
                const values = timeInput.value
                    .split(",")
                    .map((item) => item.trim())
                    .filter(Boolean);
                if (!values.includes(value)) values.push(value);
                timeInput.value = values.join(", ");
                timeInput.focus();
            });
        }

        if (allDaysButton) {
            allDaysButton.addEventListener("click", () => {
                form.querySelectorAll('input[name="weekdays"]').forEach((input) => {
                    input.checked = true;
                });
            });
        }

        const updateKind = () => {
            const checked = kindInputs.find((input) => input.checked);
            const kind = checked ? checked.value : "texto";
            const isText = kind === "texto";
            const isSticker = kind === "sticker";
            if (textInput) textInput.disabled = isSticker;
            if (fileField) fileField.hidden = isText;
            if (formatRow) formatRow.hidden = isSticker;
            if (counter) {
                if (isSticker) {
                    counter.textContent = "";
                } else {
                    const max = kind === "imagen" ? 1024 : 4096;
                    counter.textContent = `${textInput ? textInput.value.length : 0} / ${max}`;
                }
            }
        };

        if (textInput) textInput.addEventListener("input", updateKind);
        kindInputs.forEach((input) => input.addEventListener("change", updateKind));
        updateKind();
    };

    onReady(() => {
        initToasts();
        initConfirms();
        initLoadingForms();
        initStatusPolling();
        initPostForm();
        initScheduleForm();
    });
})();
