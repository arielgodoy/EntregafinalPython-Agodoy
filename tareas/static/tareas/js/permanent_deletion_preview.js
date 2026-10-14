(function () {
    "use strict";

    const modalElement = document.getElementById("permanentDeletionPreviewModal");
    if (!modalElement || !window.bootstrap) return;

    const modal = window.bootstrap.Modal.getOrCreateInstance(modalElement);
    const fields = {
        correlativo: document.getElementById("permanentDeletionPreviewCorrelativo"),
        title: document.getElementById("permanentDeletionPreviewTaskTitle"),
        taskCount: document.getElementById("permanentDeletionPreviewTaskCount"),
        descendants: document.getElementById("permanentDeletionPreviewDescendantCount"),
        state: document.getElementById("permanentDeletionPreviewState"),
        backend: document.getElementById("permanentDeletionPreviewBackend"),
        counts: document.getElementById("permanentDeletionPreviewCounts"),
        warnings: document.getElementById("permanentDeletionPreviewWarnings"),
        shared: document.getElementById("permanentDeletionPreviewShared"),
        blockers: document.getElementById("permanentDeletionPreviewBlockers"),
        warningContainer: document.getElementById("permanentDeletionPreviewWarningsContainer"),
        sharedContainer: document.getElementById("permanentDeletionPreviewSharedContainer"),
        blockersContainer: document.getElementById("permanentDeletionPreviewBlockersContainer"),
        error: document.getElementById("permanentDeletionPreviewError"),
    };

    function clearList(element) {
        element.replaceChildren();
    }

    function appendDetail(element, value, key) {
        const item = document.createElement("li");
        const detail = document.createElement("span");
        detail.dataset.key = key;
        detail.textContent = String(value);
        item.appendChild(detail);
        element.appendChild(item);
    }

    function reset() {
        Object.values(fields).forEach((element) => {
            if (element instanceof HTMLElement && "textContent" in element) {
                if (!["counts", "warnings", "shared", "blockers", "error"].includes(element.id)) {
                    element.textContent = "—";
                }
            }
        });
        clearList(fields.counts);
        clearList(fields.warnings);
        clearList(fields.shared);
        clearList(fields.blockers);
        fields.warningContainer.classList.add("d-none");
        fields.sharedContainer.classList.add("d-none");
        fields.blockersContainer.classList.add("d-none");
        fields.error.textContent = "";
        fields.error.classList.add("d-none");
    }

    function renderMessages(element, container, messages, key) {
        clearList(element);
        (messages || []).forEach((message) => appendDetail(element, message, key));
        container.classList.toggle("d-none", !messages || messages.length === 0);
    }

    function renderPreview(preview) {
        fields.correlativo.textContent = preview.task.correlativo || "—";
        fields.title.textContent = preview.task.titulo || "—";
        fields.taskCount.textContent = String(preview.task_count);
        fields.descendants.textContent = String(preview.descendant_count);
        fields.state.textContent = preview.task.estado || "—";
        fields.backend.textContent = preview.backend || "—";

        clearList(fields.counts);
        Object.entries(preview.counts || {}).sort(([left], [right]) => left.localeCompare(right))
            .forEach(([label, count]) => {
                const item = document.createElement("li");
                item.className = "list-group-item d-flex justify-content-between align-items-center";
                const name = document.createElement("span");
                name.dataset.key = "tareas.deletion_preview.dependency_label";
                name.textContent = label;
                const value = document.createElement("span");
                value.className = "badge bg-secondary-subtle text-secondary";
                value.textContent = String(count);
                item.append(name, value);
                fields.counts.appendChild(item);
            });

        renderMessages(
            fields.warnings,
            fields.warningContainer,
            preview.warnings,
            "tareas.deletion_preview.warning_detail"
        );
        renderMessages(
            fields.shared,
            fields.sharedContainer,
            (preview.shared_references || []).map((reference) => reference.message),
            "tareas.deletion_preview.shared_detail"
        );
        renderMessages(
            fields.blockers,
            fields.blockersContainer,
            preview.blockers,
            "tareas.deletion_preview.blocker_detail"
        );
    }

    async function loadPreview(url) {
        reset();
        try {
            const response = await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers: { Accept: "application/json" },
            });
            const result = await response.json();
            if (result.preview) renderPreview(result.preview);
            if (!response.ok && !result.preview) {
                const message = response.status === 403
                    ? "No tienes permiso Supervisor para esta previsualización."
                    : response.status === 404
                        ? "La tarea no existe o no está disponible."
                        : response.status === 409
                            ? (result.blockers || ["El inventario no está completo."]).join(" ")
                            : "No se pudo generar la previsualización.";
                fields.error.dataset.key = "tareas.deletion_preview.load_error";
                fields.error.textContent = message;
                fields.error.classList.remove("d-none");
            }
        } catch (_error) {
            fields.error.dataset.key = "tareas.deletion_preview.load_error";
            fields.error.textContent = "No se pudo comunicar con el backend de tareas.";
            fields.error.classList.remove("d-none");
        }
    }

    document.querySelectorAll(".js-permanent-deletion-preview").forEach((button) => {
        button.addEventListener("click", () => {
            modal.show();
            loadPreview(button.dataset.previewUrl);
        });
    });
})();
