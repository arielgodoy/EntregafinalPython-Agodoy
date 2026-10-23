(() => {
    const initializeHierarchyForm = () => {
        const parentSelect = document.querySelector("[data-hierarchy-parent]");
        if (!parentSelect) {
            return;
        }

        const departmentGroup = document.querySelector("[data-hierarchy-department]");
        const departmentSelect = document.querySelector("#id_departamento");
        const updateSelection = (resetDepartment) => {
            const option = parentSelect.options[parentSelect.selectedIndex];
            const taskKind = option ? option.dataset.taskKind : "main";
            const parentHasDepartment = Boolean(
                option && option.dataset.scope === "DEPARTAMENTO"
            );

            document.querySelectorAll("[data-task-kind-label]").forEach((label) => {
                label.hidden = label.dataset.taskKindLabel !== taskKind;
            });
            if (departmentGroup) {
                departmentGroup.hidden = !parentHasDepartment;
            }
            if (resetDepartment && departmentSelect) {
                departmentSelect.value = parentHasDepartment
                    ? (option.dataset.departmentId || "")
                    : "";
            }
        };

        parentSelect.addEventListener("change", () => updateSelection(true));
        updateSelection(false);
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initializeHierarchyForm, {
            once: true,
        });
    } else {
        initializeHierarchyForm();
    }
})();
