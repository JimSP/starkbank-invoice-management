import requests
import pytest
from app.mock_interceptor import setup_mock_interceptor


def test_mock_interceptor_redirects_url(monkeypatch):
    original_request = requests.Session.request
    setup_mock_interceptor()
    
    try:
        with pytest.raises(requests.exceptions.ConnectionError) as exc:
            requests.get("https://sandbox.api.starkbank.com/v2/invoice", timeout=0.1)
        
        assert "127.0.0.1" in str(exc.value)
        assert "9090" in str(exc.value)
    finally:
        requests.Session.request = original_request


def test_mock_interceptor_ignores_other_urls(monkeypatch):
    import requests
    from app.mock_interceptor import setup_mock_interceptor
    original_request = requests.Session.request
    setup_mock_interceptor()
    try:
        with pytest.raises(requests.exceptions.ConnectionError):
            requests.get("https://google.com", timeout=0.001)
    finally:
        requests.Session.request = original_request