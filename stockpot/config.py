"""Settings, read from the environment with a `.env` file filling in anything the environment leaves unset."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_env_file(path: Path) -> dict[str, str]:
    """The `KEY=value` pairs in a `.env` file, skipping blanks and `#` comments. A missing file is empty."""
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Settings:
    db_path: Path
    llm: str
    gemini_api_key: str
    gemini_model: str

    @property
    def backend(self) -> str:
        """The LLM backend in use: Gemini when asked for and given a key, otherwise the mock."""
        return "gemini" if self.llm == "gemini" and self.gemini_api_key else "mock"

    def __repr__(self) -> str:
        key = "set" if self.gemini_api_key else "unset"
        return f"Settings(db_path={self.db_path}, llm={self.llm}, key={key}, model={self.gemini_model})"


def load(env_file: Path = ROOT / ".env") -> Settings:
    environment = {k: v for k, v in os.environ.items() if k.startswith(("STOCKPOT_", "GEMINI_"))}
    values = read_env_file(env_file) | environment
    db_path = Path(values.get("STOCKPOT_DB") or "stockpot.db")
    return Settings(
        db_path=db_path if db_path.is_absolute() else ROOT / db_path,
        llm=(values.get("STOCKPOT_LLM") or "mock").strip().lower(),
        gemini_api_key=(values.get("GEMINI_API_KEY") or "").strip(),
        gemini_model=(values.get("GEMINI_MODEL") or "gemini-3.8-flash").strip(),
    )
