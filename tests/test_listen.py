import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from agent.listen import transcribe_audio


def test_transcribe_audio_writes_file_and_calls_openai():
    audio_bytes = b"audio-data"

    def fake_transcribe(model, file_obj):
        assert model == "whisper-1"
        data = file_obj.read()
        assert data == audio_bytes
        return {"text": "hello"}

    with patch("openai.Audio.transcribe", side_effect=fake_transcribe) as mock_transcribe:
        text = transcribe_audio(audio_bytes, sample_rate=16000)
        assert text == "hello"
        mock_transcribe.assert_called_once()
