# pipeline.py — Конвейер сборки портативных приложений
import os
import sys
import shutil
import subprocess
import logging
import zipfile
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

from settings import SettingsManager, ProjectSettings
from platform_support import (
    PythonInstaller, LauncherGenerator,
    detect_torch_args, get_incompatible_packages,
)
from patch_manager import PatchManager
from sanity_check import SanityChecker
from error_reporter import ErrorReporter

logger = logging.getLogger(__name__)

ARCHIVE_EXCLUDE_DIRS = {".git", "__pycache__", "node_modules",
                        "_build_temp", "_pip_cache"}

AVAILABLE_PYTHON_VERSIONS = {
    "3.10": "3.10.14",
    "3.11": "3.11.9",
    "3.12": "3.12.4",
    "3.13": "3.13.1",
}
DEFAULT_PYTHON_VERSION = "3.11.9"


# ── Context ────────────────────────────────────────────────────────
class BuildContext:
    """Состояние, передаваемое между шагами конвейера."""

    def __init__(self, repo_name: str, repo_path: str, settings: ProjectSettings):
        self.repo_name = repo_name
        self.repo_path = repo_path
        self.settings = settings
        self.logs: List[str] = []
        self.output_folder: Path = Path(settings.output_dir) / f"{repo_name}_portable"
        self.src_path = Path(repo_path)
        self.patch: Optional[Dict] = None
        self.python_exe: Optional[Path] = None
        self.env: Optional[dict] = None
        self.pip_cmd: Optional[List[str]] = None
        self.archive_path: Optional[Path] = None
        self.sanity_result: Optional[Dict] = None
        self.failed = False
        self.error_msg: Optional[str] = None

    def log(self, msg: str):
        self.logs.append(msg)
        logger.info(msg)

    def failed_with(self, msg: str):
        self.failed = True
        self.error_msg = msg
        self.log(f"❌ {msg}")


# ── Base Step ──────────────────────────────────────────────────────
class BuildStep:
    """Один шаг конвейера сборки."""

    def __init__(self, name: str):
        self.name = name

    def execute(self, ctx: BuildContext) -> bool:
        """Вернуть True для продолжения, False для остановки конвейера."""
        raise NotImplementedError


# ── Шаг 0: Подготовка / патч ──────────────────────────────────────
class PrepareStep(BuildStep):
    """Поиск патча, создание output-папки."""

    def __init__(self):
        super().__init__("Подготовка")

    def execute(self, ctx: BuildContext) -> bool:
        patch_mgr = PatchManager()
        ctx.patch = patch_mgr.find_patch(ctx.repo_name, ctx.repo_path)

        if ctx.patch:
            ctx.log(f"🔧 Найден патч: {ctx.patch.get('description', ctx.repo_name)}")
            patch_env = patch_mgr.get_env_vars(ctx.patch)
            if patch_env:
                ctx.log(f"🔧 Патч добавит переменных окружения: {len(patch_env)}")

        # Очистка старой версии
        if ctx.output_folder.exists():
            ctx.log("🗑️ Удаление старой версии...")
            self._safe_remove(ctx.output_folder)
        ctx.output_folder.mkdir(parents=True)
        return True

    @staticmethod
    def _safe_remove(path: Path):
        for _ in range(5):
            try:
                shutil.rmtree(path)
                return
            except PermissionError:
                time.sleep(2)
        raise Exception(f"Не удалось удалить {path}")


# ── Шаг 1: Копирование исходников ─────────────────────────────────
class CopySourceStep(BuildStep):
    """Копирование файлов из исходного репозитория."""

    def __init__(self):
        super().__init__("Копирование")

    def execute(self, ctx: BuildContext) -> bool:
        ctx.log("📋 Копирование файлов проекта...")
        files_copied = 0
        exclude_names = {'.git', '__pycache__', 'node_modules', '.DS_Store'}
        exclude_exts = {'.pyc', '.pyo'}

        for item in ctx.src_path.rglob('*'):
            try:
                parts = item.relative_to(ctx.src_path).parts
            except ValueError:
                continue
            if any(p in exclude_names for p in parts):
                continue
            if item.suffix in exclude_exts:
                continue
            rel = item.relative_to(ctx.src_path)
            dest = ctx.output_folder / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if item.is_file():
                shutil.copy2(item, dest)
                files_copied += 1

        ctx.log(f"✅ Скопировано {files_copied} файлов.")
        return True


# ── Шаг 2: Определение и установка Python ─────────────────────────
class PythonStep(BuildStep):
    """Определение нужной версии Python и установка portable Python."""

    def __init__(self):
        super().__init__("Python")

    def execute(self, ctx: BuildContext) -> bool:
        override = getattr(ctx.settings, "python_version", "") or ""
        py_version, py_reason = self._detect_required_python(ctx.src_path, override)
        ctx.log(f"🐍 Python {py_version} ({py_reason}).")

        installer = PythonInstaller(ctx.output_folder,
                                    Path(ctx.settings.temp_dir), ctx.logs, py_version)
        ctx.python_exe, ctx.env = installer.setup()
        ctx.pip_cmd = [str(ctx.python_exe.resolve()), "-m", "pip"]

        # CUDA args (патч может переопределить extra-index-url)
        ctx.torch_args = detect_torch_args(ctx.logs)
        if ctx.patch:
            patch_mgr = PatchManager()
            extra_urls = patch_mgr.get_extra_index_urls(ctx.patch)
            if extra_urls:
                ctx.torch_args = []
                for url in extra_urls:
                    ctx.torch_args += ["--extra-index-url", url]
                ctx.log(f"🔧 Патч переопределил index-url: {extra_urls}")
        return True

    @staticmethod
    def _detect_required_python(src_path: Path, override: str = "") -> tuple[str, str]:
        """Определяет версию Python из pyproject.toml или настроек."""
        if override and override in AVAILABLE_PYTHON_VERSIONS.values():
            return override, "задана вручную (полная версия)"
        if override in AVAILABLE_PYTHON_VERSIONS:
            return AVAILABLE_PYTHON_VERSIONS[override], f"задана вручную (minor {override})"

        pyproject = src_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                m = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', content)
                if m:
                    spec = m.group(1)
                    if "<3.11" in spec or "<3.10" in spec or "==3.10" in spec:
                        return AVAILABLE_PYTHON_VERSIONS["3.10"], f"проект требует Python 3.10 ({spec})"
                    if ">=3.12" in spec:
                        return AVAILABLE_PYTHON_VERSIONS["3.12"], f"проект требует Python 3.12+ ({spec})"
                    max_match = re.search(r'<\s*3\.(\d+)', spec)
                    if max_match:
                        max_ver = int(max_match.group(1))
                        if max_ver <= 11:
                            return AVAILABLE_PYTHON_VERSIONS["3.10"], f"ограничено верхней границей {spec}"
                    return AVAILABLE_PYTHON_VERSIONS["3.11"], f"выбрано как оптимальное для ({spec})"
            except Exception as e:
                logger.warning(f"⚠️ Ошибка парсинга pyproject.toml: {e}")

        return DEFAULT_PYTHON_VERSION, "по умолчанию"


# ── Шаг 3: Установка зависимостей ─────────────────────────────────
class InstallDepsStep(BuildStep):
    """Установка pip-зависимостей из requirements.txt / pyproject.toml."""

    def __init__(self):
        super().__init__("Зависимости")

    def execute(self, ctx: BuildContext) -> bool:
        req_file = ctx.src_path / "requirements.txt"
        raw_req = ctx.output_folder / "requirements_raw.txt"
        filtered_req = ctx.output_folder / "requirements_filtered.txt"
        has_req = False

        if req_file.exists():
            source_lines = req_file.read_text(encoding="utf-8").splitlines(True)
            if ctx.patch:
                patch_mgr = PatchManager()
                source_lines = patch_mgr.apply_to_requirements(
                    source_lines, ctx.patch, ctx.logs
                )
            has_req = self._filter_requirements(req_file, filtered_req, ctx.logs, source_lines)

        elif (ctx.src_path / "pyproject.toml").exists():
            extracted = self._extract_deps_from_pyproject(
                ctx.src_path / "pyproject.toml", raw_req, ctx.logs
            )
            if extracted:
                source_lines = raw_req.read_text(encoding="utf-8").splitlines(True)
                if ctx.patch:
                    patch_mgr = PatchManager()
                    source_lines = patch_mgr.apply_to_requirements(
                        source_lines, ctx.patch, ctx.logs
                    )
                has_req = self._filter_requirements(raw_req, filtered_req, ctx.logs, source_lines)

        if has_req:
            ctx.log("⏳ Установка зависимостей...")
            success = self._install_with_retry(
                ctx.pip_cmd, filtered_req, getattr(ctx, 'torch_args', []), ctx.env, ctx.logs
            )
            if not success:
                ctx.failed_with("Не удалось установить зависимости")
                return False

        return True

    @staticmethod
    def _filter_requirements(src_req: Path, dest_req: Path, logs: list,
                             patch_lines: List[str] = None) -> bool:
        """Фильтрует несовместимые пакеты."""
        if not src_req.exists():
            logs.append("⚠️ requirements.txt не найден.")
            return False

        incompatible = get_incompatible_packages()
        skipped = []
        source_lines = patch_lines if patch_lines else src_req.read_text(encoding="utf-8").splitlines(True)

        with open(dest_req, 'w', encoding='utf-8') as f_out:
            for line in source_lines:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    f_out.write(line if line.endswith('\n') else line + '\n')
                    continue
                pkg_name = re.split(r'[>=<!;\[\s]', stripped)[0].lower().replace('_', '-')
                if pkg_name in incompatible:
                    skipped.append(stripped)
                    f_out.write(f"# [SKIPPED] {stripped}\n")
                else:
                    f_out.write(line if line.endswith('\n') else line + '\n')

        if skipped:
            logs.append(f"⚠️ Пропущено {len(skipped)} несовместимых пакетов: {skipped}")
        return True

    @staticmethod
    def _install_with_retry(pip_cmd: list, req_file: Path,
                            torch_args: list, env: dict, logs: list,
                            timeout_seconds: int = 600) -> bool:
        packages = []
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                packages.append(line)

        failed = []
        for pkg in packages:
            cmd = pip_cmd + [
                "install", pkg, "--no-cache-dir",
                "--no-warn-script-location", "--prefer-binary"
            ]
            if torch_args:
                cmd.extend(torch_args)
            try:
                logs.append(f"   ⬇️ {pkg[:60]}...")
                subprocess.run(
                    cmd, env=env, check=True, timeout=timeout_seconds,
                    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
                )
            except subprocess.TimeoutExpired:
                failed.append(pkg)
                logs.append(f"   ⏰ Timeout ({timeout_seconds}s): {pkg}")
            except subprocess.CalledProcessError:
                failed.append(pkg)
                logs.append(f"   ❌ Failed: {pkg}")

        if failed:
            logs.append(f"⚠️ Не удалось установить {len(failed)} пакетов: {failed}")
        logs.append("✅ Установка зависимостей завершена.")
        return True

    @staticmethod
    def _extract_deps_from_pyproject(pyproject_path: Path, dest_req: Path, logs: list) -> bool:
        try:
            content = pyproject_path.read_text(encoding="utf-8")
            m = re.search(r'\[project\].*?dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL)
            if not m:
                logs.append("⚠️ [project.dependencies] не найден.")
                return False
            deps = re.findall(r'["\']([^"\']+)["\']', m.group(1))
            with open(dest_req, 'w', encoding='utf-8') as f:
                for dep in deps:
                    f.write(dep + "\n")
            return True
        except Exception as e:
            logs.append(f"⚠️ Ошибка парсинга pyproject.toml: {e}")
            return False


# ── Шаг 4: Post-install из патча ───────────────────────────────────
class PostInstallStep(BuildStep):
    """Выполнение post-install команд из патча."""

    def __init__(self):
        super().__init__("Post-install")

    def execute(self, ctx: BuildContext) -> bool:
        if not ctx.patch:
            return True
        patch_mgr = PatchManager()
        post_cmds = patch_mgr.get_post_install_commands(ctx.patch)
        for cmd_str in post_cmds:
            ctx.log(f"🔧 Патч: выполняем post-install: {cmd_str}")
            try:
                parts = cmd_str.split()
                if parts[0] == "pip":
                    parts = [str(ctx.python_exe.resolve()), "-m"] + parts
                subprocess.check_call(parts, env=ctx.env, timeout=300,
                                      cwd=str(ctx.output_folder))
            except Exception as e:
                ctx.log(f"⚠️ Post-install ошибка: {e}")
        return True


# ── Шаг 5: Установка проекта как pip-пакета ───────────────────────
class InstallProjectStep(BuildStep):
    """Установка проекта через pip install . если это pip-пакет."""

    def __init__(self):
        super().__init__("Установка проекта")

    def execute(self, ctx: BuildContext) -> bool:
        has_pyproject = (ctx.output_folder / "pyproject.toml").exists()
        has_setup = (ctx.output_folder / "setup.py").exists()
        if not has_pyproject and not has_setup:
            return True

        is_package = False
        if has_pyproject:
            try:
                content = (ctx.output_folder / "pyproject.toml").read_text(encoding="utf-8")
                if "[build-system]" in content and "[project]" in content:
                    is_package = True
            except Exception:
                pass
        if has_setup and not is_package:
            try:
                content = (ctx.output_folder / "setup.py").read_text(encoding="utf-8")
                if ("setuptools" in content or "distutils" in content) and "setup(" in content:
                    is_package = True
            except Exception:
                pass

        if is_package:
            ctx.log("📦 Установка проекта как pip-пакета...")
            try:
                subprocess.check_call(
                    ctx.pip_cmd + ["install", ".", "--no-build-isolation", "--no-deps",
                                   "--no-cache-dir", "--no-warn-script-location"],
                    cwd=str(ctx.output_folder), timeout=300, env=ctx.env
                )
                ctx.log("✅ Проект установлен.")
            except Exception as e:
                ctx.log(f"⚠️ Не удалось установить проект: {e}")
        else:
            ctx.log("ℹ️ setup.py/pyproject.toml найден, но это приложение — пропускаем pip install.")
        return True


# ── Шаг 6: Лаунчеры ───────────────────────────────────────────────
class LauncherStep(BuildStep):
    """Создание bat/sh лаунчеров для запуска."""

    def __init__(self):
        super().__init__("Лаунчеры")

    def execute(self, ctx: BuildContext) -> bool:
        if not ctx.settings.create_launcher:
            return True

        ctx.log("🚀 Создание лаунчеров...")
        entries = self._detect_entry_points(ctx.output_folder, ctx.src_path)
        gen = LauncherGenerator(ctx.output_folder)
        gen.create(entries)
        if ctx.patch:
            self._write_patch_env_file(ctx.output_folder, ctx.patch)
        ctx.log(f"✅ Создано {len(entries) or 1} лаунчеров.")
        return True

    @staticmethod
    def _detect_entry_points(output_dir: Path, src_dir: Path) -> List[Dict]:
        entries = []
        pyproject = output_dir / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                m = re.search(r'\[project\.scripts\](.*?)(\[|\Z)', content, re.DOTALL)
                if m:
                    for line in m.group(1).splitlines():
                        line = line.strip()
                        if '=' in line and not line.startswith('#'):
                            name = re.split(r'\s*=', line)[0].strip().strip(' "\'')
                            if name:
                                entries.append({"name": name, "type": "cli"})
            except Exception:
                pass

        scripts_to_check = [
            "app.py", "main.py", "demo.py", "gradio_app.py", "webui.py",
            "run.py", "server.py", "api.py", "launch.py", "start.py",
            "cli.py", "gui.py", "bot.py", "service.py",
        ]
        subdirs_to_check = ["", "backend", "api", "server", "src", "app", "core"]

        for sub in subdirs_to_check:
            for script in scripts_to_check:
                for base in (output_dir, src_dir):
                    path = base / sub / script
                    if path.exists():
                        rel = str(Path(sub) / script) if sub else script
                        entries.append({"name": rel, "type": "py", "script": str(rel)})
                        break  # один раз за скрипт
        return entries[:5]

    @staticmethod
    def _write_patch_env_file(output_folder: Path, patch: Dict):
        patch_mgr = PatchManager()
        env_vars = patch_mgr.get_env_vars(patch)
        if not env_vars:
            return
        env_file = output_folder / "patch.env"
        lines = ["# Переменные окружения из патча PortableAI Creator\n"]
        for k, v in env_vars.items():
            lines.append(f"{k}={v}\n")
        env_file.write_text("".join(lines), encoding="utf-8")

        for bat in output_folder.glob("run_*.bat"):
            try:
                content = bat.read_text(encoding="utf-8")
                env_block = "\n".join(f'set "{k}={v}"' for k, v in env_vars.items())
                content = content.replace(
                    "@echo off\n",
                    f"@echo off\n:: === PATCH ENV ===\n{env_block}\n:: ===============\n", 1
                )
                bat.write_text(content, encoding="utf-8")
            except Exception:
                pass


# ── Шаг 7: Sanity check ───────────────────────────────────────────
class SanityStep(BuildStep):
    """Проверка работоспособности после сборки."""

    def __init__(self):
        super().__init__("Проверка")

    def execute(self, ctx: BuildContext) -> bool:
        if not getattr(ctx.settings, "run_sanity_check", True):
            return True

        ctx.log("🧪 Запуск sanity check...")
        checker = SanityChecker(ctx.output_folder, ctx.python_exe, ctx.env)
        ctx.sanity_result = checker.run()
        ctx.logs.extend(ctx.sanity_result["logs"])
        if not ctx.sanity_result["success"]:
            ctx.log("⚠️ Sanity check выявил проблемы. Сборка завершена.")
        return True


# ── Шаг 8: Архивация ──────────────────────────────────────────────
class ArchiveStep(BuildStep):
    """Упаковка результата в ZIP."""

    def __init__(self):
        super().__init__("Архивация")

    def execute(self, ctx: BuildContext) -> bool:
        if not ctx.settings.enable_compression:
            return True

        ctx.log("🗜️ Архивация...")
        archive_path = Path(ctx.settings.output_dir) / f"{ctx.repo_name}_portable.zip"
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=ctx.settings.compression_level) as zf:
            for root, dirs, files in os.walk(ctx.output_folder):
                dirs[:] = [d for d in dirs if d not in ARCHIVE_EXCLUDE_DIRS]
                for file in files:
                    fp = Path(root) / file
                    zf.write(fp, fp.relative_to(ctx.output_folder))
        size_mb = archive_path.stat().st_size / 1024 / 1024
        ctx.archive_path = archive_path
        ctx.log(f"✅ Архив: {archive_path.name} ({size_mb:.0f} МБ)")
        return True


# ── Конвейер ───────────────────────────────────────────────────────
class BuildPipeline:
    """Запускает шаги сборки последовательно."""

    def __init__(self, settings_mgr: SettingsManager):
        self.settings_mgr = settings_mgr
        self.reporter = ErrorReporter(
            output_dir=settings_mgr.settings.output_dir,
            logs_dir=settings_mgr.settings.logs_dir
        )
        self.steps: List[BuildStep] = [
            PrepareStep(),
            CopySourceStep(),
            PythonStep(),
            InstallDepsStep(),
            PostInstallStep(),
            InstallProjectStep(),
            LauncherStep(),
            SanityStep(),
            ArchiveStep(),
        ]

    def run(self, repo_name: str, repo_path: str) -> Dict[str, Any]:
        ctx = BuildContext(repo_name, repo_path, self.settings_mgr.settings)

        try:
            for step in self.steps:
                ctx.log(f"▶ {step.name}...")
                ok = step.execute(ctx)
                if not ok or ctx.failed:
                    break

            if ctx.failed:
                report_path = self.reporter.generate(
                    build_logs=ctx.logs, repo_name=repo_name,
                    error_msg=ctx.error_msg,
                    output_folder=ctx.output_folder if ctx.output_folder.exists() else None
                )
                return {
                    "success": False, "logs": ctx.logs,
                    "error": ctx.error_msg,
                    "report_path": str(report_path) if report_path else None,
                }

            return {
                "success": True,
                "logs": ctx.logs,
                "output_path": str(ctx.output_folder),
                "archive_path": str(ctx.archive_path) if ctx.archive_path else None,
                "sanity": ctx.sanity_result,
            }

        except Exception as e:
            logger.exception("Pipeline failed")
            ctx.log(f"❌ Критическая ошибка: {e}")
            report_path = self.reporter.generate(
                build_logs=ctx.logs, repo_name=repo_name, error_msg=str(e),
                output_folder=ctx.output_folder if ctx.output_folder.exists() else None
            )
            return {
                "success": False, "logs": ctx.logs, "error": str(e),
                "report_path": str(report_path) if report_path else None,
            }

    def run_with_callback(self, repo_name: str, repo_path: str,
                          on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """
        Запуск с callback для потоковой передачи логов (для SSE).
        Вызывается для каждого нового сообщения лога.
        """
        ctx = BuildContext(repo_name, repo_path, self.settings_mgr.settings)

        try:
            for step in self.steps:
                msg = f"▶ {step.name}..."
                ctx.log(msg)
                if on_log:
                    on_log(msg)
                ok = step.execute(ctx)
                if not ok or ctx.failed:
                    # Отправляем последние логи
                    if on_log and ctx.logs:
                        for line in ctx.logs[-3:]:
                            on_log(line)
                    break

            if ctx.failed:
                if on_log:
                    on_log(f"❌ {ctx.error_msg}")
                return {
                    "success": False, "logs": ctx.logs, "error": ctx.error_msg,
                }

            if on_log:
                on_log("✅ Сборка завершена!")
            return {
                "success": True, "logs": ctx.logs,
                "output_path": str(ctx.output_folder),
                "archive_path": str(ctx.archive_path) if ctx.archive_path else None,
                "sanity": ctx.sanity_result,
            }

        except Exception as e:
            logger.exception("Pipeline failed")
            ctx.log(f"❌ Критическая ошибка: {e}")
            if on_log:
                on_log(f"❌ {e}")
            return {
                "success": False, "logs": ctx.logs, "error": str(e),
            }
