!function(){
  "use strict";

  const htmlTag = document.documentElement;
  const layoutOptions = [
    "data-layout",
    "data-sidebar-size",
    "data-bs-theme",
    "data-layout-width",
    "data-sidebar",
    "data-sidebar-image",
    "data-layout-direction",
    "data-layout-position",
    "data-layout-style",
    "data-topbar",
    "data-preloader",
    "data-body-image"
  ];

  // Guardar los atributos por defecto si no están guardados
  if (!localStorage.getItem("defaultAttribute")) {
    const attrs = htmlTag.attributes;
    const defaults = {};
    for (let attr of attrs) {
      if (attr && attr.nodeName && attr.nodeValue) {
        defaults[attr.nodeName] = attr.nodeValue;
      }
    }
    localStorage.setItem("defaultAttribute", JSON.stringify(defaults));
    console.log("💾 Preferencias por defecto guardadas en localStorage:", defaults);
  }

  // Comprobar si han cambiado los atributos por defecto (opcional)
  const currentDefaults = {};
  for (let attr of htmlTag.attributes) {
    if (attr && attr.nodeName && attr.nodeValue) {
      currentDefaults[attr.nodeName] = attr.nodeValue;
    }
  }

  const storedDefaults = localStorage.getItem("defaultAttribute");

  if (storedDefaults && storedDefaults !== JSON.stringify(currentDefaults)) {
    console.warn("⚠️ Preferencias cambiaron respecto a los valores iniciales.");
    // localStorage.clear(); // Si quieres reiniciar, puedes descomentar esto
    // location.reload();
  }

  // Aplicar preferencias guardadas
  const layoutSettings = {};
  layoutOptions.forEach(attr => {
    const saved = localStorage.getItem(attr);
    if (saved) {
      layoutSettings[attr] = saved;
      htmlTag.setAttribute(attr, saved);
    }
  });

  console.log("✅ Preferencias cargadas desde localStorage:", layoutSettings);
}();
