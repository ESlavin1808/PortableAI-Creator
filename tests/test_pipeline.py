"""Тесты для pipeline.py (базовые сценарии)"""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import BuildContext, PrepareStep, ArchiveStep
from settings import ProjectSettings


class TestBuildContext:
    def test_context_initialization(self):
        """BuildContext должен корректно инициализироваться."""
        ctx = BuildContext("test-repo", "/tmp/test-path", ProjectSettings())
        assert ctx.repo_name == "test-repo"
        assert ctx.repo_path == "/tmp/test-path"
        assert ctx.failed is False
        assert ctx.logs == []
        assert ctx.output_folder.name == "test-repo_portable"

    def test_log(self):
        """Логирование должно добавлять записи."""
        ctx = BuildContext("test", "/tmp/test", ProjectSettings())
        ctx.log("✅ hello")
        ctx.log("⚠️ warning")
        assert len(ctx.logs) == 2
        assert ctx.logs[0] == "✅ hello"
        assert ctx.logs[1] == "⚠️ warning"

    def test_failed_with(self):
        """Метод failed_with должен устанавливать флаг ошибки."""
        ctx = BuildContext("test", "/tmp/test", ProjectSettings())
        ctx.failed_with("Something went wrong")
        assert ctx.failed is True
        assert ctx.error_msg == "Something went wrong"
        assert "❌" in ctx.logs[0]


class TestPrepareStep:
    def test_prepare_creates_folder(self):
        """PrepareStep должен создавать output папку."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = ProjectSettings()
            settings.output_dir = tmp
            ctx = BuildContext("test-repo", tmp, settings)
            step = PrepareStep()
            result = step.execute(ctx)
            assert result is True
            assert ctx.output_folder.exists()
            assert ctx.output_folder.is_dir()


class TestArchiveStep:
    def test_archive_disabled(self):
        """ArchiveStep не должен создавать архив если компрессия отключена."""
        ctx = BuildContext("test", "/tmp/test", ProjectSettings())
        ctx.settings.enable_compression = False
        step = ArchiveStep()
        result = step.execute(ctx)
        assert result is True
        assert ctx.archive_path is None
