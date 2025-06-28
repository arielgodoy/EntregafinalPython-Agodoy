// static/js/formatters.js

export function formatearRUT(inputElement) {
    if (!inputElement) return;

    inputElement.addEventListener('input', function (e) {
        let value = e.target.value.replace(/[^0-9kK]/g, '');
        let formattedRut = '';

        if (value.length <= 7) {
            if (value.length > 6) {
                formattedRut =
                    value.slice(0, value.length - 6) + '.' +
                    value.slice(value.length - 6, value.length - 3) + '.' +
                    value.slice(value.length - 3);
            } else if (value.length > 3) {
                formattedRut =
                    value.slice(0, value.length - 3) + '.' +
                    value.slice(value.length - 3);
            } else {
                formattedRut = value;
            }
        } else {
            formattedRut =
                value.slice(0, value.length - 7) + '.' +
                value.slice(value.length - 7, value.length - 4) + '.' +
                value.slice(value.length - 4, value.length - 1) + '-' +
                value.slice(value.length - 1);
        }

        e.target.value = formattedRut;
    });
}

// Este bloque se ejecuta al cargar el módulo
document.addEventListener('DOMContentLoaded', function () {
    const rutInput = document.querySelector('[data-inputingreso="camporut"]');
    formatearRUT(rutInput);
});
