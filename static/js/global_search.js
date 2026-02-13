(function () {
  var cacheTranslations = null;
  var cacheLang = null;

  function getLanguage() {
    return localStorage.getItem("language") || "en";
  }

  function loadTranslations() {
    var lang = getLanguage();
    if (cacheTranslations && cacheLang === lang) {
      return Promise.resolve(cacheTranslations);
    }
    return fetch("/static/lang/" + lang + ".json", { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("request failed");
        }
        return response.json();
      })
      .then(function (data) {
        cacheLang = lang;
        cacheTranslations = data || {};
        return cacheTranslations;
      })
      .catch(function () {
        cacheTranslations = {};
        return cacheTranslations;
      });
  }

  function applyTranslations(root, translations) {
    if (!translations) {
      return;
    }
    var nodes = (root || document).querySelectorAll("[data-key]");
    Array.from(nodes).forEach(function (node) {
      var key = node.getAttribute("data-key");
      if (key && translations[key]) {
        node.textContent = translations[key];
      }
    });
  }

  function isValidTerm(value) {
    return value && value.length >= 2;
  }

  function readRecent() {
    try {
      var raw = localStorage.getItem("globalSearchRecent");
      if (!raw) {
        return [];
      }
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function writeRecent(items) {
    localStorage.setItem("globalSearchRecent", JSON.stringify(items.slice(0, 5)));
  }

  function addRecent(term) {
    var items = readRecent();
    var cleaned = term.trim();
    if (!cleaned) {
      return;
    }
    items = items.filter(function (item) {
      return item.toLowerCase() !== cleaned.toLowerCase();
    });
    items.unshift(cleaned);
    writeRecent(items);
  }

  function renderRecent(container, term, triggerSearch) {
    if (!container) {
      return;
    }
    var items = readRecent();
    container.innerHTML = "";
    if (!items.length) {
      return;
    }
    items.forEach(function (item) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-soft-secondary btn-sm rounded-pill me-1 mb-1";
      button.textContent = item;
      button.addEventListener("click", function () {
        triggerSearch(item);
      });
      container.appendChild(button);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var input = document.getElementById("search-options");
    var dropdown = document.getElementById("search-dropdown");
    var closeBtn = document.getElementById("search-close-options");
    var recentList = document.getElementById("global-search-recent-list");
    var pagesContainer = document.getElementById("global-search-pages");
    var emptyState = document.getElementById("global-search-empty");
    var loadingState = document.getElementById("global-search-loading");
    var viewAll = document.getElementById("global-search-view-all");
    var form = document.getElementById("global-search-form");

    if (!input || !dropdown) {
      return;
    }

    var debounceTimer;

    function showDropdown() {
      dropdown.classList.add("show");
    }

    function hideDropdown() {
      dropdown.classList.remove("show");
    }

    function setLoading(isLoading) {
      if (!loadingState) {
        return;
      }
      loadingState.classList.toggle("d-none", !isLoading);
    }

    function setEmpty(isEmpty) {
      if (!emptyState) {
        return;
      }
      emptyState.classList.toggle("d-none", !isEmpty);
    }

    function clearPages() {
      if (pagesContainer) {
        pagesContainer.innerHTML = "";
      }
    }

    function updateViewAll(query) {
      if (!viewAll) {
        return;
      }
      viewAll.href = "/search/results/?q=" + encodeURIComponent(query);
    }

    function renderPages(pages, translations) {
      clearPages();
      if (!pagesContainer) {
        return;
      }
      pages.forEach(function (page) {
        var link = document.createElement("a");
        link.href = page.url;
        link.className = "dropdown-item notify-item";

        var icon = document.createElement("i");
        icon.className = "ri-file-text-line align-middle fs-18 text-muted me-2";
        link.appendChild(icon);

        var textWrap = document.createElement("div");
        textWrap.className = "d-inline-block";

        var title = document.createElement("span");
        title.className = "d-block";
        if (page.label_key) {
          title.setAttribute("data-key", page.label_key);
          title.textContent = page.default_label || page.label_key;
        } else {
          title.textContent = page.default_label || "";
        }

        var subtitle = document.createElement("span");
        subtitle.className = "text-muted fs-12 d-block";
        if (page.group_key) {
          subtitle.setAttribute("data-key", page.group_key);
          subtitle.textContent = page.group_key;
        } else {
          subtitle.textContent = "";
        }

        textWrap.appendChild(title);
        textWrap.appendChild(subtitle);
        link.appendChild(textWrap);

        link.addEventListener("click", function () {
          addRecent(input.value);
        });

        pagesContainer.appendChild(link);
      });

      applyTranslations(pagesContainer, translations);
    }

    function executeSearch(term) {
      var query = term.trim();
      input.value = query;
      if (!isValidTerm(query)) {
        clearPages();
        setEmpty(false);
        setLoading(false);
        hideDropdown();
        return;
      }

      showDropdown();
      setLoading(true);
      setEmpty(false);
      updateViewAll(query);

      loadTranslations().then(function (translations) {
        fetch("/search/menu/?q=" + encodeURIComponent(query), {
          credentials: "same-origin",
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
        })
          .then(function (response) {
            if (!response.ok) {
              throw new Error("request failed");
            }
            return response.json();
          })
          .then(function (data) {
            var pages = (data && data.pages) || [];
            renderPages(pages, translations);
            setLoading(false);
            setEmpty(pages.length === 0);
          })
          .catch(function () {
            setLoading(false);
            setEmpty(true);
          });
      });
    }

    input.addEventListener("input", function () {
      var value = input.value || "";
      if (debounceTimer) {
        clearTimeout(debounceTimer);
      }
      debounceTimer = setTimeout(function () {
        executeSearch(value);
      }, 250);
    });

    input.addEventListener("focus", function () {
      renderRecent(recentList, input.value, executeSearch);
      if (isValidTerm(input.value)) {
        executeSearch(input.value);
      } else {
        showDropdown();
        setLoading(false);
        setEmpty(false);
      }
    });

    document.addEventListener("click", function (event) {
      if (!form) {
        return;
      }
      if (!form.contains(event.target)) {
        hideDropdown();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        hideDropdown();
      }
    });

    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        input.value = "";
        clearPages();
        setEmpty(false);
        setLoading(false);
        hideDropdown();
      });
    }
  });
})();
