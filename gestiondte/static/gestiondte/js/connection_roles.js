(function () {
  function updateRoleFields(roleSection) {
    const sourceType = roleSection.querySelector('[data-role-source-type]');
    const djangoContainer = roleSection.querySelector('[data-role-field-container="django_alias"]');
    const mysqlContainer = roleSection.querySelector('[data-role-field-container="mysql_connection"]');
    const databaseContainer = roleSection.querySelector('[data-role-field-container="database_name"]');
    const djangoField = roleSection.querySelector('[data-role-django-alias]');
    const mysqlField = roleSection.querySelector('[data-role-mysql-connection]');

    if (!sourceType || !djangoContainer || !mysqlContainer || !djangoField || !mysqlField) {
      return;
    }

    const isDjango = sourceType.value === 'DJANGO';
    const isMysql = sourceType.value === 'MYSQL_CONFIG';

    djangoContainer.hidden = !isDjango;
    mysqlContainer.hidden = !isMysql;
    djangoField.disabled = !isDjango;
    mysqlField.disabled = !isMysql;
    if (databaseContainer) {
      const databaseField = databaseContainer.querySelector('[data-role-database-name]');
      databaseContainer.hidden = !isMysql;
      if (databaseField) {
        databaseField.disabled = !isMysql;
      }
    }
  }

  function initializeConnectionRoleSelectors() {
    document.querySelectorAll('[data-connection-role]').forEach((roleSection) => {
      const sourceType = roleSection.querySelector('[data-role-source-type]');
      if (!sourceType) {
        return;
      }

      sourceType.addEventListener('change', function () {
        updateRoleFields(roleSection);
      });
      updateRoleFields(roleSection);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeConnectionRoleSelectors);
  } else {
    initializeConnectionRoleSelectors();
  }
})();
