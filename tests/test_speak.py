import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
import pytest
from unittest.mock import Mock
from agent.speak import speak_text


def test_speak_text_success(tmp_path, monkeypatch):
    mock_response = Mock()
    mock_response.content = b'audio-data'
    mock_response.raise_for_status.return_value = None

    def mock_post(url, headers, json, timeout=None):
        assert url.endswith('/v1/text-to-speech/test-voice')
        assert headers['xi-api-key'] == 'test-key'
        assert json['text'] == 'hello'
        assert timeout == 10.0
        return mock_response

    monkeypatch.setenv('ELEVEN_VOICE_ID', 'test-voice')
    monkeypatch.setenv('ELEVEN_API_KEY', 'test-key')
    monkeypatch.setattr(requests, 'post', mock_post)

    out_file = tmp_path / 'out.mp3'
    result = speak_text('hello', str(out_file))

    assert result == str(out_file)
    assert out_file.read_bytes() == b'audio-data'
    mock_response.raise_for_status.assert_called_once()


def test_speak_text_failure(monkeypatch):
    def mock_post(*args, **kwargs):
        raise requests.exceptions.RequestException('boom')

    monkeypatch.setattr(requests, 'post', mock_post)

    with pytest.raises(RuntimeError) as exc:
        speak_text('hello')
    assert 'ElevenLabs TTS failed' in str(exc.value)
