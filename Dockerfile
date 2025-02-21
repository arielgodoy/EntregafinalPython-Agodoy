# Utiliza una imagen base de Python adecuada
FROM python:3.8

# Establece el directorio de trabajo en el contenedor
WORKDIR /AppDocs

# Copia los archivos necesarios para instalar dependencias
COPY requirements.txt /AppDocs/

# Instala las dependencias de tu aplicación
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto de los archivos de la aplicación
COPY . /AppDocs/

# Expone el puerto en el que se ejecutará la aplicación (por ejemplo, 8000)
EXPOSE 8000

# Comando para ejecutar la aplicación
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
