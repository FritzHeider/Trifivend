import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import types
from unittest.mock import Mock
from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    stub = types.ModuleType('app.voicebot')
    mock_coldcall = Mock(return_value='AI reply')
    stub.coldcall_lead = mock_coldcall
    sys.modules['app.voicebot'] = stub

    if 'twilio.webhook_handler' in sys.modules:
        del sys.modules['twilio.webhook_handler']
    sys.modules.pop('twilio', None)
    import twilio_utils.webhook_handler as handler

    mock_speak = Mock()
    monkeypatch.setattr(handler, 'speak_text', mock_speak)
    return handler.app, mock_coldcall, mock_speak


def test_twilio_voice_with_speech(monkeypatch):
    app, mock_coldcall, mock_speak = _load_app(monkeypatch)
    client = TestClient(app)
    resp = client.post('/twilio-voice', data={'SpeechResult': 'hi'})
    assert resp.status_code == 200
    assert '<Play>https://your-app.fly.dev/audio/response.mp3</Play>' in resp.text
    mock_coldcall.assert_called_once_with([{'role': 'user', 'content': 'hi'}])
    mock_speak.assert_called_once_with('AI reply')


def test_twilio_voice_without_speech(monkeypatch):
    app, mock_coldcall, mock_speak = _load_app(monkeypatch)
    client = TestClient(app)
    resp = client.post('/twilio-voice')
    assert resp.status_code == 200
    assert 'Ava from Trifivend' in resp.text
    mock_coldcall.assert_not_called()
    mock_speak.assert_not_called()
