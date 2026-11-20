import os
import unittest
from unittest.mock import patch

from sistema_web_de_laboratorio_bromatol_gico_flask_sqlite_pdf_a4 import app


class ProductionAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "APP_USERNAME": "laboratorio",
                "APP_PASSWORD": "test-password-12345",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = app.test_client()

    def test_allows_public_application_and_api_reads(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/bootstrap").status_code, 200)

    def test_requires_authentication_for_writes(self):
        response = self.client.post("/api/configuracion")

        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response.headers["WWW-Authenticate"])

    def test_rejects_wrong_credentials(self):
        response = self.client.post(
            "/api/configuracion", auth=("otro", "wrong-password-12345")
        )

        self.assertEqual(response.status_code, 401)

    def test_fails_closed_when_credentials_are_missing(self):
        with patch.dict(os.environ, {"APP_USERNAME": "", "APP_PASSWORD": ""}):
            read_response = self.client.get("/")
            write_response = self.client.post("/api/configuracion")

        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(write_response.status_code, 503)

    def test_accepts_configured_credentials_for_writes(self):
        with patch(
            "sistema_web_de_laboratorio_bromatol_gico_flask_sqlite_pdf_a4.get_db_connection"
        ) as get_db_connection:
            response = self.client.post(
                "/api/configuracion",
                auth=("laboratorio", "test-password-12345"),
                json={
                    "nombre": "Laboratorio",
                    "subtitulo": "",
                    "direccion": "",
                    "telefono": "",
                    "email": "",
                    "consideraciones_legales": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        get_db_connection.return_value.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
