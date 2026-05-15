# preflight.py — Проверка системных требований перед сборкой
import os
import sys
import shutil
import subprocess
import platform
import ctypes
from pathlib import Path
from typing import Dict, List, Any


class PreflightChecker:
    """Проверяет готовность системы к сборке портативного приложения."""

    MIN_FREE_GB = 15  # Минимум свободного места для сборки (ГБ)
    MIN_FREE_AI_GB = 30  # Для AI-проектов (torch и т.д.)

    def __init__(self, output_dir: str = "output/portable", temp_dir: str = "temp"):
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir)
        self.results: List[Dict] = []
        self.warnings: List[str] = []
        self.errors: List[str] = []

    # ------------------------------------------------------------------ #
    #  Публичный метод                                                     #
    # ------------------------------------------------------------------ #

    def run(self, repo_path: str = None, is_ai_project: bool = True) -> Dict[str, Any]:
        """
        Запускает все pre-flight проверки.
        Возвращает {'ok': bool, 'errors': [...], 'warnings': [...], 'results': [...]}
        """
        self.results = []
        self.warnings = []
        self.errors = []

        self._check_disk_space(is_ai_project)
        self._check_git()
        self._check_python()
        self._check_internet()
        self._check_output_writable()

        # Windows-специфичные проверки
        if sys.platform == "win32":
            self._check_vcredist()
            self._check_path_length()
            self._check_antivirus_conflict()

        if repo_path:
            self._check_repo_path(repo_path)

        ok = len(self.errors) == 0
        return {
            "ok": ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "results": self.results,
            "html": self._render_html()
        }

    # ------------------------------------------------------------------ #
    #  Проверки                                                            #
    # ------------------------------------------------------------------ #

    def _check_disk_space(self, is_ai: bool):
        """Проверяет свободное место на диске."""
        min_gb = self.MIN_FREE_AI_GB if is_ai else self.MIN_FREE_GB
        try:
            # Проверяем диск, где находится output
            check_path = self.output_dir.parent if self.output_dir.exists() else Path(".")
            stat = shutil.disk_usage(check_path)
            free_gb = stat.free / (1024 ** 3)
            total_gb = stat.total / (1024 ** 3)

            if free_gb < min_gb:
                msg = (f"Мало места на диске: {free_gb:.1f} ГБ свободно, "
                       f"нужно минимум {min_gb} ГБ (AI-проекты с torch занимают 10-25 ГБ).")
                self._fail("disk_space", msg)
            elif free_gb < min_gb * 1.5:
                msg = (f"Место на диске на пределе: {free_gb:.1f} ГБ свободно. "
                       f"Рекомендуется {min_gb * 1.5:.0f}+ ГБ.")
                self._warn("disk_space", msg)
            else:
                self._ok("disk_space",
                         f"Диск: {free_gb:.1f} ГБ свободно из {total_gb:.0f} ГБ.")
        except Exception as e:
            self._warn("disk_space", f"Не удалось проверить место на диске: {e}")

    def _check_git(self):
        """Проверяет наличие Git."""
        git_path = shutil.which("git")
        if git_path:
            try:
                ver = subprocess.check_output(
                    ["git", "--version"], stderr=subprocess.DEVNULL
                ).decode().strip()
                self._ok("git", f"Git найден: {ver} ({git_path})")
            except Exception:
                self._ok("git", f"Git найден: {git_path}")
        else:
            self._fail("git",
                       "Git не найден! Установите Git: https://git-scm.com/download/win "
                       "или используйте Portable Git.")

    def _check_python(self):
        """Проверяет версию Python хоста."""
        v = sys.version_info
        ver_str = f"{v.major}.{v.minor}.{v.micro}"
        if v.major < 3 or (v.major == 3 and v.minor < 9):
            self._fail("python_host",
                       f"Python {ver_str} слишком старый. Нужен Python 3.9+.")
        elif v.major == 3 and v.minor >= 12:
            self._warn("python_host",
                       f"Python {ver_str}: некоторые пакеты ещё не совместимы с 3.12+.")
        else:
            self._ok("python_host", f"Python хоста: {ver_str}")

    def _check_internet(self):
        """Проверяет подключение к интернету."""
        import urllib.request
        urls = [
            ("PyPI", "https://pypi.org/simple/pip/"),
            ("GitHub", "https://github.com"),
            ("python.org", "https://www.python.org/ftp/python/"),
        ]
        reachable = []
        unreachable = []
        for name, url in urls:
            try:
                urllib.request.urlopen(url, timeout=5)
                reachable.append(name)
            except Exception:
                unreachable.append(name)

        if not reachable:
            self._fail("internet", "Нет интернета! Сборка требует скачивания Python и пакетов.")
        elif unreachable:
            self._warn("internet",
                       f"Доступны: {', '.join(reachable)}. "
                       f"Недоступны: {', '.join(unreachable)}.")
        else:
            self._ok("internet", f"Интернет: {', '.join(reachable)} — всё доступно.")

    def _check_output_writable(self):
        """Проверяет, что можно писать в папку вывода."""
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            test_file = self.output_dir / ".preflight_test"
            test_file.write_text("test")
            test_file.unlink()
            self._ok("output_writable", f"Папка вывода доступна для записи: {self.output_dir}")
        except Exception as e:
            self._fail("output_writable",
                       f"Нет прав на запись в {self.output_dir}: {e}")

    def _check_vcredist(self):
        """Проверяет Visual C++ Redistributable (нужен для компиляции C-расширений)."""
        try:
            import winreg
            keys_to_check = [
                r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64",
            ]
            found = False
            for key_path in keys_to_check:
                try:
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                    installed, _ = winreg.QueryValueEx(key, "Installed")
                    if installed == 1:
                        version, _ = winreg.QueryValueEx(key, "Version")
                        self._ok("vcredist",
                                 f"Visual C++ Redistributable найден: {version}")
                        found = True
                        break
                except (FileNotFoundError, OSError):
                    continue

            if not found:
                self._warn("vcredist",
                           "Visual C++ Redistributable 2015-2022 не найден. "
                           "Некоторые пакеты (numpy, scipy) могут не установиться. "
                           "Скачайте: https://aka.ms/vs/17/release/vc_redist.x64.exe")
        except ImportError:
            pass  # не Windows

    def _check_path_length(self):
        """Проверяет ограничение длины пути Windows (MAX_PATH = 260)."""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\FileSystem"
            )
            val, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
            if val == 1:
                self._ok("long_paths",
                         "Длинные пути Windows включены (LongPathsEnabled=1).")
            else:
                # Проверяем длину пути вывода
                full_path = str(self.output_dir.resolve())
                if len(full_path) > 180:
                    self._warn(
                        "long_paths",
                        f"Длинные пути Windows НЕ включены, а путь к output уже "
                        f"{len(full_path)} символов. Установите output ближе к корню диска "
                        f"(например C:\\Portable) или включите LongPathsEnabled в реестре."
                    )
                else:
                    self._warn(
                        "long_paths",
                        "Длинные пути Windows не включены (LongPathsEnabled=0). "
                        "Если сборка упадёт с ошибкой пути — включите через реестр или "
                        "перенесите output ближе к корню диска."
                    )
        except Exception:
            pass

    def _check_antivirus_conflict(self):
        """Предупреждает о возможных конфликтах с антивирусом."""
        known_av = {
            "MsMpEng.exe": "Windows Defender",
            "avp.exe": "Kaspersky",
            "avgnt.exe": "Avira",
            "mbam.exe": "Malwarebytes",
        }
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            running_av = []
            for proc, name in known_av.items():
                if proc.lower() in result.stdout.lower():
                    running_av.append(name)

            if running_av:
                self._warn(
                    "antivirus",
                    f"Активный антивирус: {', '.join(running_av)}. "
                    "Может замедлить установку пакетов или заблокировать python.exe. "
                    "Если сборка зависает — временно добавьте папку temp/ в исключения."
                )
            else:
                self._ok("antivirus", "Конфликтов с антивирусом не обнаружено.")
        except Exception:
            pass

    def _check_repo_path(self, repo_path: str):
        """Проверяет валидность пути к репозиторию."""
        p = Path(repo_path)
        if not p.exists():
            self._warn("repo_path", f"Путь к репозиторию не существует: {repo_path}")
            return

        # Проверяем наличие хотя бы одного из файлов сборки
        build_files = [
            "requirements.txt", "pyproject.toml", "setup.py",
            "environment.yml", "Pipfile"
        ]
        found = [f for f in build_files if (p / f).exists()]
        if found:
            self._ok("repo_path",
                     f"Репозиторий: найдены файлы зависимостей: {', '.join(found)}")
        else:
            self._warn("repo_path",
                       f"Не найдено файлов зависимостей ({', '.join(build_files)}). "
                       "Установка пакетов может не сработать.")

    # ------------------------------------------------------------------ #
    #  Рендеринг результатов                                              #
    # ------------------------------------------------------------------ #

    def _render_html(self) -> str:
        """Рендерит HTML-блок для вставки в веб-интерфейс."""
        lines = []
        for r in self.results:
            color = {"ok": "#22c55e", "warn": "#f59e0b", "fail": "#ef4444"}.get(
                r["status"], "#64748b"
            )
            icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}.get(r["status"], "•")
            lines.append(
                f'<div style="padding:6px 0; border-bottom:1px solid #f1f5f9;">'
                f'<span style="color:{color}">{icon}</span> {r["msg"]}</div>'
            )
        ok = len(self.errors) == 0
        header_color = "#22c55e" if ok else "#ef4444"
        header_text = "✅ Система готова к сборке" if ok else f"❌ Обнаружены проблемы ({len(self.errors)} ошибок)"
        return (
            f'<div style="border:2px solid {header_color}; border-radius:8px; '
            f'padding:16px; margin-bottom:16px;">'
            f'<b style="color:{header_color}; font-size:16px;">{header_text}</b>'
            f'<div style="margin-top:10px;">{"".join(lines)}</div>'
            f'</div>'
        )

    # ------------------------------------------------------------------ #
    #  Хелперы                                                            #
    # ------------------------------------------------------------------ #

    def _ok(self, key: str, msg: str):
        self.results.append({"key": key, "status": "ok", "msg": msg})

    def _warn(self, key: str, msg: str):
        self.results.append({"key": key, "status": "warn", "msg": msg})
        self.warnings.append(msg)

    def _fail(self, key: str, msg: str):
        self.results.append({"key": key, "status": "fail", "msg": msg})
        self.errors.append(msg)