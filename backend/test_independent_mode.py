import unittest

from fastapi.testclient import TestClient

from main import app


class IndependentModeTests(unittest.TestCase):
    def test_signup_login_and_score_submission(self):
        client = TestClient(app)
        username = "alice_local"
        password = "secret123"

        signup = client.post(
            "/api/signup",
            json={"username": username, "password": password},
        )
        self.assertEqual(signup.status_code, 200, signup.text)
        self.assertTrue(signup.json()["ok"])

        login = client.post(
            "/api/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["token"]
        self.assertTrue(token)

        score = client.post(
            "/api/score",
            json={"name": username, "score": 42, "duration_ms": 1234},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(score.status_code, 200, score.text)
        self.assertEqual(score.json()["ok"], True)


if __name__ == "__main__":
    unittest.main()
