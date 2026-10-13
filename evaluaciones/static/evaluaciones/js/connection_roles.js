(function () {
  function updateRoleFields(roleSection) {
    const sourceType = roleSection.querySelector("[data-role-source-type]");
    if (!sourceType) {
      return;
    }

    const isDjango = sourceType.value === "DJANGO";
    const isMysql = sourceType.value === "MYSQL_CONFIG";
    const djangoContainer = roleSection.querySelector(
      '[data-role-field-container="django_alias"]'
    );
    const mysqlContainer = roleSection.querySelector(
      '[data-role-field-container="mysql_connection"]'
    );
    const databaseContainer = roleSection.querySelector(
      '[data-role-field-container="database_name"]'
    );
    const djangoField = roleSection.querySelector("[data-role-django-alias]");
    const mysqlField = roleSection.querySelector(
      "[data-role-mysql-connection]"
    );
    const databaseField = roleSection.querySelector(
      "[data-role-database-name]"
    );

    if (djangoContainer) {
      djangoContainer.hidden = !isDjango;
    }
    if (djangoField) {
      djangoField.disabled = !isDjango;
    }
    if (mysqlContainer) {
      mysqlContainer.hidden = !isMysql;
    }
    if (mysqlField) {
      mysqlField.disabled = !isMysql;
    }
    if (databaseContainer) {
      databaseContainer.hidden = !isMysql;
    }
    if (databaseField) {
      databaseField.disabled = !isMysql;
    }
  }

  function initializeConnectionRoleSelectors() {
    document.querySelectorAll("[data-connection-role]").forEach((roleSection) => {
      const sourceType = roleSection.querySelector("[data-role-source-type]");
      if (!sourceType) {
        return;
      }

      sourceType.addEventListener("change", function () {
        updateRoleFields(roleSection);
      });
      updateRoleFields(roleSection);
    });

    const schemaModal = document.querySelector(
      '#baseEvaluacionesSchemaModal[data-open-on-load="true"]'
    );
    if (schemaModal && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(schemaModal).show();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeConnectionRoleSelectors);
  } else {
    initializeConnectionRoleSelectors();
  }
})();
