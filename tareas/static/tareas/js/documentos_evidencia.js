(function () {
    "use strict";

    const formatosPermitidos = {
        PDF: ".pdf",
        JPG: ".jpg,.jpeg",
        JPEG: ".jpg,.jpeg",
        PNG: ".png",
        DOC: ".doc",
        DOCX: ".docx",
        XLS: ".xls",
        XLSX: ".xlsx"
    };

    function actualizarFiltroArchivo(formatoSelect, archivoInput) {
        const accept = formatosPermitidos[formatoSelect.value] || "";
        archivoInput.accept = accept;
    }

    document.querySelectorAll("form").forEach(function (formulario) {
        const formatoSelect = formulario.querySelector(
            'select[name="formato_archivo"]'
        );
        const archivoInput = formulario.querySelector(
            'input[type="file"][name="archivo"]'
        );

        if (!formatoSelect || !archivoInput) {
            return;
        }

        actualizarFiltroArchivo(formatoSelect, archivoInput);
        formatoSelect.addEventListener("change", function () {
            actualizarFiltroArchivo(formatoSelect, archivoInput);
        });
    });
})();
