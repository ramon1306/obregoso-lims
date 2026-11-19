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

    def test_requires_authentication_for_application(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response.headers["WWW-Authenticate"])

    def test_rejects_wrong_credentials(self):
        response = self.client.get("/", auth=("otro", "wrong-password-12345"))

        self.assertEqual(response.status_code, 401)

    def test_fails_closed_when_credentials_are_missing(self):
        with patch.dict(os.environ, {"APP_USERNAME": "", "APP_PASSWORD": ""}):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 503)

    def test_accepts_configured_credentials(self):
        response = self.client.get("/", auth=("laboratorio", "test-password-12345"))

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
