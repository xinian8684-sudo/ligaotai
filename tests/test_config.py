from ligaotai.config import AppConfig, library_path, load_config, save_config


def test_default_when_no_file(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.library_dir == ""
    assert library_path(cfg, tmp_path) == tmp_path / "书库"


def test_save_and_load(tmp_path):
    save_config(AppConfig(library_dir=str(tmp_path / "别处")), tmp_path)
    cfg = load_config(tmp_path)
    assert library_path(cfg, tmp_path) == tmp_path / "别处"
