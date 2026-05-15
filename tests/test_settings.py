"""Тесты для settings.py"""
import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from settings import SettingsManager, ProjectSettings


class TestProjectSettings:
    def test_default_values(self):
        """Дефолтные настройки должны быть разумными."""
        s = ProjectSettings()
        assert s.python_version == "3.11"
        assert s.install_timeout == 600
        assert s.enable_compression is True
        assert s.compression_level == 6
        assert s.run_sanity_check is True
        assert s.create_launcher is True
        assert s.git_shallow_clone is True
        assert s.output_dir == "output/portable"

    def test_save_and_load(self):
        """Сохранение и загрузка должны восстанавливать все поля."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = f.name

        try:
            original = ProjectSettings()
            original.python_version = "3.12"
            original.install_timeout = 900
            original.enable_compression = False

            original.save(tmp_path)

            loaded = ProjectSettings.load(tmp_path)
            assert loaded.python_version == "3.12"
            assert loaded.install_timeout == 900
            assert loaded.enable_compression is False
            # Поля, которые не меняли, должны быть по умолчанию
            assert loaded.output_dir == "output/portable"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_get_method(self):
        """Метод get() должен работать как dict.get() для Jinja2-совместимости."""
        s = ProjectSettings()
        assert s.get("python_version") == "3.11"
        assert s.get("non_existent", "fallback") == "fallback"
        assert s.get("non_existent") is None

    def test_load_nonexistent(self):
        """Загрузка несуществующего файла должна создавать дефолтный объект."""
        s = ProjectSettings.load("/tmp/nonexistent_config_deadbeef.json")
        assert isinstance(s, ProjectSettings)
        assert s.python_version == "3.11"


class TestSettingsManager:
    def test_manager_creates_settings(self):
        """SettingsManager должен иметь settings объект."""
        mgr = SettingsManager()
        assert isinstance(mgr.settings, ProjectSettings)

    def test_validate_paths(self):
        """validate_paths должен создавать папки и возвращать список ошибок."""
        mgr = SettingsManager()
        errors = mgr.validate_paths()
        assert isinstance(errors, list)

    def test_save_load_cycle(self):
        """Цикл save/load через менеджер не должен терять данные."""
        mgr = SettingsManager()
        original_output = mgr.settings.output_dir
        mgr.settings.output_dir = "/tmp/test_portable_output"
        mgr.save()

        mgr2 = SettingsManager()
        assert mgr2.settings.output_dir == "/tmp/test_portable_output"

        # Восстанавливаем
        mgr.settings.output_dir = original_output
        mgr.save()
