"""Config: generazione del PIN e regola anti-rigenerazione sugli upgrade."""

import json

from liquidmouse.config import Config, migrate_legacy
from liquidmouse.security.auth import pin_matches


def _config_at(tmp_path):
    return Config(path=tmp_path / "LiquidMouse" / "config.json")


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


class TestMigrazioneDaLiquidControl:
    """Fino alla 2.5.x la config stava in %APPDATA%/LiquidControl."""

    def _vecchia(self, tmp_path, contenuto: dict):
        vecchio = tmp_path / "LiquidControl" / "config.json"
        vecchio.parent.mkdir()
        vecchio.write_text(json.dumps(contenuto), encoding="utf-8")
        return vecchio

    def test_copia_la_config_vecchia(self, tmp_path):
        self._vecchia(tmp_path, {"pin_plain": "abc", "pin_hash": "h"})
        nuovo = tmp_path / "LiquidMouse" / "config.json"
        assert migrate_legacy(nuovo, base=tmp_path)
        assert json.loads(nuovo.read_text(encoding="utf-8"))["pin_plain"] == "abc"

    def test_lascia_al_suo_posto_la_vecchia(self, tmp_path):
        vecchio = self._vecchia(tmp_path, {"pin_plain": "abc"})
        migrate_legacy(tmp_path / "LiquidMouse" / "config.json", base=tmp_path)
        assert vecchio.exists()

    def test_non_sovrascrive_una_config_nuova(self, tmp_path):
        self._vecchia(tmp_path, {"pin_plain": "vecchio"})
        nuovo = tmp_path / "LiquidMouse" / "config.json"
        nuovo.parent.mkdir()
        nuovo.write_text(json.dumps({"pin_plain": "nuovo"}), encoding="utf-8")
        assert not migrate_legacy(nuovo, base=tmp_path)
        assert json.loads(nuovo.read_text(encoding="utf-8"))["pin_plain"] == "nuovo"

    def test_niente_da_migrare(self, tmp_path):
        assert not migrate_legacy(tmp_path / "LiquidMouse" / "config.json", base=tmp_path)

    def test_il_pin_sopravvive_al_cambio_di_nome(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        vecchia = Config(path=tmp_path / "LiquidControl" / "config.json")
        pin = vecchia.load()["pin_plain"]
        assert Config().load()["pin_plain"] == pin
