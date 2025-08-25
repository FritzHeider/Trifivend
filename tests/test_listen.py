import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.listen import transcribe_audio


def test_transcribe_audio_writes_file_and_calls_openai():
    audio_bytes = b"audio-data"

    def fake_transcribe(model, file):
        assert model == "whisper-1"
        data = file.read()
        assert data == audio_bytes
        return SimpleNamespace(text="hello")

    with patch(
        "agent.listen.client.audio.transcriptions.create", side_effect=fake_transcribe
    ) as mock_transcribe:
        text = transcribe_audio(audio_bytes, sample_rate=16000)
        assert text == "hello"
        mock_transcribe.assert_called_once()
