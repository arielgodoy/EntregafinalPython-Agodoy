(function () {
  var toastKeyToId = {
    "access.request.toast.ok": "access-request-toast-ok",
    "access.request.toast.dup": "access-request-toast-dup",
    "access.request.toast.motivo_required": "access-request-toast-motivo-required",
    "access.request.toast.error": "access-request-toast-error",
    "access.request.toast.email_failed": "access-request-toast-email-failed",
  };

  function getCookie(name) {
    var value = "; " + document.cookie;
    var parts = value.split("; " + name + "=");
    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }
    return "";
  }

  function getToastTextById(id) {
    var el = document.getElementById(id);
    if (!el) {
      return "";
    }
    return (el.textContent || "").trim();
  }

  function getToastTextForKey(key) {
    var id = toastKeyToId[key] || "access-request-toast-error";
    return getToastTextById(id);
  }

  function showToast(message, type) {
    if (!window.Toastify || !message) {
      return;
    }
    var background = "#0d6efd";
    if (type === "success") {
      background = "#28a745";
    } else if (type === "warning") {
      background = "#f59f00";
    } else if (type === "error") {
      background = "#dc3545";
    }
    Toastify({
      text: message,
      duration: 3500,
      gravity: "top",
      position: "right",
      backgroundColor: background,
      stopOnFocus: true,
    }).showToast();
  }

  function closeModal() {
    if (!window.bootstrap) {
      return;
    }
    var modalEl = document.getElementById("accessRequestModal");
    if (!modalEl) {
      return;
    }
    var modalInstance = window.bootstrap.Modal.getOrCreateInstance(modalEl);
    modalInstance.hide();
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("access-request-form");
    if (!form) {
      return;
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      var submitButton = form.querySelector("button[type='submit']");
      if (submitButton) {
        submitButton.disabled = true;
      }

      var formData = new FormData(form);
      var body = new URLSearchParams(formData);
      var csrfToken = getCookie("csrftoken");

      fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest",
          "Accept": "application/json",
        },
        body: body.toString(),
      })
        .then(function (response) {
          return response
            .json()
            .catch(function () {
              return {};
            })
            .then(function (data) {
              return { response: response, data: data };
            });
        })
        .then(function (payload) {
          var data = payload.data || {};
          var key = data.message_key || "access.request.toast.error";
          var toastMessage = getToastTextForKey(key);
          var emailFailedMessage = getToastTextForKey("access.request.toast.email_failed");

          if (!payload.response.ok || data.ok === false) {
            showToast(toastMessage, "error");
            return;
          }

          if (data.duplicate) {
            showToast(toastMessage, "warning");
            return;
          }

          if (data.email_attempted && !data.email_sent && data.email_error) {
            showToast(emailFailedMessage, "warning");
          } else {
            showToast(toastMessage, "success");
          }

          closeModal();
          setTimeout(function () {
            window.location.reload();
          }, 600);
        })
        .catch(function () {
          showToast(getToastTextForKey("access.request.toast.error"), "error");
        })
        .finally(function () {
          if (submitButton) {
            submitButton.disabled = false;
          }
        });
    });
  });
})();
