(function () {
  function getCookie(name) {
    var value = "; " + document.cookie;
    var parts = value.split("; " + name + "=");
    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }
    return "";
  }

  function fetchTopbar() {
    var dropdown = document.getElementById("notificationDropdown");
    if (!dropdown) {
      return;
    }

    var badge = document.getElementById("notification-badge");
    var loading = document.getElementById("notifications-loading");
    var emptyAll = document.getElementById("notifications-empty-all");
    var emptyMessages = document.getElementById("notifications-empty-messages");
    var emptyAlerts = document.getElementById("notifications-empty-alerts");
    var emptySystem = document.getElementById("notifications-empty-system");

    if (loading) {
      loading.style.display = "block";
    }

    fetch("/notificaciones/topbar/", { credentials: "same-origin" })
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        renderCounts(data);
        renderItems(data.items || []);
        toggleEmptyStates(data.items || []);
      })
      .catch(function () {
        if (loading) {
          loading.style.display = "none";
        }
        if (emptyAll) {
          emptyAll.style.display = "block";
        }
      });

    function renderCounts(data) {
      var count = data.unread_count_total || 0;
      if (badge) {
        badge.textContent = count > 99 ? "99+" : String(count);
        badge.style.display = count > 0 ? "inline-block" : "none";
      }
      var newCount = document.getElementById("notification-new-count");
      if (newCount) {
        newCount.textContent = String(data.unread_all || 0);
      }
      var tabAll = document.getElementById("notification-tab-all-count");
      var tabMessages = document.getElementById("notification-tab-messages-count");
      var tabAlerts = document.getElementById("notification-tab-alerts-count");
      var tabSystem = document.getElementById("notification-tab-system-count");
      if (tabAll) {
        tabAll.textContent = String(data.unread_all || 0);
      }
      if (tabMessages) {
        tabMessages.textContent = String(data.unread_messages || 0);
      }
      if (tabAlerts) {
        tabAlerts.textContent = String(data.unread_alerts || 0);
      }
      if (tabSystem) {
        tabSystem.textContent = String(data.unread_system || 0);
      }
    }

    function renderItems(items) {
      var allList = document.getElementById("notifications-list-all");
      var messageList = document.getElementById("notifications-list-messages");
      var alertList = document.getElementById("notifications-list-alerts");
      var systemList = document.getElementById("notifications-list-system");
      if (!allList || !messageList || !alertList || !systemList) {
        return;
      }

      allList.innerHTML = "";
      messageList.innerHTML = "";
      alertList.innerHTML = "";
      systemList.innerHTML = "";

      items.forEach(function (item) {
        var element = buildItem(item);
        var elementClone = element.cloneNode(true);
        var elementClone2 = element.cloneNode(true);
        var elementClone3 = element.cloneNode(true);

        allList.appendChild(element);
        if (item.tipo === "MESSAGE") {
          messageList.appendChild(elementClone);
        }
        if (item.tipo === "ALERT") {
          alertList.appendChild(elementClone2);
        }
        if (item.tipo === "SYSTEM") {
          systemList.appendChild(elementClone3);
        }
      });

      if (loading) {
        loading.style.display = "none";
      }
    }

    function buildItem(item) {
      var wrapper = document.createElement("div");
      wrapper.className = "text-reset notification-item d-block dropdown-item position-relative";
      wrapper.dataset.notificationId = item.id;
      wrapper.dataset.notificationUrl = item.url || "";

      var content = document.createElement("div");
      content.className = "d-flex";

      var iconWrap = document.createElement("div");
      iconWrap.className = "avatar-xs me-3 flex-shrink-0";

      var icon = document.createElement("span");
      icon.className = "avatar-title bg-info-subtle text-info rounded-circle fs-16";
      icon.innerHTML = "<i class=\"bx bx-bell\"></i>";
      if (item.tipo === "ALERT") {
        icon.className = "avatar-title bg-danger-subtle text-danger rounded-circle fs-16";
        icon.innerHTML = "<i class=\"bx bx-error\"></i>";
      }
      if (item.tipo === "MESSAGE") {
        icon.className = "avatar-title bg-success-subtle text-success rounded-circle fs-16";
        icon.innerHTML = "<i class=\"bx bx-message-square-dots\"></i>";
      }

      iconWrap.appendChild(icon);

      var body = document.createElement("div");
      body.className = "flex-grow-1";

      var title = document.createElement("h6");
      title.className = "mt-0 mb-1 fs-13 fw-semibold";
      title.textContent = item.titulo || "";

      var text = document.createElement("div");
      text.className = "fs-13 text-muted";
      var p = document.createElement("p");
      p.className = "mb-1";
      p.textContent = item.cuerpo || "";
      text.appendChild(p);

      body.appendChild(title);
      if (item.cuerpo) {
        body.appendChild(text);
      }

      content.appendChild(iconWrap);
      content.appendChild(body);

      wrapper.appendChild(content);

      wrapper.addEventListener("click", function () {
        markRead(item.id, item.url);
      });

      return wrapper;
    }

    function toggleEmptyStates(items) {
      if (emptyAll) {
        emptyAll.style.display = items.length ? "none" : "block";
      }
      if (emptyMessages) {
        var anyMessages = items.some(function (i) { return i.tipo === "MESSAGE"; });
        emptyMessages.style.display = anyMessages ? "none" : "block";
      }
      if (emptyAlerts) {
        var anyAlerts = items.some(function (i) { return i.tipo === "ALERT"; });
        emptyAlerts.style.display = anyAlerts ? "none" : "block";
      }
      if (emptySystem) {
        var anySystem = items.some(function (i) { return i.tipo === "SYSTEM"; });
        emptySystem.style.display = anySystem ? "none" : "block";
      }
    }

    function markRead(id, url) {
      var csrftoken = getCookie("csrftoken");
      fetch("/notificaciones/" + id + "/read/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": csrftoken,
        },
      }).then(function () {
        if (url) {
          window.location.href = url;
        }
        fetchTopbar();
      });
    }

    var markAll = document.getElementById("notifications-mark-all");
    if (markAll) {
      markAll.addEventListener("click", function () {
        var csrftoken = getCookie("csrftoken");
        fetch("/notificaciones/mark-all-read/", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": csrftoken,
          },
        }).then(function () {
          fetchTopbar();
        });
      });
    }
  }

  document.addEventListener("DOMContentLoaded", fetchTopbar);
})();
