(function () {
    "use strict";

    const table = document.getElementById("department-catalog-table");
    const message = document.getElementById("department-catalog-message");
    if (!table || !message) {
        return;
    }

    function messageText(key) {
        const nodes = document.querySelectorAll("[data-message-key]");
        for (const node of nodes) {
            if (node.dataset.messageKey === key) {
                return node.textContent.trim();
            }
        }
        return "";
    }

    function translateDynamicLabels(root) {
        root.querySelectorAll("[data-key]").forEach(function (node) {
            const translated = messageText(node.dataset.key);
            if (translated) {
                node.textContent = translated;
            }
        });
    }

    function showMessage(key, level) {
        message.textContent = messageText(key) || messageText("tareas.master_catalog.department.unavailable");
        const alertClass = {
            success: "alert-success",
            warning: "alert-warning",
            danger: "alert-danger"
        }[level] || "alert-danger";
        message.className = "alert " + alertClass;
    }

    function newOperationId() {
        if (!window.crypto || typeof window.crypto.getRandomValues !== "function") {
            return "";
        }
        const bytes = new Uint8Array(16);
        window.crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        const hex = Array.from(bytes, function (value) {
            return value.toString(16).padStart(2, "0");
        }).join("");
        return [
            hex.slice(0, 8),
            hex.slice(8, 12),
            hex.slice(12, 16),
            hex.slice(16, 20),
            hex.slice(20)
        ].join("-");
    }

    function makeActionButton(labelKey, label, className, target) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = className;
        button.dataset.bsToggle = "modal";
        button.dataset.bsTarget = target;
        const text = document.createElement("span");
        text.dataset.key = labelKey;
        text.textContent = label;
        button.appendChild(text);
        return button;
    }

    function addRow(data) {
        const search = (document.getElementById("department-search") || {}).value || "";
        if (
            search
            && !data.codigo.toLocaleLowerCase().includes(search.toLocaleLowerCase())
            && !data.nombre.toLocaleLowerCase().includes(search.toLocaleLowerCase())
        ) {
            return;
        }

        const body = document.getElementById("department-catalog-body");
        const emptyRow = document.getElementById("department-empty-row");
        if (emptyRow) {
            emptyRow.remove();
        }

        const row = document.createElement("tr");
        row.dataset.departmentId = String(data.id);

        const code = document.createElement("td");
        code.dataset.departmentCode = "";
        code.textContent = data.codigo;
        row.appendChild(code);

        const name = document.createElement("td");
        name.dataset.departmentName = "";
        name.textContent = data.nombre;
        row.appendChild(name);

        const source = document.createElement("td");
        source.dataset.departmentSource = "";
        source.textContent = data.source;
        row.appendChild(source);

        const statusCell = document.createElement("td");
        const status = document.createElement("span");
        status.className = "badge bg-success-subtle text-success";
        status.dataset.key = "tareas.master_catalog.department.active";
        status.textContent = "Activo";
        statusCell.appendChild(status);
        row.appendChild(statusCell);

        const actions = document.createElement("td");
        actions.className = "text-nowrap";
        const detail = makeActionButton(
            "tareas.master_catalog.department.detail",
            "Detalle",
            "btn btn-sm btn-outline-secondary js-department-detail",
            "#department-detail-modal"
        );
        detail.dataset.code = data.codigo;
        detail.dataset.name = data.nombre;
        detail.dataset.source = data.source;
        detail.dataset.active = "true";
        actions.appendChild(detail);

        const edit = makeActionButton(
            "tareas.master_catalog.department.edit",
            "Editar",
            "btn btn-sm btn-outline-primary js-department-edit",
            "#department-edit-modal"
        );
        edit.dataset.url = table.dataset.editUrlTemplate.replace(
            "999999999",
            encodeURIComponent(String(data.id))
        );
        edit.dataset.code = data.codigo;
        edit.dataset.name = data.nombre;
        actions.appendChild(edit);
        row.appendChild(actions);

        body.prepend(row);
        translateDynamicLabels(row);
    }

    document.addEventListener("click", function (event) {
        const editButton = event.target.closest(".js-department-edit");
        if (editButton) {
            const form = document.querySelector("#department-edit-modal form");
            form.action = editButton.dataset.url;
            form.elements.namedItem("operation_id").value = "";
            form.elements.namedItem("nombre").value = editButton.dataset.name;
            form.elements.namedItem("motivo").value = "";
            document.getElementById("department-edit-code").value = editButton.dataset.code;
            return;
        }

        const detailButton = event.target.closest(".js-department-detail");
        if (detailButton) {
            document.getElementById("department-detail-code").textContent = detailButton.dataset.code;
            document.getElementById("department-detail-name").textContent = detailButton.dataset.name;
            document.getElementById("department-detail-source").textContent = detailButton.dataset.source;
            document.getElementById("department-detail-status").textContent = messageText(
                detailButton.dataset.active === "true"
                    ? "tareas.master_catalog.department.active"
                    : "tareas.master_catalog.department.inactive"
            );
        }
    });

    document.querySelectorAll(".js-department-mutation").forEach(function (form) {
        form.addEventListener("submit", async function (event) {
            event.preventDefault();
            const operationField = form.elements.namedItem("operation_id");
            if (!operationField.value) {
                operationField.value = newOperationId();
            }
            if (!operationField.value) {
                showMessage("tareas.master_catalog.department.unavailable", "danger");
                return;
            }

            const submit = form.querySelector('button[type="submit"]');
            const spinner = form.querySelector(".js-submit-spinner");
            submit.disabled = true;
            spinner.classList.remove("d-none");
            message.classList.add("d-none");

            try {
                let response;
                try {
                    const csrf = form.querySelector('input[name="csrfmiddlewaretoken"]');
                    response = await fetch(form.action, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: {
                            "Accept": "application/json",
                            "X-Requested-With": "XMLHttpRequest",
                            "X-CSRFToken": csrf ? csrf.value : ""
                        },
                        body: new FormData(form)
                    });
                } catch (_networkError) {
                    showMessage("tareas.master_catalog.department.operation_uncertain", "danger");
                    return;
                }

                let result;
                try {
                    result = await response.json();
                } catch (_responseError) {
                    showMessage("tareas.master_catalog.department.unavailable", "danger");
                    return;
                }
                if (!result || typeof result.success !== "boolean") {
                    showMessage("tareas.master_catalog.department.unavailable", "danger");
                    return;
                }

                const messageKey = result.message_key || "tareas.master_catalog.department.unavailable";
                const messageLevel = !result.success
                    ? "danger"
                    : (
                        messageKey === "tareas.master_catalog.department.audit_pending"
                        || messageKey === "tareas.master_catalog.department.audit_error"
                            ? "warning"
                            : "success"
                    );
                showMessage(messageKey, messageLevel);
                if (!response.ok || !result.success) {
                    return;
                }

                if (form.dataset.kind === "create") {
                    addRow(result.data);
                } else {
                    const row = table.querySelector(
                        '[data-department-id="' + String(result.data.id) + '"]'
                    );
                    if (row) {
                        row.querySelector("[data-department-name]").textContent = result.data.nombre;
                        const detailButton = row.querySelector(".js-department-detail");
                        const editButton = row.querySelector(".js-department-edit");
                        detailButton.dataset.name = result.data.nombre;
                        editButton.dataset.name = result.data.nombre;
                    }
                }

                form.reset();
                operationField.value = "";
                const modalElement = form.closest(".modal");
                if (modalElement && window.bootstrap) {
                    window.bootstrap.Modal.getOrCreateInstance(modalElement).hide();
                }
            } finally {
                submit.disabled = false;
                spinner.classList.add("d-none");
            }
        });
    });
}());
