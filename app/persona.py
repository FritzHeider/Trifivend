from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Persona:
    """Definition of a calling persona used for voice and style."""
    name: str
    voice: str
    tone: Optional[str] = None
    pitch: Optional[str] = None

    def system_prompt(self) -> str:
        """Return a system prompt describing this persona."""
        desc = [f"You are {self.name} speaking in the {self.voice} voice."]
        if self.tone:
            desc.append(f"Your tone is {self.tone}.")
        if self.pitch:
            desc.append(f"Your vocal pitch is {self.pitch}.")
        return " ".join(desc)

__all__ = ["Persona"]
