(function () {
  // Medidor visual de fortaleza + checklist para el formulario de activación.
  // Es solo ayuda de UX: la validación real siempre ocurre en el backend (Django).
  // No conoce datos personales del usuario ni la lista de contraseñas comunes de Django;
  // esas validaciones son exclusivas del backend (UserAttributeSimilarityValidator, CommonPasswordValidator).

  function hasRepeatedRun(value, runLength) {
    for (var i = 0; i <= value.length - runLength; i++) {
      var chunk = value.slice(i, i + runLength);
      if (/^(.)\1*$/.test(chunk)) {
        return true;
      }
    }
    return false;
  }

  function hasSimpleSequence(value, runLength) {
    var lower = value.toLowerCase();
    for (var i = 0; i <= lower.length - runLength; i++) {
      var isAscending = true;
      var isDescending = true;
      for (var j = 0; j < runLength - 1; j++) {
        var current = lower.charCodeAt(i + j);
        var next = lower.charCodeAt(i + j + 1);
        if (next - current !== 1) isAscending = false;
        if (current - next !== 1) isDescending = false;
      }
      if (isAscending || isDescending) {
        return true;
      }
    }
    return false;
  }

  function computeScore(password) {
    if (!password) return 0;

    var score = 0;

    // Longitud: factor dominante.
    score += Math.min(password.length * 4, 48);

    // Diversidad de caracteres: suma puntos, pero ninguno es obligatorio.
    if (/[a-z]/.test(password)) score += 8;
    if (/[A-Z]/.test(password)) score += 8;
    if (/[0-9]/.test(password)) score += 8;
    if (/[^a-zA-Z0-9]/.test(password)) score += 12;

    // Variedad de caracteres únicos respecto al largo total.
    var uniqueChars = new Set(password.split("")).size;
    score += Math.min(uniqueChars * 2, 16);

    // Penalizaciones por patrones simples.
    if (hasRepeatedRun(password, 3)) score -= 20;
    if (hasSimpleSequence(password, 4)) score -= 20;
    if (/^[0-9]+$/.test(password)) score -= 15;

    return Math.max(0, Math.min(100, score));
  }

  function strengthLabel(score, meetsMinLength) {
    if (!meetsMinLength) {
      return { key: "activation.password.strength.weak", text: "Débil", cssClass: "bg-danger" };
    }
    if (score >= 70) {
      return { key: "activation.password.strength.strong", text: "Fuerte", cssClass: "bg-success" };
    }
    if (score >= 40) {
      return { key: "activation.password.strength.medium", text: "Media", cssClass: "bg-warning" };
    }
    return { key: "activation.password.strength.weak", text: "Débil", cssClass: "bg-danger" };
  }

  function setChecklistState(element, met) {
    if (!element) return;
    var icon = element.querySelector(".req-icon");
    element.classList.toggle("text-success", met);
    element.classList.toggle("text-muted", !met);
    if (icon) {
      icon.textContent = met ? "●" : "○";
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("activation-form");
    var password1 = document.getElementById("id_password1");
    var password2 = document.getElementById("id_password2");
    var submitBtn = document.getElementById("activation-submit-btn");
    var strengthBar = document.getElementById("password-strength-bar");
    var strengthLabelEl = document.getElementById("password-strength-label");
    var reqMinLength = document.getElementById("req-min-length");

    if (!form || !password1 || !password2 || !submitBtn) {
      return;
    }

    var minLength = parseInt(form.getAttribute("data-password-min-length"), 10) || 12;

    function refresh() {
      var value = password1.value || "";
      var meetsMinLength = value.length >= minLength;

      setChecklistState(reqMinLength, meetsMinLength);

      var score = computeScore(value);
      var label = strengthLabel(score, meetsMinLength);

      if (strengthBar) {
        strengthBar.style.width = score + "%";
        strengthBar.className = "progress-bar " + label.cssClass;
      }
      if (strengthLabelEl) {
        strengthLabelEl.textContent = value ? label.text : "—";
        strengthLabelEl.setAttribute("data-key", value ? label.key : "activation.password.strength.empty");
      }

      var passwordsMatch = value.length > 0 && value === password2.value;
      // Deshabilitar el botón es solo UX; el backend sigue rechazando cualquier POST inválido.
      submitBtn.disabled = !(meetsMinLength && password2.value.length > 0 && passwordsMatch);
    }

    password1.addEventListener("input", refresh);
    password2.addEventListener("input", refresh);
    refresh();
  });
})();
