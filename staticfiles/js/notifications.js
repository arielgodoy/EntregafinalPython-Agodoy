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
    var emptyState = document.getElementById("notifications-empty");
    var listContainer = document.getElementById("notifications-list");
    var loadMoreBtn = document.getElementById("notifications-load-more");
    var scrollHost = listContainer ? listContainer.closest("[data-simplebar]") : null;
    var scrollWrapper = scrollHost ? scrollHost.querySelector(".simplebar-content-wrapper") : null;
    var tabLinks = dropdown.querySelectorAll("#notificationItemsTab a[data-filter]");

    var activeTab = "ALL";
    var pageByTab = {
      ALL: 1,
      MESSAGE: 1,
      ALERT: 1,
      SYSTEM: 1,
    };
    var itemsByTab = {
      ALL: [],
      MESSAGE: [],
      ALERT: [],
      SYSTEM: [],
    };
    var hasNextByTab = {
      ALL: false,
      MESSAGE: false,
      ALERT: false,
      SYSTEM: false,
    };

    if (loading) {
      loading.style.display = "block";
    }

    function fetchTab(tab, page) {
      var url = "/notificaciones/topbar/?type=" + tab + "&page=" + page + "&page_size=10";
      if (loading) {
        loading.style.display = "block";
      }
      return fetch(url, { credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("request failed");
          }
          return response.json();
        })
        .then(function (data) {
          renderCounts(data);
          hasNextByTab[tab] = Boolean(data.has_next);
          pageByTab[tab] = data.page || page;
          if (page === 1) {
            itemsByTab[tab] = data.items || [];
          } else {
            itemsByTab[tab] = itemsByTab[tab].concat(data.items || []);
          }
          if (tab === activeTab) {
            if (page === 1) {
              renderItems(itemsByTab[tab]);
            } else {
              appendItems(data.items || []);
            }
            toggleEmptyState(itemsByTab[tab]);
            toggleLoadMore();
          }
        })
        .catch(function () {
          if (loading) {
            loading.style.display = "none";
          }
          if (emptyState) {
            emptyState.style.display = "block";
          }
        });
    }

    function renderCounts(data) {
      var count = data.unread_count_total || 0;
      if (badge) {
        badge.textContent = count > 99 ? "99+" : String(count);
        badge.style.display = count > 0 ? "inline-block" : "none";
      }
      var sidebarBadge = document.getElementById("sidebar-notifications-badge");
      if (sidebarBadge) {
        sidebarBadge.textContent = count > 99 ? "99+" : String(count);
        sidebarBadge.style.display = count > 0 ? "inline-block" : "none";
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
        tabMessages.textContent = String(data.unread_notification_messages || 0);
      }
      if (tabAlerts) {
        tabAlerts.textContent = String(data.unread_alerts || 0);
      }
      if (tabSystem) {
        tabSystem.textContent = String(data.unread_system || 0);
      }
    }

    function renderItems(items) {
      if (!listContainer) {
        return;
      }
      listContainer.innerHTML = "";
      items.forEach(function (item) {
        listContainer.appendChild(buildItem(item));
      });
      if (loading) {
        loading.style.display = "none";
      }
    }

    function appendItems(items) {
      if (!listContainer || !items.length) {
        if (loading) {
          loading.style.display = "none";
        }
        return;
      }
      var previousScroll = scrollWrapper ? scrollWrapper.scrollTop : null;
      items.forEach(function (item) {
        listContainer.appendChild(buildItem(item));
      });
      if (loading) {
        loading.style.display = "none";
      }
      if (scrollWrapper && previousScroll !== null) {
        scrollWrapper.scrollTop = previousScroll;
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

    function removeThemeEmptyState() {
      var themeEmpty = document.querySelectorAll("#notificationItemsTabContent .empty-notification-elem");
      if (!themeEmpty.length) {
        return;
      }
      themeEmpty.forEach(function (node) {
        if (node && node.parentNode) {
          node.parentNode.removeChild(node);
        }
      });
    }

    function toggleEmptyState(items) {
      removeThemeEmptyState();
      if (!emptyState) {
        return;
      }
      emptyState.style.display = items.length ? "none" : "block";
      if (listContainer) {
        listContainer.style.display = items.length ? "block" : "none";
      }
    }

    function toggleLoadMore() {
      if (!loadMoreBtn) {
        return;
      }
      loadMoreBtn.style.display = hasNextByTab[activeTab] ? "inline-block" : "none";
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

    if (tabLinks.length) {
      tabLinks.forEach(function (link) {
        link.addEventListener("click", function () {
          var nextTab = (link.getAttribute("data-filter") || "ALL").toUpperCase();
          activeTab = nextTab;
          if (!itemsByTab[activeTab].length) {
            fetchTab(activeTab, 1);
          } else {
            renderItems(itemsByTab[activeTab]);
            toggleEmptyState(itemsByTab[activeTab]);
            toggleLoadMore();
          }
        });
      });
    }

    if (loadMoreBtn) {
      loadMoreBtn.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        var nextPage = pageByTab[activeTab] + 1;
        fetchTab(activeTab, nextPage).then(function () {
          var toggle = document.getElementById("page-header-notifications-dropdown");
          if (toggle && window.bootstrap && window.bootstrap.Dropdown) {
            var instance = window.bootstrap.Dropdown.getOrCreateInstance(toggle);
            instance.show();
          }
        });
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
          itemsByTab = { ALL: [], MESSAGE: [], ALERT: [], SYSTEM: [] };
          fetchTab(activeTab, 1);
        });
      });
    }

    fetchTab(activeTab, 1);
  }

  document.addEventListener("DOMContentLoaded", fetchTopbar);
})();
