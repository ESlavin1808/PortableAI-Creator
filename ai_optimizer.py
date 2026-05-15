# ai_optimizer.py — Модуль AI-оптимизации размера
import os
import shutil
import logging
from pathlib import Path
from typing import List, Set
import fnmatch

logger = logging.getLogger(__name__)

class AIOptimizer:
    """Оптимизатор размера портативных приложений"""
    
    # Паттерны файлов, которые МОЖНО безопасно удалить в портативной версии
    SAFE_TO_REMOVE_PATTERNS = [
        # Тесты и примеры
        "*test*.py", "*_test.py", "test_*", "tests/", "examples/", "demos/",
        # Документация
        "*.md", "*.rst", "*.txt", "docs/", "readme*", "license*", "changelog*",
        # Исходный код библиотек (оставляем только скомпилированные .pyc/.pyd)
        "*.c", "*.cpp", "*.h", "*.hpp", "*.pyx", "*.pxd",
        # Системные файлы разработки
        ".git/", ".gitignore", ".github/", ".vscode/", ".idea/", "*.swp", "*.swo",
        # Кэш и временные файлы
        "__pycache__/", "*.pyc", "*.pyo", "*.egg-info/", "dist/", "build/",
        # Излишние данные моделей (если они огромные и не используются напрямую)
        "*.bin.bak", "*.tmp", "*.log"
    ]
    
    # Папки, которые НИКОГДА нельзя трогать (критичные для работы Python)
    CRITICAL_FOLDERS = [
        "venv", "Lib", "Scripts", "DLLs", "Include",  # Структура venv
        "site-packages"  # Библиотеки
    ]
    
    # Файлы, которые нужно сохранить обязательно
    CRITICAL_FILES = [
        "requirements.txt", "setup.py", "pyproject.toml", 
        "*.exe", "*.dll", "*.pyd", "*.so", "*.dylib"
    ]

    def __init__(self, confidence_threshold: float = 0.75):
        self.confidence_threshold = confidence_threshold
        self.stats = {
            'files_scanned': 0,
            'files_removed': 0,
            'bytes_saved': 0,
            'folders_removed': 0
        }

    def optimize(self, project_path: str) -> dict:
        """
        Основная функция оптимизации.
        Возвращает статистику изменений.
        """
        path = Path(project_path)
        if not path.exists():
            logger.error(f"Путь не найден: {path}")
            return {'success': False, 'error': 'Path not found'}
        
        logger.info(f"🤖 Запуск AI-оптимизации для: {path}")
        self.stats = {'files_scanned': 0, 'files_removed': 0, 'bytes_saved': 0, 'folders_removed': 0}
        
        try:
            # 1. Очистка кэша компиляции (безопасно всегда)
            self._clean_pycache(path)
            
            # 2. Удаление тестов и документации (высокая уверенность)
            self._remove_unsafe_patterns(path, confidence=0.95)
            
            # 3. Анализ "тяжелых" файлов (имитация AI решения)
            self._analyze_and_trim_large_files(path)
            
            logger.info(f"✅ Оптимизация завершена. Сэкономлено: {self._format_size(self.stats['bytes_saved'])}")
            return {
                'success': True,
                'stats': self.stats,
                'message': f"Удалено файлов: {self.stats['files_removed']}, сэкономлено места: {self._format_size(self.stats['bytes_saved'])}"
            }
            
        except Exception as e:
            logger.exception("Error during AI optimization")
            return {'success': False, 'error': str(e)}

    def _clean_pycache(self, path: Path):
        """Удаляет все __pycache__ и .pyc файлы"""
        for pycache in path.rglob("__pycache__"):
            try:
                size = self._get_dir_size(pycache)
                shutil.rmtree(pycache)
                self.stats['folders_removed'] += 1
                self.stats['bytes_saved'] += size
                logger.debug(f"🗑️ Удален __pycache__: {pycache}")
            except Exception as e:
                logger.warning(f"Не удалось удалить {pycache}: {e}")
        
        for pyc in path.rglob("*.pyc"):
            try:
                size = pyc.stat().st_size
                pyc.unlink()
                self.stats['files_removed'] += 1
                self.stats['bytes_saved'] += size
            except Exception:
                pass

    def _remove_unsafe_patterns(self, path: Path, confidence: float = 0.9):
        """Удаляет файлы по паттернам, если уверенность выше порога"""
        if confidence < self.confidence_threshold:
            return
            
        for pattern in self.SAFE_TO_REMOVE_PATTERNS:
            if pattern.endswith('/'):
                # Это папка
                folder_name = pattern.rstrip('/')
                for folder in path.rglob(folder_name):
                    # Проверка: не является ли папка критической (например, site-packages/tests)
                    if self._is_critical_path(folder):
                        continue
                    
                    try:
                        size = self._get_dir_size(folder)
                        shutil.rmtree(folder)
                        self.stats['folders_removed'] += 1
                        self.stats['bytes_saved'] += size
                        self.stats['files_removed'] += 1 # считаем папку как 1 объект
                        logger.debug(f"🗑️ Удалена папка по паттерну '{pattern}': {folder}")
                    except Exception as e:
                        logger.warning(f"Ошибка удаления папки {folder}: {e}")
            else:
                # Это файл
                for file in path.rglob(pattern):
                    if self._is_critical_path(file):
                        continue
                    
                    try:
                        size = file.stat().st_size
                        file.unlink()
                        self.stats['files_removed'] += 1
                        self.stats['bytes_saved'] += size
                        logger.debug(f"🗑️ Удален файл по паттерну '{pattern}': {file}")
                    except Exception as e:
                        logger.warning(f"Ошибка удаления файла {file}: {e}")

    def _analyze_and_trim_large_files(self, path: Path):
        """Имитация AI анализа: поиск очень больших файлов, которые могут быть лишними"""
        # Ищем файлы больше 50 МБ, которые не являются .whl, .exe, .dll, .bin (модели)
        size_threshold = 50 * 1024 * 1024  # 50 MB
        
        safe_extensions = {'.whl', '.exe', '.dll', '.pyd', '.so', '.bin', '.safetensors', '.pth', '.pt', '.onnx'}
        
        for file in path.rglob('*'):
            if not file.is_file():
                continue
            
            self.stats['files_scanned'] += 1
            
            try:
                if file.stat().st_size > size_threshold:
                    ext = file.suffix.lower()
                    name = file.name.lower()
                    
                    # Если расширение безопасное или имя содержит 'model', пропускаем
                    if ext in safe_extensions or 'model' in name or 'checkpoint' in name:
                        continue
                    
                    # Если файл лежит в папке site-packages и не является архивом колеса - подозрительно
                    if 'site-packages' in str(file) and ext not in {'.whl', '.zip'}:
                        # Здесь можно добавить более сложную логику AI
                        logger.warning(f"️ Найден большой подозрительный файл ({self._format_size(file.stat().st_size)}): {file}")
                        # Пока только логируем, не удаляем автоматически, чтобы не сломать библиотеки
                        # В реальной AI системе здесь был бы вызов модели классификации
            except Exception:
                pass

    def _is_critical_path(self, path: Path) -> bool:
        """Проверяет, является ли путь критическим для работы"""
        path_str = str(path).lower()
        
        # Проверка на вхождение критических папок
        for critical in self.CRITICAL_FOLDERS:
            if critical.lower() in path_str:
                # Дополнительная проверка: если это tests ВНУТРИ site-packages, то можно удалять
                if 'tests' in path_str and 'site-packages' in path_str:
                    return False 
                return True
        
        # Проверка на критические расширения файлов
        for pattern in self.CRITICAL_FILES:
            if fnmatch.fnmatch(path.name, pattern):
                return True
                
        return False

    def _get_dir_size(self, path: Path) -> int:
        """Вычисляет размер папки"""
        total = 0
        try:
            for entry in path.rglob('*'):
                if entry.is_file():
                    total += entry.stat().st_size
        except Exception:
            pass
        return total

    def _format_size(self, size_bytes: int) -> str:
        """Человекочитаемый формат размера"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"