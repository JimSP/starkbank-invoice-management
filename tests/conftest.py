"""tests/conftest.py — shared pytest fixtures."""

import pytest
from app.webhook import app as flask_app


@pytest.fixture()
def client():
    """Flask test client with TESTING mode enabled."""
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
