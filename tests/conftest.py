import pytest
from app.webhook import app as flask_app

def _make_session_not_processed():
    from unittest.mock import MagicMock
    session = MagicMock()
    session.get.return_value = None
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session)
    cm.__exit__ = MagicMock(return_value=False)
    return cm

@pytest.fixture()
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
