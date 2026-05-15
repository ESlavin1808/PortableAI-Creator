# validator.py — Валидация portable-сборки
import os
import sys
import subprocess
import re
from pathlib import Path
from typing import Dict, Any, List


class BuildValidator:
    def __init__(self, output_folder: Path, python_exe: Path, env: dict):
        self.folder = output_folder
        self.python = python_exe
        self.env = env
        self.results: List[Dict] = []

    # ------------------------------------------------------------------ #
    #  Публичный метод                                                     #
    # ------------------------------------------------------------------ #

    def validate(self) -> Dict[str, Any]:
        """
        Запускает все проверки и возвращает итоговый отчёт.
        """
        self.results = []

        self._check_python()
        self._check_pip()
        self._check_entrypoints()
        self._check_package_importable()
        self._check_launchers()
        self._check_required_files()

        passed  = [r for r in self.results if r["status"] == "ok"]
        warnings = [r for r in self.results if r["status"] == "warn"]
        failed  = [r for r in self.results if r["status"] == "fail"]

        success = len(failed) == 0
        summary = (
            f"✅ {len(passed)} passed, "
            f"⚠️ {len(warnings)} warnings, "
            f"❌ {len(failed)} failed"
        )

        return {
            "success": success,
            "summary": summary,
            "results": self.results,
            "logs": self._format_logs(),
        }

    # ------------------------------------------------------------------ #
    #  Проверки                                                            #
    # ------------------------------------------------------------------ #

    def _check_python(self):
        """Python запускается и возвращает правильную версию."""
        try:
            out = subprocess.check_output(
                [str(self.python), "--version"],
                stderr=subprocess.STDOUT,
                env=self.env,
                timeout=10,
            ).decode().strip()
            self._ok("python", f"Portable Python работает: {out}")
        except Exception as e:
            self._fail("python", f"python.exe не запускается: {e}")

    def _check_pip(self):
        """pip доступен и указывает на portable."""
        try:
            out = subprocess.check_output(
                [str(self.python), "-m", "pip", "--version"],
                stderr=subprocess.STDOUT,
                env=self.env,
                timeout=10,
            ).decode().strip()

            # Убеждаемся что pip из portable, а не системного
            if str(self.folder) in out or "python_portable" in out:
                self._ok("pip", f"pip изолирован: {out}")
            else:
                self._warn("pip", f"pip может использовать системный путь: {out}")
        except Exception as e:
            self._fail("pip", f"pip недоступен: {e}")

    def _check_entrypoints(self):
        """Все CLI entrypoints из pyproject.toml существуют в Scripts/."""
        pyproject = self.folder / "pyproject.toml"
        if not pyproject.exists():
            return

        try:
            content = pyproject.read_text(encoding="utf-8")
            m = re.search(r"\[project\.scripts\](.*?)(\[|\Z)", content, re.DOTALL)
            if not m:
                return

            scripts_dir = self.folder / "python_portable" / "Scripts"
            for line in m.group(1).splitlines():
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                name = re.split(r"\s*=", line)[0].strip().strip("\"'")
                if not name:
                    continue

                ext = ".exe" if sys.platform == "win32" else ""
                exe = scripts_dir / f"{name}{ext}"
                if exe.exists():
                    self._ok(f"entrypoint:{name}", f"{name} найден: {exe.name}")
                else:
                    self._fail(f"entrypoint:{name}", f"{name} не найден в Scripts/")
        except Exception as e:
            self._warn("entrypoints", f"Ошибка парсинга pyproject.toml: {e}")

    def _check_package_importable(self):
        """Главный пакет проекта реально импортируется."""
        pkg_name = self._detect_package_name()
        if not pkg_name:
            self._warn("import", "Не удалось определить имя пакета для проверки импорта.")
            return

        try:
            out = subprocess.check_output(
                [str(self.python), "-c", f"import {pkg_name}; print({pkg_name}.__file__)"],
                stderr=subprocess.STDOUT,
                env=self.env,
                timeout=30,
            ).decode().strip()

            # Проверяем что импортируется из portable, а не из системы
            if str(self.folder) in out:
                self._ok("import", f"import {pkg_name} → {out}")
            else:
                self._warn("import", f"import {pkg_name} работает, но путь вне portable: {out}")
        except subprocess.CalledProcessError as e:
            error = e.output.decode().strip().splitlines()[-1] if e.output else str(e)
            self._fail("import", f"import {pkg_name} упал: {error}")
        except Exception as e:
            self._fail("import", f"Ошибка при проверке импорта: {e}")

    def _check_launchers(self):
        """Лаунчеры существуют и не содержат абсолютных путей."""
        bat_files = list(self.folder.glob("run_*.bat")) + list(self.folder.glob("run_*.sh"))

        if not bat_files:
            self._warn("launchers", "Лаунчеры не найдены.")
            return

        for bat in bat_files:
            content = bat.read_text(encoding="utf-8", errors="ignore")
            # Ищем абсолютные пути Windows вида C:\ или D:\
            abs_paths = re.findall(r'[A-Za-z]:\\[^"\'%\s]+', content)
            # Фильтруем системные пути которые допустимы (%SystemRoot% и т.д.)
            abs_paths = [p for p in abs_paths if "SystemRoot" not in p and "Windows" not in p]

            if abs_paths:
                self._warn(
                    f"launcher:{bat.name}",
                    f"Содержит абсолютные пути (сломается при переносе): {abs_paths[0]}"
                )
            else:
                self._ok(f"launcher:{bat.name}", f"{bat.name} использует относительные пути.")

    def _check_required_files(self):
        """Проверяет наличие ключевых файлов сборки."""
        checks = [
            (self.folder / "python_portable" / "python.exe", "critical"),
            (self.folder / "python_portable" / "Scripts" / "pip.exe", "critical"),
            (self.folder / "python_portable" / "Lib" / "site-packages", "critical"),
            (self.folder / "requirements_filtered.txt", "info"),
        ]
        for path, severity in checks:
            if path.exists():
                self._ok(f"file:{path.name}", f"{path.name} присутствует.")
            elif severity == "critical":
                self._fail(f"file:{path.name}", f"Критический файл отсутствует: {path}")
            else:
                self._warn(f"file:{path.name}", f"Файл отсутствует: {path.name}")

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                             #
    # ------------------------------------------------------------------ #

    def _detect_package_name(self) -> str:
        """Определяет имя главного пакета из pyproject.toml или структуры папок."""
        pyproject = self.folder / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
                if m:
                    # pyproject name может быть kebab-case, пакет — snake_case
                    return m.group(1).replace("-", "_")
            except Exception:
                pass

        # Fallback: ищем папку с __init__.py в корне
        for item in self.folder.iterdir():
            if item.is_dir() and (item / "__init__.py").exists():
                if item.name not in {"test", "tests", "docs", "examples"}:
                    return item.name

        return ""

    def _ok(self, key: str, msg: str):
        self.results.append({"key": key, "status": "ok", "msg": f"✅ {msg}"})

    def _warn(self, key: str, msg: str):
        self.results.append({"key": key, "status": "warn", "msg": f"⚠️ {msg}"})

    def _fail(self, key: str, msg: str):
        self.results.append({"key": key, "status": "fail", "msg": f"❌ {msg}"})

    def _format_logs(self) -> List[str]:
        return [r["msg"] for r in self.results]