"""Тесты для patch_manager.py"""
import json
import tempfile
from pathlib import Path
import sys

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from patch_manager import PatchManager


class TestPatchManager:
    def setup_method(self):
        self.mgr = PatchManager()

    def test_find_patch_by_name(self):
        """Должен найти встроенный патч по имени репозитория."""
        patch = self.mgr.find_patch("cosyvoice")
        assert patch is not None
        # cosyvoice patch может быть перезаписан внешним JSON, проверяем наличие
        assert isinstance(patch, dict)

    def test_find_patch_case_insensitive(self):
        """Поиск должен быть регистронезависимым."""
        patch = self.mgr.find_patch("ComfyUI")
        assert patch is not None
        assert patch.get("description", "").startswith("ComfyUI")

    def test_find_patch_unknown_repo(self):
        """Неизвестный репозиторий должен вернуть None."""
        patch = self.mgr.find_patch("some-random-repo-12345")
        assert patch is None

    def test_known_repos_list(self):
        """Список известных репозиториев должен содержать популярные проекты."""
        repos = self.mgr.list_known_repos()
        names = [r["name"] for r in repos]
        assert "cosyvoice" in names
        assert "comfyui" in names
        assert "whisper" in names
        assert "ollama" in names
        assert "stable-diffusion-webui" in names

    def test_get_env_vars(self):
        """Должен возвращать переменные окружения из патча."""
        patch = self.mgr.find_patch("cosyvoice")
        env = self.mgr.get_env_vars(patch)
        assert "HF_HOME" in env
        assert env["HF_HOME"] == "./models"

    def test_get_env_vars_empty(self):
        """Патч без env_vars должен вернуть пустой словарь."""
        patch = self.mgr.find_patch("comfyui")
        env = self.mgr.get_env_vars(patch)
        assert env == {}

    def test_extra_index_urls(self):
        """Должен возвращать extra_index_urls из патча."""
        patch = self.mgr.find_patch("comfyui")
        urls = self.mgr.get_extra_index_urls(patch)
        assert len(urls) > 0
        assert "download.pytorch.org" in urls[0]

    def test_get_post_install_commands(self):
        """Должен возвращать список post-install команд."""
        patch = self.mgr.find_patch("cosyvoice")
        cmds = self.mgr.get_post_install_commands(patch)
        assert isinstance(cmds, list)
        # Может быть пустым — просто проверяем тип

    def test_load_external_patch(self):
        """Должен загружать внешний JSON-патч из папки patches/."""
        # Создаём временный файл с repo_name в названии (stem = имя патча)
        patch_data = {
            "description": "Test Repo",
            "env_vars": {"TEST_VAR": "hello"}
        }
        patch_path = Path("patches") / "test-repo.json"
        patch_path.write_text(json.dumps(patch_data), encoding="utf-8")

        try:
            # Пересоздаём менеджер, чтобы он загрузил новый патч
            mgr2 = PatchManager()
            patch = mgr2.find_patch("test-repo")
            assert patch is not None
            assert patch["description"] == "Test Repo"
            assert mgr2.get_env_vars(patch)["TEST_VAR"] == "hello"
        finally:
            patch_path.unlink(missing_ok=True)
