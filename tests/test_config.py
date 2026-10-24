"""Settings come from `.env` and the environment, and Gemini is only chosen when it can actually run."""

from stockpot import config


def test_an_env_file_is_read_skipping_comments_blanks_and_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nGEMINI_MODEL="gemini-x"\nSTOCKPOT_LLM = gemini \nnot a pair\n')
    assert config.read_env_file(env) == {"GEMINI_MODEL": "gemini-x", "STOCKPOT_LLM": "gemini"}
    assert config.read_env_file(tmp_path / "missing") == {}


def test_the_environment_overrides_the_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("STOCKPOT_DB=from-file.db\n")
    monkeypatch.setenv("STOCKPOT_DB", "from-env.db")
    assert config.load(env).db_path == config.ROOT / "from-env.db"


def test_gemini_is_used_only_when_asked_for_and_given_a_key(tmp_path, monkeypatch):
    for name in ("STOCKPOT_LLM", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    for text, backend in (
        ("", "mock"),
        ("STOCKPOT_LLM=gemini\n", "mock"),
        ("GEMINI_API_KEY=k\n", "mock"),
        ("STOCKPOT_LLM=gemini\nGEMINI_API_KEY=k\n", "gemini"),
    ):
        env.write_text(text)
        assert config.load(env).backend == backend, text


def test_the_api_key_never_appears_when_settings_are_printed(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=super-secret-key\n")
    assert "super-secret-key" not in repr(config.load(env))
