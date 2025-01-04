    document.addEventListener('DOMContentLoaded', function () {
        const searchPropietario = document.getElementById('searchPropietario');
        const propietariosBody = document.getElementById('propietariosBody');
        const propietarioInput = document.getElementById('propietarioInput');
        const propietario_idInput = document.getElementById('propietario_idInput');



        function escapeHTML(text) {
            const div = document.createElement('div');
            div.innerText = text;
            return div.innerHTML;
        }

        function fetchPropietarios(query = '') {
            fetch(`/api/v1/propietarios/?search=${query}`)
                .then(response => {
                    if (!response.ok) throw new Error('Error al cargar propietarios');
                    return response.json();
                })
                .then(data => {
                    propietariosBody.innerHTML = '';
                    data.forEach(propietario => {
                        propietariosBody.innerHTML += 
                            <tr>
                                <td>${escapeHTML(propietario.id)}</td>
                                <td>${escapeHTML(propietario.nombre)}</td>
                                <td>
                                    <button class="btn btn-primary btn-sm" onclick="selectPropietario('${escapeHTML(propietario.id)}', '${escapeHTML(propietario.nombre)}')">Seleccionar</button>
                                </td>
                            </tr>;
                    });
                })
                .catch(error => {
                    console.error(error);
                    Toastify({
                        text: "Error al cargar propietarios. Intenta nuevamente.",
                        backgroundColor: "linear-gradient(to right, #ff5f6d, #ffc371)",
                        duration: 3000
                    }).showToast();
                });
        }

        window.selectPropietario = function (id, nombre) {
            propietarioInput.value = nombre;
            propietario_idInput.value = id;            
            const modalElement = document.getElementById('AyudaPropietariosModal');
            const modalInstance = bootstrap.Modal.getOrCreateInstance(modalElement);
            if (modalInstance) modalInstance.hide();
        };

        if (searchPropietario) {
            searchPropietario.addEventListener('input', function () {
                fetchPropietarios(this.value);
            });
        }

        fetchPropietarios();

        const searchTrabajador = document.getElementById('searchTrabajador');
        const trabajadoresBody = document.getElementById('trabajadoresBody');
        const trabajadorInput = document.getElementById('trabajadorInput');
        const trabajador_rutInput = document.getElementById('trabajador_rutInput');
        

        function fetchTrabajadores(query = '') {
            fetch(`/api/v1/trabajadores/?search=${query}`)
                .then(response => {
                    if (!response.ok) throw new Error('Error al cargar trabajadores');
                    return response.json();
                })
                .then(data => {
                    trabajadoresBody.innerHTML = '';
                    data.data.forEach(trabajador => {
                        trabajadoresBody.innerHTML += 
                            <tr>
                                <td>${escapeHTML(trabajador.rut)}</td>
                                <td>${escapeHTML(trabajador.nombre)}</td>
                                <td>
                                    <button class="btn btn-secondary btn-sm" onclick="selectTrabajador('${escapeHTML(trabajador.rut)}', '${escapeHTML(trabajador.nombre)}')">Seleccionar</button>
                                </td>
                            </tr>;
                    });
                })
                .catch(error => {
                    console.error(error);
                    Toastify({
                        text: "Error al cargar trabajadores. Intenta nuevamente.",
                        backgroundColor: "linear-gradient(to right, #ff5f6d, #ffc371)",
                        duration: 3000
                    }).showToast();
                });
        }

        window.selectTrabajador = function (rut, nombre) {
            trabajadorInput.value = nombre;
            trabajador_rutInput.value = rut;

                // Forzar el evento 'change' en el input del RUT
            const changeEvent = new Event('change', { bubbles: true });
            trabajador_rutInput.dispatchEvent(changeEvent);
            const modalElement = document.getElementById('AyudaTrabajadoresModal');
            const modalInstance = bootstrap.Modal.getOrCreateInstance(modalElement);
            if (modalInstance) modalInstance.hide();
        };

        if (searchTrabajador) {
            searchTrabajador.addEventListener('input', function () {
                fetchTrabajadores(this.value);
            });
        }

        fetchTrabajadores();

        document.addEventListener('hidden.bs.modal', function () {
            setTimeout(() => {
                document.querySelectorAll('.modal-backdrop').forEach(backdrop => backdrop.remove());
                document.body.classList.remove('modal-open');
                document.body.style = '';
            }, 200);
        });
    });
