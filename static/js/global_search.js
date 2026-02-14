(function () {
  var cacheTranslations = null;
  var cacheLang = null;
  var menuIndex = []; // Índice de menú construido desde DOM

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

  /**
   * Construye índice de búsqueda directamente desde el DOM del sidebar.
   * Lee todos los links que el usuario PUEDE VER (respeta permisos).
   * Indexa también los toggles colapsables (padres) apuntando al primer hijo navegable.
   */
  function buildMenuIndexFromDOM() {
    var index = [];
    var sidebar = document.getElementById("navbar-nav");
    if (!sidebar) return index;

    function safeTextFromSpan(span) {
      if (!span) return "";
      // Solo nodos de texto directos (evita badges)
      return Array.from(span.childNodes)
        .filter(function (node) { return node.nodeType === 3; })
        .map(function (node) { return (node.textContent || ""); })
        .join("")
        .trim();
    }

    function getGroupNameForLink(link) {
      // Si está dentro de un collapse, resolver el texto del botón que lo abre
      var parentCollapse = link.closest(".collapse.menu-dropdown");
      if (!parentCollapse) return "";
      var collapseId = parentCollapse.getAttribute("id");
      if (!collapseId) return "";

      var toggle = sidebar.querySelector('[data-bs-toggle="collapse"][href="#' + collapseId + '"],[data-bs-toggle="collapse"][data-bs-target="#' + collapseId + '"]');
      if (!toggle) return "";

      var span = toggle.querySelector("span[data-key]") || toggle.querySelector("span");
      return safeTextFromSpan(span) || (toggle.textContent || "").trim();
    }

    function addIndexItem(opts) {
      if (!opts || !opts.url) return;
      var label = (opts.default_label || "").trim();
      if (!label) return;

      var groupName = (opts.group_name || "").trim();
      var labelKey = (opts.label_key || "").trim();
      var groupKey = (opts.group_key || "").trim();

      var keywords = [
        label,
        labelKey,
        groupName,
        groupKey
      ].filter(Boolean).join(" ").toLowerCase();

      index.push({
        url: opts.url,
        label_key: labelKey,
        default_label: label,
        group_key: groupKey,
        group_name: groupName,
        keywords: keywords
      });
    }

    // 1) Indexar links navegables (no collapse toggles)
    var navLinks = sidebar.querySelectorAll("a.nav-link");
    navLinks.forEach(function (link) {
      var href = (link.getAttribute("href") || "").trim();
      var isCollapseToggle = !!link.getAttribute("data-bs-toggle") || !!link.getAttribute("data-bs-target");

      // Ignorar toggles aquí (los tratamos en sección 2)
      if (isCollapseToggle) return;

      // Ignorar links inválidos o anchors
      if (!href || href === "#" || href.indexOf("#") === 0) return;

      var spanWithKey = link.querySelector("span[data-key]");
      var labelKey = spanWithKey ? (spanWithKey.getAttribute("data-key") || "").trim() : "";
      var defaultLabel = safeTextFromSpan(spanWithKey) || (link.textContent || "").trim();

      var groupName = getGroupNameForLink(link);
      var groupKey = "";
      var toggleSpanWithKey = null;
      if (groupName) {
        // Intentar recuperar data-key del toggle padre si existe
        var parentCollapse = link.closest(".collapse.menu-dropdown");
        var collapseId = parentCollapse ? parentCollapse.getAttribute("id") : "";
        if (collapseId) {
          var toggle = sidebar.querySelector('[data-bs-toggle="collapse"][href="#' + collapseId + '"],[data-bs-toggle="collapse"][data-bs-target="#' + collapseId + '"]');
          toggleSpanWithKey = toggle ? toggle.querySelector("span[data-key]") : null;
          groupKey = toggleSpanWithKey ? (toggleSpanWithKey.getAttribute("data-key") || "").trim() : "";
        }
      }

      addIndexItem({
        url: href,
        label_key: labelKey,
        default_label: defaultLabel,
        group_key: groupKey,
        group_name: groupName
      });
    });

    // 2) Indexar también los padres (collapse toggles) apuntando al primer hijo navegable
    var toggles = sidebar.querySelectorAll('[data-bs-toggle="collapse"]');
    toggles.forEach(function (toggle) {
      var target = (toggle.getAttribute("data-bs-target") || "").trim();
      var href = (toggle.getAttribute("href") || "").trim();

      var collapseSelector = "";
      if (target && target.indexOf("#") === 0) collapseSelector = target;
      else if (href && href.indexOf("#") === 0) collapseSelector = href;

      if (!collapseSelector) return;

      var collapse = sidebar.querySelector(collapseSelector);
      if (!collapse) return;

      // Primer link hijo navegable
      var firstChildLink = collapse.querySelector('a.nav-link[href]:not([data-bs-toggle]):not([data-bs-target])');
      if (!firstChildLink) return;

      var childHref = (firstChildLink.getAttribute("href") || "").trim();
      if (!childHref || childHref === "#" || childHref.indexOf("#") === 0) return;

      var toggleSpan = toggle.querySelector("span[data-key]") || toggle.querySelector("span");
      var labelKey = toggleSpan && toggleSpan.getAttribute ? (toggleSpan.getAttribute("data-key") || "").trim() : "";
      var defaultLabel = safeTextFromSpan(toggleSpan) || (toggle.textContent || "").trim();

      // Los padres no necesitan group, pero si quieres, puedes dejar group_name vacío
      addIndexItem({
        url: childHref,
        label_key: labelKey,
        default_label: defaultLabel,
        group_key: labelKey,
        group_name: "" // o defaultLabel si quieres que aparezca agrupado
      });
    });

    console.log("Menú indexado desde DOM:", index.length, "items");
    return index;
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
    // Construir índice desde DOM al cargar página
    menuIndex = buildMenuIndexFromDOM();

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
          subtitle.textContent = page.group_name || page.group_key;
        } else if (page.group_name) {
          subtitle.textContent = page.group_name;
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

    /**
     * Busca en el índice local (DOM) en lugar de consultar backend.
     * Mucho más rápido y siempre actualizado.
     */
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

      // Búsqueda local instantánea
      loadTranslations().then(function (translations) {
        var queryLower = query.toLowerCase();
        var results = menuIndex.filter(function(item) {
          return item.keywords.indexOf(queryLower) !== -1;
        });

        // Limitar a 10 resultados
        var pages = results.slice(0, 10);
        
        renderPages(pages, translations);
        setLoading(false);
        setEmpty(pages.length === 0);
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

