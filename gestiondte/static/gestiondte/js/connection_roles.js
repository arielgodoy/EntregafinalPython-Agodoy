(function () {
  function updateRoleFields(roleSection) {
    const sourceType = roleSection.querySelector('[data-role-source-type]');
    const djangoContainer = roleSection.querySelector('[data-role-field-container="django_alias"]');
    const mysqlContainer = roleSection.querySelector('[data-role-field-container="mysql_connection"]');
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
