import os
import unittest
from unittest.mock import patch

os.environ["JOURNAL_DEMO"] = "1"

from fastapi.testclient import TestClient

from api import app


class BrowserOriginPolicyTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_non_browser_client_is_allowed(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_vite_development_origin_is_allowed(self):
        origin = "http://localhost:5173"
        response = self.client.get("/health", headers={"Origin": origin})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], origin)

    def test_untrusted_origin_cannot_read_api(self):
        response = self.client.get(
            "/health",
            headers={"Origin": "https://example.invalid"},
        )
        self.assertEqual(response.status_code, 403)

    def test_untrusted_origin_cannot_trigger_refresh(self):
        response = self.client.post(
            "/refresh",
            headers={"Origin": "https://example.invalid"},
        )
        self.assertEqual(response.status_code, 403)

    def test_empty_api_key_is_reported_as_unconfigured(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            health = self.client.get("/health")
            chat = self.client.post("/chat", json={"message": "hello"})

        self.assertFalse(health.json()["gemini_key_set"])
        self.assertEqual(chat.status_code, 503)


if __name__ == "__main__":
    unittest.main()
