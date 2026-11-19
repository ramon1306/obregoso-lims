# OBREGOSO LIMS

Sistema web de gestión de laboratorio bromatológico y análisis de agua, desarrollado con Flask y SQLite.

## Requisitos

- Python 3.13 recomendado

## Instalación en Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Ejecución local

```powershell
.\.venv\Scripts\python.exe .\sistema_web_de_laboratorio_bromatol_gico_flask_sqlite_pdf_a4.py
```

Luego abre <http://127.0.0.1:5000>.

En desarrollo local, el acceso no requiere autenticación. En producción, la app exige `APP_ENV=production`, `APP_USERNAME` y una `APP_PASSWORD` de al menos 16 caracteres.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Publicación gratuita en PythonAnywhere

PythonAnywhere Beginner ofrece una app web Flask y almacenamiento persistente en el directorio de usuario, adecuado para esta base SQLite pequeña. El plan tiene límites de CPU y almacenamiento; realiza copias de seguridad de la base manualmente.

1. Crea una cuenta Beginner en <https://www.pythonanywhere.com/registration/register/beginner/>.
2. Desde una consola Bash de PythonAnywhere, clona este repositorio e instala dependencias en un entorno virtual con Python 3.13:

   ```bash
   git clone https://github.com/ramon1306/obregoso-lims.git ~/obregoso-lims
   cd ~/obregoso-lims
   mkvirtualenv --python=/usr/bin/python3.13 obregoso-lims
   pip install -r requirements.txt
   ```

3. Sube `laboratorio_bromatologia.db` desde la sección Files a `~/obregoso-lims/`. La base contiene datos y no se versiona ni se publica en GitHub.
4. Crea `~/obregoso-lims/.env` en PythonAnywhere con los valores siguientes. Usa una contraseña aleatoria de al menos 16 caracteres y no la agregues a Git:

   ```text
   APP_ENV=production
   APP_USERNAME=admin
   APP_PASSWORD=REEMPLAZAR_POR_UNA_CONTRASENA_ALEATORIA
   ```

5. En la pestaña Web, crea una app con Manual configuration y Python 3.13. Selecciona el entorno virtual `~/.virtualenvs/obregoso-lims` y configura su archivo WSGI con el contenido de [pythonanywhere_wsgi.example.py](./pythonanywhere_wsgi.example.py).
6. Recarga la app desde la pestaña Web. La autenticación HTTP solicitará el usuario y la contraseña configurados en `.env`.

El ejemplo WSGI carga las variables privadas, configura SQLite dentro del directorio persistente del proyecto e inicializa el esquema sin borrar una base existente.
