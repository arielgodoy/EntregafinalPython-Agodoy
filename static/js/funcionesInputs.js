export function formatearRUT(inputElement) {
    if (!window.Funciones || !window.Funciones.rut) {
        throw new Error('Debe cargar static/js/funciones.js antes de funcionesInputs.js.');
    }
    window.Funciones.rut.vincularInput(inputElement);
}
