from unittest.mock import MagicMock, patch
from terngi import TerngiClient


def test_terngi_client_chat():
    client = TerngiClient(api_key="test-key", base_url="http://localhost:8000")
    with patch.object(client._client, "post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            is_error=False,
            json=lambda: {"response": "Hello world"},
        )
        res = client.chat("Hello")
        assert res.response == "Hello world"
    client.close()


def test_terngi_client_translate():
    client = TerngiClient(api_key="test-key", base_url="http://localhost:8000")
    with patch.object(client._client, "post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            is_error=False,
            json=lambda: {"translated_text": "Bawo ni", "detected_source_lang": "en"},
        )
        res = client.translate("Hello", target_lang="yo")
        assert res.translated_text == "Bawo ni"
    client.close()


def test_terngi_client_detect():
    client = TerngiClient(api_key="test-key", base_url="http://localhost:8000")
    with patch.object(client._client, "post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            is_error=False,
            json=lambda: {"language": "yo", "confidence": 0.98},
        )
        res = client.detect("Bawo ni")
        assert res.language == "yo"
        assert res.confidence == 0.98
    client.close()