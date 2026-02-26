"""tests/test_config.py — covers app/config.py"""

from unittest.mock import MagicMock, patch

import starkbank
import app.config as cfg


class TestInitStarkbank:
    def test_returns_project(self):
        fake = MagicMock(spec=starkbank.Project)
        with patch("app.config.starkbank.Project", return_value=fake):
            assert cfg.init_starkbank() is fake

    def test_sets_global_user(self):
        fake = MagicMock(spec=starkbank.Project)
        with patch("app.config.starkbank.Project", return_value=fake):
            cfg.init_starkbank()
        assert starkbank.user is fake

    def test_uses_configured_values(self):
        with patch("app.config.starkbank.Project") as MockProject:
            MockProject.return_value = MagicMock()
            cfg.init_starkbank()
            MockProject.assert_called_once_with(
                environment=cfg.ENVIRONMENT,
                id=cfg.PROJECT_ID,
                private_key=cfg.PRIVATE_KEY,
            )
