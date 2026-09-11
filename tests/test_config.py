from ligaotai.config import AppConfig, library_path, load_config, save_config


def test_default_when_no_file(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.library_dir == ""
    assert library_path(cfg, tmp_path) == tmp_path / "书库"


def test_save_and_load(tmp_path):
    save_config(AppConfig(library_dir=str(tmp_path / "别处")), tmp_path)
    cfg = load_config(tmp_path)
    assert library_path(cfg, tmp_path) == tmp_path / "别处"


from ligaotai.config import KEY_ENV, apply_update, effective_key, mask_key, public_config


def test_model_defaults():
    cfg = AppConfig()
    assert cfg.api_base == "https://api.deepseek.com"
    assert (cfg.batch.model, cfg.batch.thinking, cfg.batch.json_mode) == ("deepseek-flash", "off", True)
    assert (cfg.synth.thinking, cfg.synth.effort, cfg.synth.max_tokens) == ("on", "high", 32768)
    assert cfg.concurrency == 8


def test_old_config_file_still_loads(tmp_path):
    (tmp_path / "config.json").write_text('{"library_dir": ""}', encoding="utf-8")
    assert load_config(tmp_path).batch.thinking == "off"


def test_effective_key_prefers_file_then_env(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "sk-from-env-123")
    assert effective_key(AppConfig()) == "sk-from-env-123"
    assert effective_key(AppConfig(api_key="sk-from-file-9")) == "sk-from-file-9"


def test_mask_key():
    assert mask_key("") == ""
    assert mask_key("sk-abcdefghijkl") == "sk-…ijkl"
    assert mask_key("short") == "…"


def test_public_config_never_shows_key(tmp_path):
    data = public_config(AppConfig(api_key="sk-abcdefghijkl"), tmp_path)
    assert "sk-abcdefghijkl" not in str(data)
    assert data["has_key"] is True and data["key_from_env"] is False
    assert data["library_path"] == str(tmp_path / "书库")


def test_apply_update_keeps_old_key():
    old = AppConfig(api_key="sk-abcdefghijkl")
    assert apply_update(old, AppConfig(api_key="")).api_key == "sk-abcdefghijkl"
    assert apply_update(old, AppConfig(api_key="sk-…ijkl")).api_key == "sk-abcdefghijkl"
    assert apply_update(old, AppConfig(api_key="sk-new-key-0000")).api_key == "sk-new-key-0000"
