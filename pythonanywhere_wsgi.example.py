import os
import sys

from dotenv import load_dotenv

project_home = os.path.expanduser("~/obregoso-lims")
if project_home not in sys.path:
    sys.path.insert(0, project_home)

load_dotenv(os.path.join(project_home, ".env"))
os.environ.setdefault("APP_ENV", "production")
os.environ.setdefault(
    "LAB_DB_PATH", os.path.join(project_home, "laboratorio_bromatologia.db")
)

if not os.environ.get("APP_USERNAME") or len(os.environ.get("APP_PASSWORD", "")) < 16:
    raise RuntimeError(
        "Set APP_USERNAME and a 16-character APP_PASSWORD in the private .env file."
    )

from sistema_web_de_laboratorio_bromatol_gico_flask_sqlite_pdf_a4 import (
    app as application,
    init_db,
)

init_db()
