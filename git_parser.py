# git_parser.py — модуль анализа Git-репозиториев (Исправленная версия для Windows)
import os
import re
import json
import logging
import time
import shutil
from pathlib import Path
from git import Repo, GitCommandError
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class GitRepoParser:
    """Анализатор структуры и зависимостей Git-репозитория"""
    
    SUPPORTED_BUILD_FILES = {
        'python': ['requirements.txt', 'setup.py', 'pyproject.toml', 'Pipfile'],
        'node': ['package.json', 'yarn.lock', 'pnpm-lock.yaml'],
        'java': ['pom.xml', 'build.gradle', 'build.gradle.kts'],
        'cpp': ['CMakeLists.txt', 'Makefile', 'configure.ac'],
        'dotnet': ['.csproj', '.sln', 'packages.config'],
        'rust': ['Cargo.toml'],
        'go': ['go.mod', 'go.sum'],
    }
    
    def __init__(self, base_temp_dir="temp/repos"):
        self.base_dir = Path(base_temp_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _force_remove(self, path: Path):
        """Надежное удаление папки в Windows с использованием CMD как запасного варианта"""
        max_retries = 5
        for i in range(max_retries):
            try:
                # Попытка стандартного удаления
                if path.is_dir():
                    shutil.rmtree(path, onerror=self._remove_readonly)
                else:
                    path.unlink()
                return # Успех
            except PermissionError as e:
                if i < max_retries - 1:
                    logger.warning(f"⚠️ Файл заблокирован ({path.name}). Попытка {i+1}/{max_retries}. Ждем 3 секунды...")
                    time.sleep(3) # Увеличиваем ожидание
                else:
                    # Если стандартные методы не помогли, пробуем через CMD
                    logger.warning("🔨 Попытка принудительного удаления через CMD...")
                    try:
                        subprocess.run(['cmd', '/c', 'rmdir', '/s', '/q', str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
                        logger.info("✅ Папка удалена через CMD.")
                        return
                    except Exception as cmd_err:
                        raise Exception(f"Не удалось удалить папку {path}. Закройте файлы в проводнике/антивирусе. Ошибка: {e}")
            except Exception as e:
                raise e

    def _remove_readonly(self, func, path, excinfo):
        """Обработчик для снятия атрибута 'только для чтения' при удалении"""
        import stat
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def clone_repo(self, repo_url: str, branch: str = None) -> dict:
        """Клонирует репозиторий и возвращает метаданные"""
        try:
            # Парсинг URL
            parsed = urlparse(repo_url)
            repo_name = Path(parsed.path).stem or "unknown_repo"
            local_path = self.base_dir / repo_name
            
            logger.info(f"📥 Клонирование: {repo_url} → {local_path}")
            
            # === ИСПРАВЛЕНИЕ: Надежная очистка существующей папки ===
            if local_path.exists():
                logger.warning(f"🔄 Папка уже существует. Принудительная очистка...")
                try:
                    self._force_remove(local_path)
                    logger.info("✅ Папка успешно очищена.")
                except Exception as e:
                    logger.error(f"❌ Не удалось удалить папку {local_path}. Закройте файлы в проводнике и попробуйте снова. Ошибка: {e}")
                    return {'success': False, 'error': f'Не удалось очистить папку (файл занят): {str(e)}'}
            # ================================================
            
            # Клонирование
            clone_args = {'depth': 1} if not branch else {'branch': branch, 'single-branch': True}
            repo = Repo.clone_from(repo_url, local_path, **clone_args)
            
            # Сбор метаданных
            metadata = {
                'success': True,
                'path': str(local_path),
                'repo_name': repo_name,
                'branch': repo.active_branch.name if not repo.head.is_detached else 'detached',
                'commit': repo.head.commit.hexsha[:7],
                'files_count': sum(1 for _ in local_path.rglob('*') if _.is_file()),
                'detected_languages': self._detect_languages(local_path),
                'build_systems': self._detect_build_systems(local_path),
                'dependencies': self._parse_dependencies(local_path),
            }
            logger.info(f"✅ Успешно: {metadata['files_count']} файлов, языки: {metadata['detected_languages']}")
            return metadata
            
        except GitCommandError as e:
            logger.error(f"❌ Git error: {e}")
            return {'success': False, 'error': f'Git error: {str(e)}'}
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            return {'success': False, 'error': f'Error: {str(e)}'}
    
    def _detect_languages(self, path: Path) -> list:
        """Определяет языки программирования по расширениям файлов"""
        extensions = {
            '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
            '.java': 'Java', '.cpp': 'C++', '.c': 'C', '.h': 'C/C++ Header',
            '.cs': 'C#', '.rs': 'Rust', '.go': 'Go', '.php': 'PHP',
            '.rb': 'Ruby', '.swift': 'Swift', '.kt': 'Kotlin'
        }
        found = set()
        for ext, lang in extensions.items():
            if any(path.rglob(f'*{ext}')):
                found.add(lang)
        return list(found) if found else ['Unknown']
    
    def _detect_build_systems(self, path: Path) -> list:
        """Определяет системы сборки по наличию конфигурационных файлов"""
        found = []
        for lang, files in self.SUPPORTED_BUILD_FILES.items():
            for file in files:
                if file.startswith('.'):
                    if any(path.rglob(f'*{file}')):
                        found.append(lang)
                        break
                elif (path / file).exists():
                    found.append(lang)
                    break
        return found if found else ['Unknown']
    
    def _parse_dependencies(self, path: Path) -> dict:
        """Парсит файлы зависимостей и извлекает списки пакетов"""
        deps = {}
        
        # Python: requirements.txt
        req_file = path / 'requirements.txt'
        if req_file.exists():
            deps['python'] = self._parse_requirements(req_file)
        
        # Node.js: package.json
        pkg_file = path / 'package.json'
        if pkg_file.exists():
            deps['node'] = self._parse_package_json(pkg_file)
        
        # Java: pom.xml (базовый парсинг)
        pom_file = path / 'pom.xml'
        if pom_file.exists():
            deps['java'] = self._parse_pom(pom_file)
        
        # Rust: Cargo.toml
        cargo_file = path / 'Cargo.toml'
        if cargo_file.exists():
            deps['rust'] = self._parse_cargo(cargo_file)
        
        return deps
    
    def _parse_requirements(self, file_path: Path) -> list:
        """Парсит requirements.txt"""
        deps = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and not line.startswith('-'):
                        # Извлекаем имя пакета (без версий и опций)
                        pkg = re.split(r'[=<>~!@]', line)[0].strip()
                        if pkg:
                            deps.append(pkg)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось парсить {file_path}: {e}")
        return deps
    
    def _parse_package_json(self, file_path: Path) -> dict:
        """Парсит package.json"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return {
                'dependencies': list(data.get('dependencies', {}).keys()),
                'devDependencies': list(data.get('devDependencies', {}).keys()),
            }
        except Exception as e:
            logger.warning(f"⚠️ Не удалось парсить {file_path}: {e}")
            return {}
    
    def _parse_pom(self, file_path: Path) -> list:
        """Базовый парсинг pom.xml (без внешней библиотеки)"""
        deps = []
        try:
            content = file_path.read_text(encoding='utf-8')
            # Простой regex для artifactId в зависимостях
            matches = re.findall(r'<dependency>.*?<artifactId>([^<]+)</artifactId>.*?</dependency>', content, re.DOTALL)
            deps = [m.strip() for m in matches if m.strip()]
        except Exception as e:
            logger.warning(f"⚠️ Не удалось парсить {file_path}: {e}")
        return deps
    
    def _parse_cargo(self, file_path: Path) -> list:
        """Парсит Cargo.toml"""
        deps = []
        try:
            in_deps = False
            for line in file_path.read_text(encoding='utf-8').split('\n'):
                line = line.strip()
                if line == '[dependencies]':
                    in_deps = True
                    continue
                elif line.startswith('[') and in_deps:
                    in_deps = False
                    continue
                if in_deps and '=' in line and not line.startswith('#'):
                    pkg = line.split('=')[0].strip()
                    if pkg and pkg not in ('workspace', 'package'):
                        deps.append(pkg)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось парсить {file_path}: {e}")
        return deps
    
    def cleanup(self, repo_name: str):
        """Удаляет клонированный репозиторий"""
        path = self.base_dir / repo_name
        if path.exists():
            try:
                self._force_remove(path)
                logger.info(f"🗑️ Очищено: {path}")
            except Exception as e:
                logger.error(f"❌ Не удалось очистить {path}: {e}")