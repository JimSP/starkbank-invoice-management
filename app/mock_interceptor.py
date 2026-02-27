import requests
import logging

logger = logging.getLogger(__name__)


def setup_mock_interceptor():
    original_request = requests.Session.request


    def _redirect_request(self, method, url, *args, **kwargs):
        if isinstance(url, str) and "starkbank.com" in url:
            new_url = url.replace("https://sandbox.api.starkbank.com", "http://127.0.0.1:9090")
            new_url = new_url.replace("https://api.starkbank.com", "http://127.0.0.1:9090")
            
            logger.warning(f"Interceptando {method} {url} -> {new_url}")
            return original_request(self, method, new_url, *args, **kwargs)
        
        return original_request(self, method, url, *args, **kwargs)

    requests.Session.request = _redirect_request
    
    logger.warning("MOCK API INTERCEPTOR ATIVADO: O tráfego da StarkBank está grampeado.")
