import unittest
from unittest.mock import patch

from fastapi import HTTPException

from middleware.agent_control import require_agent_control


class AgentControlAuthTests(unittest.TestCase):
    def test_disabled_returns_503(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", False), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "secret"
        ):
            with self.assertRaises(HTTPException) as ctx:
                require_agent_control("Bearer secret")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_missing_token_config_returns_503(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", ""
        ):
            with self.assertRaises(HTTPException) as ctx:
                require_agent_control("Bearer secret")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_missing_authorization_returns_401(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "secret"
        ):
            with self.assertRaises(HTTPException) as ctx:
                require_agent_control(None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_authorization_returns_401(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "secret"
        ):
            with self.assertRaises(HTTPException) as ctx:
                require_agent_control("Bearer wrong")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_correct_authorization_returns_actor_context(self):
        with patch("middleware.agent_control.settings.AGENT_CONTROL_ENABLED", True), patch(
            "middleware.agent_control.settings.AGENT_CONTROL_TOKEN", "secret"
        ):
            context = require_agent_control("Bearer secret")
        self.assertEqual(context, {"actor": "hermes"})


if __name__ == "__main__":
    unittest.main()
