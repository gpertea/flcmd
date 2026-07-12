from flcmd import config


def test_roundtrip_types(isolated_config):
    config.save({"window": {"w": 1000, "h": 640.5, "max": True},
                 "editor": {"command": "code -w"},
                 "left": {"path": "/home/x", "rev": False}})
    cfg = config.load()
    assert cfg["window"]["w"] == 1000
    assert cfg["window"]["h"] == 640.5
    assert cfg["window"]["max"] is True
    assert cfg["left"]["rev"] is False
    assert cfg["editor"]["command"] == "code -w"
    assert config.config_file().endswith("flcmd/flcmd.ini")


def test_update_section(isolated_config):
    config.save({"viewer": {"size": 12}, "left": {"path": "/a"}})
    config.update("viewer", {"size": 14, "wrap": True})
    cfg = config.load()
    assert cfg["viewer"] == {"size": 14, "wrap": True}
    assert cfg["left"]["path"] == "/a"  # other sections untouched


def test_missing_file(isolated_config):
    assert config.load() == {}
