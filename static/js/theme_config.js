
// theme_config.js

(function () {
    const htmlTag = document.documentElement;

    const layoutOptions = [
        "data-layout",
        "data-bs-theme",
        "data-sidebar-visibility",
        "data-layout-width",
        "data-layout-position",
        "data-topbar",
        "data-sidebar-size",
        "data-layout-style",
        "data-sidebar",
        "data-sidebar-image",
        "data-preloader"
    ];

    // Aplicar configuración desde localStorage
    layoutOptions.forEach(attr => {
        const savedValue = localStorage.getItem(attr);
        if (savedValue) {
            htmlTag.setAttribute(attr, savedValue);
            const input = document.querySelector(`input[name='${attr}'][value='${savedValue}']`);
            if (input) input.checked = true;
            // console.log(`🔄 ${attr} aplicado desde localStorage:`, savedValue);
        }
    });

    // Observar cambios dinámicos y guardar en localStorage
    const observer = new MutationObserver(mutations => {
        mutations.forEach(mutation => {
            const attr = mutation.attributeName;
            const value = htmlTag.getAttribute(attr);
            if (layoutOptions.includes(attr) && value) {
                localStorage.setItem(attr, value);
                //console.log(`💾 ${attr} actualizado por script y guardado:`, value);
            }
        });
    });

    observer.observe(htmlTag, {
        attributes: true,
        attributeFilter: layoutOptions
    });

    // Alternar tema manualmente con botón (si existe)
    const toggleBtn = document.getElementById("btn-toggle-theme");
    if (toggleBtn) {
        toggleBtn.addEventListener("click", function () {
            const currentTheme = htmlTag.getAttribute("data-bs-theme") || "light";
            const newTheme = currentTheme === "light" ? "dark" : "light";
            htmlTag.setAttribute("data-bs-theme", newTheme);
            console.log(`🌗 Tema cambiado manualmente: ${newTheme}`);
        });
    }

    // Botón para resetear configuración
    const resetBtn = document.getElementById("reset-layout");
    if (resetBtn) {
        resetBtn.addEventListener("click", function () {
            layoutOptions.forEach(attr => {
                localStorage.removeItem(attr);
                htmlTag.removeAttribute(attr);
            });
            console.log("🔁 Layout reseteado. Recargando...");
            window.location.reload();
        });
    }
})();
