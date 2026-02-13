(function () {
  function getCookie(name) {
    var value = "; " + document.cookie;
    var parts = value.split("; " + name + "=");
    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }
    return "";
  }

  function isValidIsoDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      return false;
    }
    var testDate = new Date(value + "T00:00:00");
    if (Number.isNaN(testDate.getTime())) {
      return false;
    }
    return testDate.toISOString().slice(0, 10) === value;
  }

  function hideMessages() {
    var invalid = document.getElementById("system-date-error-invalid");
    var server = document.getElementById("system-date-error-server");
    var success = document.getElementById("system-date-success");
    if (invalid) invalid.classList.add("d-none");
    if (server) server.classList.add("d-none");
    if (success) success.classList.add("d-none");
  }

  document.addEventListener("DOMContentLoaded", function () {
    var modalEl = document.getElementById("systemDateModal");
    var input = document.getElementById("system_date_input");
    var saveBtn = document.getElementById("system_date_save_btn");
    var trigger = document.getElementById("system-date-trigger");

    if (!modalEl || !input || !saveBtn) {
      return;
    }

    modalEl.addEventListener("show.bs.modal", function () {
      var current = input.value || (trigger ? trigger.getAttribute("data-current-date") : "");
      if (current) {
        input.value = current;
      }
      hideMessages();
    });

    saveBtn.addEventListener("click", function () {
      hideMessages();
      var value = (input.value || "").trim();

      if (!isValidIsoDate(value)) {
        var invalid = document.getElementById("system-date-error-invalid");
        if (invalid) invalid.classList.remove("d-none");
        return;
      }

      var csrftoken = getCookie("csrftoken");
      var body = new URLSearchParams();
      body.append("fecha_sistema", value);

      fetch("/settings/fecha-sistema/set/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": csrftoken,
        },
        body: body.toString(),
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("request failed");
          }
          return response.json();
        })
        .then(function (data) {
          if (data && data.ok) {
            var success = document.getElementById("system-date-success");
            if (success) success.classList.remove("d-none");
            setTimeout(function () {
              window.location.reload();
            }, 400);
            return;
          }
          var invalid = document.getElementById("system-date-error-invalid");
          if (invalid) invalid.classList.remove("d-none");
        })
        .catch(function () {
          var server = document.getElementById("system-date-error-server");
          if (server) server.classList.remove("d-none");
        });
    });
  });
})();
