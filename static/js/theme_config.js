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

    // Valores por defecto (ajústalos si necesitas otro estilo base)
    const defaultLayout = {
        "data-layout": "vertical",
        "data-bs-theme": "light",
        "data-sidebar-visibility": "show",
        "data-layout-width": "fluid",
        "data-layout-position": "fixed",
        "data-topbar": "light",
        "data-sidebar-size": "lg",
        "data-layout-style": "default",
        "data-sidebar": "dark",
        "data-sidebar-image": "none",
        "data-preloader": "disable"
    };

    // ✅ 1. Aplicar configuración desde localStorage
    layoutOptions.forEach(attr => {
        const savedValue = localStorage.getItem(attr);
        if (savedValue) {
            htmlTag.setAttribute(attr, savedValue);
            const input = document.querySelector(`input[name='${attr}'][value='${savedValue}']`);
            if (input) input.checked = true;
            //console.log(`🔄 ${attr} desde localStorage:`, savedValue);
        }
    });

    // ✅ 2. Observar cambios dinámicos y guardar en localStorage
    const observer = new MutationObserver(mutations => {
        mutations.forEach(mutation => {
            const attr = mutation.attributeName;
            const value = htmlTag.getAttribute(attr);
            if (layoutOptions.includes(attr) && value) {
                localStorage.setItem(attr, value);
                //console.log(`💾 ${attr} actualizado y guardado:`, value);
            }
        });
    });

    observer.observe(htmlTag, {
        attributes: true,
        attributeFilter: layoutOptions
    });

    // ✅ 3. Alternar tema manual con botón
    document.addEventListener("DOMContentLoaded", function () {
        const toggleBtn = document.getElementById("btn-toggle-theme");
        if (toggleBtn) {
            toggleBtn.addEventListener("click", function () {
                const currentTheme = htmlTag.getAttribute("data-bs-theme") || "light";
                const newTheme = currentTheme === "light" ? "dark" : "light";
                htmlTag.setAttribute("data-bs-theme", newTheme);
                // console.log(`🌗 Tema cambiado manualmente: ${newTheme}`);
            });
        }

        // ✅ 4. Reset total del layout a valores por defecto
        const resetBtn = document.getElementById("reset-layout");
        // console.log("🧪 resetBtn encontrado:", resetBtn);
        if (resetBtn) {
            resetBtn.addEventListener("click", function () {
                layoutOptions.forEach(attr => {
                    localStorage.removeItem(attr);
                    if (defaultLayout[attr]) {
                        htmlTag.setAttribute(attr, defaultLayout[attr]);
                    } else {
                        htmlTag.removeAttribute(attr);
                    }
                });

                console.log("🔁 Layout reseteado a valores por defecto. Recargando en 150ms...");
                setTimeout(() => {
                    window.location.reload();
                }, 150);
            });
        }
    });
})();
