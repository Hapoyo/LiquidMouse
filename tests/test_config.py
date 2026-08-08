"""Config: generazione del PIN e regola anti-rigenerazione sugli upgrade."""

import json

from liquidmouse.config import Config
from liquidmouse.security.auth import pin_matches


def _config_at(tmp_path):
    return Config(path=tmp_path / "LiquidControl" / "config.json")


class TestFirstRun:
    def test_creates_file_and_pin(self, tmp_path):
        cfg = _config_at(tmp_path)
        data = cfg.load()
        assert cfg.path.exists()
        assert data["pin_plain"]
        assert pin_matches(data["pin_plain"], data["pin_hash"])

    def test_creates_parent_directories(self, tmp_path):
        cfg = Config(path=tmp_path / "a" / "b" / "config.json")
        cfg.load()
        assert cfg.path.exists()


class TestReload:
    def test_pin_survives_a_restart(self, tmp_path):
        first = _config_at(tmp_path)
        pin = first.load()["pin_plain"]

        second = _config_at(tmp_path)
        assert second.load()["pin_plain"] == pin

    def test_extra_keys_do_not_regenerate_the_pin(self, tmp_path):
        # Un upgrade che aggiunge campi non deve invalidare il PIN già
        # memorizzato sui telefoni.
        cfg = _config_at(tmp_path)
        pin = cfg.load()["pin_plain"]
        cfg["ssl_cert"] = "roba"
        cfg.save()

        reloaded = _config_at(tmp_path)
        data = reloaded.load()
        assert data["pin_plain"] == pin
        assert data["ssl_cert"] == "roba"

    def test_malformed_file_regenerates(self, tmp_path):
        cfg = _config_at(tmp_path)
        cfg.load()
        cfg.path.write_text("{ questo non e' json", encoding="utf-8")

        data = _config_at(tmp_path).load()
        assert pin_matches(data["pin_plain"], data["pin_hash"])

    def test_missing_pin_hash_regenerates(self, tmp_path):
        cfg = _config_at(tmp_path)
        cfg.load()
        cfg.path.write_text(json.dumps({"altro": 1}), encoding="utf-8")

        data = _config_at(tmp_path).load()
        assert "pin_hash" in data
        assert pin_matches(data["pin_plain"], data["pin_hash"])


class TestSaveIsNonFatal:
    def test_unwritable_path_does_not_raise(self, tmp_path):
        # La config vive sotto %APPDATA%: se non è scrivibile l'app deve
        # comunque partire, col PIN valido per la sessione corrente.
        cfg = Config(path=tmp_path / "config.json")
        cfg.data = {"pin_plain": "x"}
        cfg.path.mkdir()  # una directory dove ci si aspetta un file
        cfg.save()  # non deve sollevare
