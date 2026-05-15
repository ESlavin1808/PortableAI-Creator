# sanity_check.py — Тест работоспособности портативной сборки
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List


# Известные AI-фреймворки и что проверять для каждого
AI_CHECKS = {
    "torch": {
        "import_test": "import torch; print(f'torch {torch.__version__}, CUDA={torch.cuda.is_available()}')",
        "cuda_test": "import torch; assert torch.cuda.is_available(), f'CUDA недоступна (device_count={torch.cuda.device_count()})'",
        "hint_no_cuda": "PyTorch установлен в CPU-режиме. Для GPU убедитесь, что установлены драйверы NVIDIA и torch с CUDA (--extra-index-url https://download.pytorch.org/whl/cu128)."
    },
    "tensorflow": {
        "import_test": "import tensorflow as tf; print(f'tf {tf.__version__}, GPU={len(tf.config.list_physical_devices(\"GPU\"))}')",
    },
    "gradio": {
        "import_test": "import gradio; print(f'gradio {gradio.__version__}')",
    },
    "fastapi": {
        "import_test": "import fastapi; print(f'fastapi {fastapi.__version__}')",
    },
    "transformers": {
        "import_test": "import transformers; print(f'transformers {transformers.__version__}')",
    },
    "diffusers": {
        "import_test": "import diffusers; print(f'diffusers {diffusers.__version__}')",
    },
    "numpy": {
        "import_test": "import numpy; print(f'numpy {numpy.__version__}')",
    },
    "cv2": {
        "import_test": "import cv2; print(f'opencv {cv2.__version__}')",
    },
    "PIL": {
        "import_test": "from PIL import Image; import PIL; print(f'Pillow {PIL.__version__}')",
    },
    "flask": {
        "import_test": "import flask; print(f'flask {flask.__version__}')",
    },
    "scipy": {
        "import_test": "import scipy; print(f'scipy {scipy.__version__}')",
    },
    "sklearn": {
        "import_test": "import sklearn; print(f'scikit-learn {sklearn.__version__}')",
    },
}


class SanityChecker:
    """Проверяет работоспособность портативной сборки."""

    def __init__(self, output_folder: Path, python_exe: Path, env: dict):
        self.folder = output_folder
        self.python = python_exe
        self.env = env
        self.results: List[Dict] = []

    # ------------------------------------------------------------------ #
    #  Публичный метод                                                     #
    # ------------------------------------------------------------------ #

    def run(self) -> Dict[str, Any]:
        """
        Запускает sanity-checks.
        Возвращает {'success': bool, 'logs': [...], 'html': str}
        """
        self.results = []

        # 1. Базовая проверка Python
        self._check_python_runs()

        # 2. Определяем установленные пакеты
        installed = self._get_installed_packages()

        # 3. Проверяем каждый AI-фреймворк, если он установлен
        for pkg_name, checks in AI_CHECKS.items():
            # Нормализуем имя для сравнения (torch, opencv-python→cv2, etc.)
            pip_name = self._to_pip_name(pkg_name)
            if pip_name in installed:
                self._check_package(pkg_name, checks, installed)

        # 4. Проверяем точку входа приложения
        self._check_entrypoint()

        # 5. Итог
        failed = [r for r in self.results if r["status"] == "fail"]
        warned = [r for r in self.results if r["status"] == "warn"]
        passed = [r for r in self.results if r["status"] == "ok"]

        success = len(failed) == 0
        logs = [r["msg"] for r in self.results]
        summary = (f"✅ {len(passed)} passed  ⚠️ {len(warned)} warnings  "
                   f"❌ {len(failed)} failed")
        logs.append(f"\n{'='*50}\n{summary}")

        return {
            "success": success,
            "summary": summary,
            "logs": logs,
            "results": self.results,
            "html": self._render_html(summary),
        }

    # ------------------------------------------------------------------ #
    #  Внутренние проверки                                                #
    # ------------------------------------------------------------------ #

    def _check_python_runs(self):
        """Python исполняемый файл запускается."""
        try:
            out = subprocess.check_output(
                [str(self.python), "-c", "import sys; print(sys.version)"],
                stderr=subprocess.STDOUT,
                env=self.env,
                timeout=15,
            ).decode().strip().splitlines()[0]
            self._ok("python", f"Python запускается: {out}")
        except subprocess.TimeoutExpired:
            self._fail("python", "Python не отвечает (timeout 15s). Антивирус или битый архив?")
        except Exception as e:
            self._fail("python", f"Python не запускается: {e}")

    def _get_installed_packages(self) -> set:
        """Получает список установленных пакетов."""
        try:
            out = subprocess.check_output(
                [str(self.python), "-m", "pip", "list", "--format=freeze"],
                stderr=subprocess.DEVNULL,
                env=self.env,
                timeout=30,
            ).decode()
            pkgs = set()
            for line in out.splitlines():
                if "==" in line:
                    pkgs.add(line.split("==")[0].lower().replace("_", "-").replace(".", "-"))
            return pkgs
        except Exception:
            return set()

    def _check_package(self, pkg_name: str, checks: dict, installed: set):
        """Проверяет импорт и работоспособность пакета."""
        import_code = checks.get("import_test", f"import {pkg_name}")
        try:
            out = subprocess.check_output(
                [str(self.python), "-c", import_code],
                stderr=subprocess.STDOUT,
                env=self.env,
                timeout=60,
            ).decode().strip()
            self._ok(f"pkg:{pkg_name}", f"{out}")
        except subprocess.CalledProcessError as e:
            err = e.output.decode().strip().splitlines()[-1] if e.output else str(e)
            self._fail(f"pkg:{pkg_name}", f"import {pkg_name} упал: {err}")
            return

        # Дополнительная CUDA-проверка для torch
        if pkg_name == "torch" and "cuda_test" in checks:
            has_nvidia = self._check_nvidia_smi()
            if has_nvidia:
                try:
                    subprocess.check_output(
                        [str(self.python), "-c", checks["cuda_test"]],
                        stderr=subprocess.STDOUT,
                        env=self.env,
                        timeout=30,
                    )
                    self._ok("torch:cuda", "torch.cuda.is_available() → True")
                except subprocess.CalledProcessError as e:
                    err = e.output.decode().strip() if e.output else str(e)
                    hint = checks.get("hint_no_cuda", "")
                    self._fail("torch:cuda",
                               f"NVIDIA GPU есть, но CUDA недоступна. {hint}")
            else:
                self._warn("torch:cuda",
                           "NVIDIA GPU не найден. torch работает в CPU-режиме.")

    def _check_entrypoint(self):
        """Проверяет наличие и синтаксис основного скрипта."""
        candidates = ["app.py", "main.py", "gradio_app.py", "webui.py", "demo.py", "run.py"]
        found = None
        for c in candidates:
            if (self.folder / c).exists():
                found = c
                break

        if not found:
            self._warn("entrypoint",
                       f"Не найдена точка входа ({', '.join(candidates)}). "
                       "Проверьте файлы репозитория вручную.")
            return

        # Проверяем синтаксис через py_compile
        try:
            subprocess.check_output(
                [str(self.python), "-m", "py_compile", found],
                stderr=subprocess.STDOUT,
                env=self.env,
                timeout=15,
                cwd=str(self.folder),
            )
            self._ok("entrypoint", f"Синтаксис {found} корректен.")
        except subprocess.CalledProcessError as e:
            err = e.output.decode().strip() if e.output else str(e)
            self._fail("entrypoint", f"Синтаксическая ошибка в {found}: {err}")

    def _check_nvidia_smi(self) -> bool:
        """Проверяет наличие nvidia-smi."""
        try:
            return subprocess.run(
                ["nvidia-smi"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).returncode == 0
        except Exception:
            return False

    def _to_pip_name(self, pkg: str) -> str:
        """Нормализует имя пакета для поиска в pip list."""
        mapping = {
            "cv2": "opencv-python",
            "PIL": "pillow",
            "sklearn": "scikit-learn",
        }
        name = mapping.get(pkg, pkg)
        return name.lower().replace("_", "-").replace(".", "-")

    # ------------------------------------------------------------------ #
    #  HTML-рендер                                                        #
    # ------------------------------------------------------------------ #

    def _render_html(self, summary: str) -> str:
        lines = []
        for r in self.results:
            color = {"ok": "#22c55e", "warn": "#f59e0b", "fail": "#ef4444"}.get(
                r["status"], "#64748b"
            )
            icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}.get(r["status"], "•")
            lines.append(
                f'<div style="padding:5px 0; border-bottom:1px solid #f1f5f9; font-size:13px;">'
                f'<span style="color:{color}">{icon}</span> '
                f'<code style="font-size:11px; color:#64748b">[{r["key"]}]</code> '
                f'{r["msg"]}</div>'
            )

        ok = all(r["status"] != "fail" for r in self.results)
        hdr_color = "#22c55e" if ok else "#ef4444"
        hdr_text = "✅ Сборка работоспособна" if ok else "❌ Обнаружены проблемы"

        return (
            f'<div style="border:2px solid {hdr_color};border-radius:8px;padding:16px;">'
            f'<b style="color:{hdr_color};font-size:15px;">{hdr_text}</b>'
            f'<div style="font-size:12px;color:#64748b;margin-bottom:8px;">{summary}</div>'
            f'<div>{"".join(lines)}</div>'
            f'</div>'
        )

    def _ok(self, key, msg):
        self.results.append({"key": key, "status": "ok", "msg": msg})

    def _warn(self, key, msg):
        self.results.append({"key": key, "status": "warn", "msg": msg})

    def _fail(self, key, msg):
        self.results.append({"key": key, "status": "fail", "msg": msg})
