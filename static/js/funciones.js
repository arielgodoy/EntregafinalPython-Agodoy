(function (global) {
    "use strict";

    function limpiar(value) {
        return String(value == null ? "" : value)
            .replace(/[^0-9kK]/g, "")
            .toUpperCase();
    }

    function formatear(value) {
        const cleanValue = limpiar(value);

        if (cleanValue.length <= 7) {
            if (cleanValue.length > 6) {
                return cleanValue.slice(0, cleanValue.length - 6) + "." +
                    cleanValue.slice(cleanValue.length - 6, cleanValue.length - 3) + "." +
                    cleanValue.slice(cleanValue.length - 3);
            }
            if (cleanValue.length > 3) {
                return cleanValue.slice(0, cleanValue.length - 3) + "." +
                    cleanValue.slice(cleanValue.length - 3);
            }
            return cleanValue;
        }

        return cleanValue.slice(0, cleanValue.length - 7) + "." +
            cleanValue.slice(cleanValue.length - 7, cleanValue.length - 4) + "." +
            cleanValue.slice(cleanValue.length - 4, cleanValue.length - 1) + "-" +
            cleanValue.slice(cleanValue.length - 1);
    }

    function calcularDigitoVerificador(cuerpo) {
        const cleanBody = String(cuerpo == null ? "" : cuerpo).replace(/\D/g, "");
        if (!cleanBody) return "";

        let multiplier = 2;
        let sum = 0;

        for (let index = cleanBody.length - 1; index >= 0; index -= 1) {
            sum += Number(cleanBody[index]) * multiplier;
            multiplier = multiplier === 7 ? 2 : multiplier + 1;
        }

        const remainder = 11 - (sum % 11);
        if (remainder === 11) return "0";
        if (remainder === 10) return "K";
        return String(remainder);
    }

    function validar(value) {
        const cleanValue = limpiar(value);
        if (!/^\d{1,8}[0-9K]$/.test(cleanValue)) return false;

        const body = cleanValue.slice(0, -1);
        const expectedDigit = calcularDigitoVerificador(body);
        return cleanValue.slice(-1) === expectedDigit;
    }

    function vincularInput(inputElement, options) {
        if (!inputElement || inputElement.dataset.funcionesRutVinculado === "true") {
            return;
        }

        const settings = options || {};
        const validate = settings.validar === true;
        const errorMessage = settings.mensaje || "Ingrese un RUT válido.";

        inputElement.addEventListener("input", function (event) {
            event.target.value = formatear(event.target.value);
            if (validate) {
                event.target.setCustomValidity(
                    !event.target.value || validar(event.target.value) ? "" : errorMessage
                );
            }
        });

        if (validate && inputElement.form) {
            inputElement.form.addEventListener("submit", function () {
                inputElement.setCustomValidity(
                    !inputElement.value || validar(inputElement.value) ? "" : errorMessage
                );
            });
        }

        inputElement.dataset.funcionesRutVinculado = "true";
    }

    const funciones = global.Funciones || {};
    funciones.rut = {
        limpiar: limpiar,
        formatear: formatear,
        calcularDigitoVerificador: calcularDigitoVerificador,
        validar: validar,
        vincularInput: vincularInput
    };
    global.Funciones = funciones;
}(window));
