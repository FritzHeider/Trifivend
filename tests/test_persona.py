import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.persona import Persona


def test_system_prompt_includes_details():
    persona = Persona(name="Ava", voice="warm", tone="friendly")
    prompt = persona.system_prompt()
    assert "Ava" in prompt
    assert "warm" in prompt
    assert "friendly" in prompt
