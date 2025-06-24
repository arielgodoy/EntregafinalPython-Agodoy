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

    // ✅ 1. Aplicar configuración desde localStorage antes del render CSS
    const appliedPrefs = {};
    layoutOptions.forEach(attr => {
        const savedValue = localStorage.getItem(attr);
        if (savedValue) {
            htmlTag.setAttribute(attr, savedValue);
            appliedPrefs[attr] = savedValue;
        }
    });
    console.log("✅ Preferencias cargadas desde localStorage:", appliedPrefs);

    // ✅ 2. Observar cambios y guardar en localStorage
    const observer = new MutationObserver(mutations => {
        let storedPrefs = {};
        mutations.forEach(mutation => {
            const attr = mutation.attributeName;
            const value = htmlTag.getAttribute(attr);
            if (layoutOptions.includes(attr) && value) {
                localStorage.setItem(attr, value);
                storedPrefs[attr] = value;
            }
        });
        if (Object.keys(storedPrefs).length > 0) {
            console.log("💾 Preferencias guardadas en localStorage:", storedPrefs);
        }
    });

    observer.observe(htmlTag, {
        attributes: true,
        attributeFilter: layoutOptions
    });

    // ✅ 3. Configurar íconos y botones al cargar el DOM
    document.addEventListener("DOMContentLoaded", function () {
        const buttons = document.querySelectorAll(".btn-toggle-theme");

        buttons.forEach(btn => {
            const icon = btn.querySelector("i");

            // Establecer ícono inicial correctamente
            const currentTheme = htmlTag.getAttribute("data-bs-theme") || "light";
            if (icon) {
                icon.classList.remove("bx-moon", "bx-sun");
                icon.classList.add(currentTheme === "light" ? "bx-moon" : "bx-sun");
            }

            // Evento para cambiar tema
            btn.addEventListener("click", function () {
                const currentTheme = htmlTag.getAttribute("data-bs-theme") || "light";
                const newTheme = currentTheme === "light" ? "dark" : "light";
                htmlTag.setAttribute("data-bs-theme", newTheme);
                localStorage.setItem("data-bs-theme", newTheme);
                console.log(`🌗 Tema cambiado manualmente: ${newTheme} y guardado en localStorage`);

                if (icon) {
                    icon.classList.remove("bx-moon", "bx-sun");
                    icon.classList.add(newTheme === "light" ? "bx-moon" : "bx-sun");
                }
            });
        });

        // 🔁 Botón de reset
        const resetBtn = document.getElementById("reset-layout");
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
