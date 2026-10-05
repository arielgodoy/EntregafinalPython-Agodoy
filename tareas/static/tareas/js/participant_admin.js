document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-responsible-form]").forEach(function (form) {
        var responsible = form.querySelector('[name="responsable"]');
        var reason = form.querySelector('[name="motivo"]');
        if (!responsible || !reason) return;
        function updateRequirement() {
            reason.required = form.dataset.draft !== "true" &&
                responsible.value !== form.dataset.initialResponsible;
        }
        responsible.addEventListener("change", updateRequirement);
        updateRequirement();
    });
});
