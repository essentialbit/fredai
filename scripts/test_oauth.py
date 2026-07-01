#!/usr/bin/env python3
import sys
import unittest
from unittest.mock import patch, MagicMock

# Inject dummy OAuth config variables before importing main to ensure routes are active
import os
os.environ["GOOGLE_CLIENT_ID"] = "test-google-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-google-secret"
os.environ["GITHUB_CLIENT_ID"] = "test-github-id"
os.environ["GITHUB_CLIENT_SECRET"] = "test-github-secret"

from flask import session
from main import app
from memory_store import get_user_by_username, get_conn

def delete_user_by_username(username):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE username=?", (username,))

class TestOAuth(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

    def tearDown(self):
        # Clean up any test users
        delete_user_by_username("google_testuser")
        delete_user_by_username("github_testuser")
        self.app_context.pop()

    def test_google_login_redirect(self):
        res = self.app.get("/login/google")
        self.assertEqual(res.status_code, 302)
        self.assertIn("accounts.google.com", res.location)

    def test_github_login_redirect(self):
        res = self.app.get("/login/github")
        self.assertEqual(res.status_code, 302)
        self.assertIn("github.com/login/oauth/authorize", res.location)

    @patch("requests.post")
    @patch("requests.get")
    def test_google_callback_success(self, mock_get, mock_post):
        # Setup mock responses
        mock_post_res = MagicMock()
        mock_post_res.status_code = 200
        mock_post_res.json.return_value = {"access_token": "google-mock-token"}
        mock_post.return_value = mock_post_res

        mock_get_res = MagicMock()
        mock_get_res.status_code = 200
        mock_get_res.json.return_value = {
            "sub": "12345678",
            "name": "Google Test User",
            "email": "testuser@gmail.com"
        }
        mock_get.return_value = mock_get_res

        with self.app as c:
            # 1. Start login flow to generate state in session
            c.get("/login/google")
            state = session["oauth_state"]
            
            # 2. Call callback with state and code
            res = c.get(f"/login/google/callback?code=mockcode&state={state}")
            self.assertEqual(res.status_code, 302)
            self.assertEqual(res.location, "/")
            self.assertEqual(session["username"], "google_testuser")
            self.assertEqual(session["display_name"], "Google Test User")

    @patch("requests.post")
    @patch("requests.get")
    def test_github_callback_success(self, mock_get, mock_post):
        # Setup mock responses
        mock_post_res = MagicMock()
        mock_post_res.status_code = 200
        mock_post_res.json.return_value = {"access_token": "github-mock-token"}
        mock_post.return_value = mock_post_res

        mock_get_res = MagicMock()
        mock_get_res.status_code = 200
        mock_get_res.json.return_value = {
            "login": "testuser",
            "name": "GitHub Test User"
        }
        mock_get.return_value = mock_get_res

        with self.app as c:
            # 1. Start login flow
            c.get("/login/github")
            state = session["oauth_state"]
            
            # 2. Callback
            res = c.get(f"/login/github/callback?code=mockcode&state={state}")
            self.assertEqual(res.status_code, 302)
            self.assertEqual(res.location, "/")
            self.assertEqual(session["username"], "github_testuser")
            self.assertEqual(session["display_name"], "GitHub Test User")

if __name__ == "__main__":
    unittest.main()
