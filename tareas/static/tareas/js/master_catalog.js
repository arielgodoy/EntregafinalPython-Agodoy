(function () {
    "use strict";

    const form = document.querySelector(".js-master-delete-form");
    if (!form) {
        return;
    }

    const label = form.querySelector(".js-master-delete-label");
    const error = form.querySelector(".js-master-delete-error");
    let activeRow = null;

    function messageText(key) {
        const node = document.querySelector("[data-message-key='" + key + "']");
        return node ? node.textContent.trim() : key;
    }

    function operationId() {
        if (!window.crypto || typeof window.crypto.randomUUID !== "function") {
            return "";
        }
        return window.crypto.randomUUID();
    }

    document.addEventListener("click", function (event) {
        const button = event.target.closest(".js-master-delete");
        if (!button) {
            return;
        }
        activeRow = button.closest("tr");
        form.action = button.dataset.deleteUrl;
        label.textContent = button.dataset.recordLabel || "";
        form.elements.namedItem("operation_id").value = operationId();
        error.classList.add("d-none");
        error.textContent = "";
    });

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        const csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
        const submit = form.querySelector("button[type='submit']");
        submit.disabled = true;
        try {
            const response = await fetch(form.action, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": csrf ? csrf.value : ""
                },
                body: new FormData(form)
            });
            const result = await response.json();
            if (!response.ok || !result || result.success !== true) {
                error.textContent = result && result.message_key
                    ? messageText(result.message_key)
                    : "No fue posible eliminar el registro.";
                error.classList.remove("d-none");
                return;
            }
            if (activeRow) {
                activeRow.remove();
            }
            if (window.bootstrap) {
                window.bootstrap.Modal.getOrCreateInstance(
                    document.getElementById("master-delete-modal")
                ).hide();
            }
        } catch (_error) {
            error.textContent = messageText("tareas.master_catalog.common.unavailable");
            error.classList.remove("d-none");
        } finally {
            submit.disabled = false;
        }
    });
}());
