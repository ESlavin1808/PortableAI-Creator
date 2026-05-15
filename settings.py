# settings.py
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class ProjectSettings:
    """Настройки проекта PortableAI Creator"""

    # Пути
    output_dir: str = "output/portable"
    temp_dir: str = "temp"
    cache_dir: str = "temp/cache"
    logs_dir: str = "logs"

    # Git
    git_shallow_clone: bool = True
    git_default_branch: str = "main"
    git_timeout_seconds: int = 300

    # Фильтры файлов
    include_patterns: List[str] = field(default_factory=lambda: [
        "*.exe", "*.dll", "*.py", "*.pyd", "*.so", "*.dylib",
        "requirements.txt", "package.json", "setup.py", "pyproject.toml"
    ])
    exclude_patterns: List[str] = field(default_factory=lambda: [
        "*.git*", "*.md", "docs/*", "tests/*", "*.log",
        "__pycache__", "*.pyc", ".env", "*.tmp", "*.bak"
    ])

    # Сборка
    python_version: str = "3.11"          # ← было getattr-костылём
    enable_compression: bool = True
    compression_level: int = 6
    enable_ai_optimization: bool = False
    ai_confidence_threshold: float = 0.75
    create_launcher: bool = True
    strip_debug_symbols: bool = True
    run_sanity_check: bool = True          # ← было в allowed_keys, но не в датаклассе

    # Тайм-ауты
    install_timeout: int = 600

    # Сеть
    allowed_hosts: str = "127.0.0.1,localhost"
    use_proxy: bool = False
    proxy_http: str = ""
    proxy_https: str = ""
    verify_ssl: bool = True

    # Логирование
    log_level: str = "INFO"
    log_to_file: bool = True
    log_max_size_mb: int = 10

    # AI-модели
    ai_model_path: Optional[str] = None
    enable_telemetry: bool = False

    # ------------------------------------------------------------------ #

    def get(self, key: str, default=None):
        """Совместимость с dict-стилем обращения из шаблонов Jinja2."""
        return getattr(self, key, default)

    def save(self, filepath: str = "config.json") -> bool:
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Настройки сохранены: {filepath}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения настроек: {e}")
            return False

    @classmethod
    def load(cls, filepath: str = "config.json") -> "ProjectSettings":
        if not Path(filepath).exists():
            logger.info(f"📄 config.json не найден, используем дефолтные настройки")
            return cls()
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            instance = cls()
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            logger.info(f"📥 Настройки загружены: {filepath}")
            return instance
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки настроек, используем дефолтные: {e}")
            return cls()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectSettings":
        instance = cls()
        for key, value in data.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        return instance


class SettingsManager:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.settings = ProjectSettings.load(config_path)

    def get(self, key: str, default=None):
        return getattr(self.settings, key, default)

    def set(self, key: str, value: Any, autosave: bool = True) -> bool:
        if not hasattr(self.settings, key):
            logger.warning(f"⚠️ Неизвестная настройка игнорируется: {key}")
            return False
        setattr(self.settings, key, value)
        if autosave:
            return self.save()
        return True

    def save(self) -> bool:
        return self.settings.save(self.config_path)

    def reset_to_defaults(self) -> bool:
        self.settings = ProjectSettings()
        return self.save()

    def validate_paths(self) -> list:
        errors = []
        for path_str in [
            self.settings.output_dir,
            self.settings.temp_dir,
            self.settings.cache_dir,
            self.settings.logs_dir,
        ]:
            try:
                Path(path_str).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Не удалось создать папку {path_str}: {e}")
        return errors