(function () {
    function csrfToken(form) {
        var input = form.querySelector("input[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function showFeedback(element, success, message) {
        element.className = "alert mt-3 " + (success ? "alert-success" : "alert-danger");
        element.textContent = message;
    }

    function resolveMessage(key) {
        var element = document.querySelector('[data-key="' + key + '"]');
        return element ? element.textContent : "";
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".js-task-link-form").forEach(function (form) {
            form.addEventListener("submit", function (event) {
                event.preventDefault();
                var feedback = document.getElementById("task-link-feedback");
                fetch(form.action, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": csrfToken(form),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: new FormData(form),
                }).then(function (response) {
                    return response.json().then(function (data) {
                        return { ok: response.ok, data: data };
                    });
                }).then(function (result) {
                    if (!result.ok || !result.data.success) {
                        showFeedback(
                            feedback,
                            false,
                            resolveMessage(result.data.message_key || "tareas.links.create_error")
                        );
                        return;
                    }
                    showFeedback(
                        feedback,
                        true,
                        resolveMessage("tareas.links.url_created") + " " + result.data.url
                    );
                    if (navigator.clipboard && result.data.url) {
                        navigator.clipboard.writeText(result.data.url);
                    }
                }).catch(function () {
                    showFeedback(feedback, false, resolveMessage("tareas.links.create_error"));
                });
            });
        });

        document.querySelectorAll(".js-task-link-revoke").forEach(function (form) {
            form.addEventListener("submit", function (event) {
                event.preventDefault();
                fetch(form.action, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": csrfToken(form),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                }).then(function (response) {
                    return response.json();
                }).then(function (data) {
                    if (data.success) {
                        window.location.reload();
                    }
                });
            });
        });
    });
}());
