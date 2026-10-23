(() => {
    const bindForms = () => {
        document.querySelectorAll("[data-logical-restoration-form]").forEach((form) => {
            let submitted = false;
            form.addEventListener("submit", (event) => {
                if (submitted) {
                    event.preventDefault();
                    return;
                }
                submitted = true;
                const button = form.querySelector("[data-restoration-submit]");
                if (button) {
                    button.disabled = true;
                    button.setAttribute("aria-disabled", "true");
                }
            });
        });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bindForms, { once: true });
    } else {
        bindForms();
    }
})();
