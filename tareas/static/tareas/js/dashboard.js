(function () {
    function text(value) {
        return value || "-";
    }

    document.addEventListener("DOMContentLoaded", function () {
        if (window.jQuery && window.jQuery.fn && window.jQuery.fn.DataTable) {
            window.jQuery(".js-t060-datatable").DataTable({
                pageLength: 20,
                order: [],
            });
        }

        document.querySelectorAll(".js-task-info").forEach(function (button) {
            button.addEventListener("click", function () {
                var fields = {
                    correlativo: "task-info-correlativo",
                    titulo: "task-info-titulo",
                    descripcion: "task-info-descripcion",
                    estado: "task-info-estado",
                    prioridad: "task-info-prioridad",
                    responsable: "task-info-responsable",
                    fechaPublicacion: "task-info-fecha-publicacion",
                    fechaTope: "task-info-fecha-tope",
                    ambito: "task-info-ambito",
                    local: "task-info-local",
                    departamento: "task-info-departamento",
                };
                Object.keys(fields).forEach(function (key) {
                    var element = document.getElementById(fields[key]);
                    if (element) {
                        element.textContent = text(button.dataset[key]);
                    }
                });
                var detail = document.getElementById("task-info-detail");
                if (detail) {
                    detail.href = button.dataset.detalleUrl || "#";
                }
            });
        });
    });
}());
