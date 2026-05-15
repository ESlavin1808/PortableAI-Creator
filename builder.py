# builder.py — Фасад для конвейера сборки (делегирует в pipeline.py)
import logging
from typing import Dict, Any, Optional, Callable
from pathlib import Path

from settings import SettingsManager
from pipeline import BuildPipeline, BuildStep, BuildContext, PrepareStep  # noqa
from error_reporter import ErrorReporter

logger = logging.getLogger(__name__)


class PortableBuilder:
    """
    Фасад для сборки портативных приложений.
    Вся логика шагов — в pipeline.py.
    """

    def __init__(self, settings_mgr: SettingsManager):
        self.settings = settings_mgr.settings
        self.pipeline = BuildPipeline(settings_mgr)
        self.base_output = Path(self.settings.output_dir)
        self.base_output.mkdir(parents=True, exist_ok=True)

    def build_from_repo(self, repo_name: str, repo_path: str,
                        build_type: str = "venv") -> Dict[str, Any]:
        """
        Запустить сборку портативного приложения из репозитория.
        Возвращает словарь с результатами (success, logs, archive_path, error и т.д.)
        """
        return self.pipeline.run(repo_name, repo_path)

    def build_stream(self, repo_name: str, repo_path: str,
                     on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """
        Запустить сборку с потоковой передачей логов через callback.
        Используется для SSE/WebSocket-трансляции.
        """
        return self.pipeline.run_with_callback(repo_name, repo_path, on_log=on_log)
