# error_reporter.py — Генератор ZIP-отчётов об ошибках сборки
import os
import sys
import json
import platform
import subprocess
import zipfile
import tempfile
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ErrorReporter:
    """
    Собирает диагностическую информацию и пакует её в ZIP-отчёт.
    Используется при сбое сборки для отладки.
    """

    def __init__(self, output_dir: str = "output/portable", logs_dir: str = "logs"):
        self.output_dir = Path(output_dir)
        self.logs_dir = Path(logs_dir)

    # ------------------------------------------------------------------ #
    #  Публичный метод                                                    #
    # ------------------------------------------------------------------ #

    def generate(
        self,
        build_logs: List[str],
        repo_name: str = "unknown",
        repo_url: str = "",
        error_msg: str = "",
        output_folder: Optional[Path] = None,
    ) -> Optional[Path]:
        """
        Генерирует ZIP-отчёт об ошибке.
        Возвращает путь к ZIP-файлу или None при ошибке.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_name = f"error_report_{repo_name}_{timestamp}.zip"
        report_path = Path(tempfile.gettempdir()) / report_name

        try:
            with zipfile.ZipFile(report_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 1. Системная информация
                zf.writestr("system_info.json",
                            json.dumps(self._collect_system_info(), indent=2, ensure_ascii=False))

                # 2. Логи сборки
                zf.writestr("build_logs.txt", "\n".join(build_logs))

                # 3. Информация об ошибке
                zf.writestr("error.txt",
                            f"Репозиторий: {repo_name}\nURL: {repo_url}\n"
                            f"Ошибка: {error_msg}\n"
                            f"Время: {datetime.now().isoformat()}")

                # 4. Установленные пакеты (если Python уже есть)
                pip_list = self._get_pip_list(output_folder)
                if pip_list:
                    zf.writestr("installed_packages.txt", pip_list)

                # 5. requirements.txt из сборки (если есть)
                if output_folder:
                    for req_file in ["requirements.txt", "requirements_filtered.txt",
                                     "requirements_raw.txt"]:
                        req_path = output_folder / req_file
                        if req_path.exists():
                            try:
                                zf.writestr(req_file, req_path.read_text(encoding="utf-8"))
                            except Exception:
                                pass

                # 6. Логи из папки logs/ (последние 500 строк каждого)
                if self.logs_dir.exists():
                    for log_file in self.logs_dir.glob("*.log"):
                        try:
                            lines = log_file.read_text(encoding="utf-8",
                                                       errors="ignore").splitlines()
                            tail = "\n".join(lines[-500:])
                            zf.writestr(f"logs/{log_file.name}", tail)
                        except Exception:
                            pass

                # 7. config.json (без паролей/прокси)
                cfg_path = Path("config.json")
                if cfg_path.exists():
                    try:
                        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                        # Удаляем чувствительные данные
                        for key in ("proxy_http", "proxy_https", "ai_model_path"):
                            cfg.pop(key, None)
                        zf.writestr("config_sanitized.json",
                                    json.dumps(cfg, indent=2, ensure_ascii=False))
                    except Exception:
                        pass

                # 8. Инструкции
                zf.writestr(
                    "README.txt",
                    "=== Отчёт об ошибке PortableAI Creator ===\n\n"
                    "Содержимое архива:\n"
                    "  system_info.json     — версия ОС, Python, GPU\n"
                    "  build_logs.txt       — полные логи сборки\n"
                    "  error.txt            — краткая информация об ошибке\n"
                    "  installed_packages.txt — список установленных пакетов\n"
                    "  requirements*.txt    — файлы зависимостей\n"
                    "  logs/                — логи приложения\n"
                    "  config_sanitized.json — настройки (без паролей)\n\n"
                    "Отправьте этот архив разработчику или приложите к Issue на GitHub.\n"
                )

            logger.info(f"📋 Отчёт создан: {report_path}")
            return report_path

        except Exception as e:
            logger.error(f"❌ Не удалось создать отчёт: {e}")
            return None

    # ------------------------------------------------------------------ #
    #  Сбор информации                                                    #
    # ------------------------------------------------------------------ #

    def _collect_system_info(self) -> Dict[str, Any]:
        info = {
            "timestamp": datetime.now().isoformat(),
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
            },
            "python": {
                "version": sys.version,
                "executable": sys.executable,
                "platform": sys.platform,
            },
            "env": {
                "PATH_length": len(os.environ.get("PATH", "")),
                "TEMP": os.environ.get("TEMP", ""),
                "CUDA_PATH": os.environ.get("CUDA_PATH", "not set"),
                "PYTHONPATH": os.environ.get("PYTHONPATH", "not set"),
            },
            "disk": self._get_disk_info(),
            "gpu": self._get_gpu_info(),
            "git": self._get_git_version(),
        }
        return info

    def _get_disk_info(self) -> Dict:
        try:
            import shutil
            stat = shutil.disk_usage(Path("."))
            return {
                "total_gb": round(stat.total / 1024**3, 1),
                "free_gb": round(stat.free / 1024**3, 1),
                "used_gb": round(stat.used / 1024**3, 1),
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_gpu_info(self) -> Dict:
        result = {"nvidia": None, "amd": None}
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                 "--format=csv,noheader"],
                stderr=subprocess.DEVNULL, timeout=5
            ).decode().strip()
            result["nvidia"] = out
        except Exception:
            result["nvidia"] = "not found"

        if sys.platform == "linux":
            try:
                out = subprocess.check_output(
                    ["rocm-smi", "--showproductname"],
                    stderr=subprocess.DEVNULL, timeout=5
                ).decode().strip()
                result["amd"] = out
            except Exception:
                result["amd"] = "not found"
        return result

    def _get_git_version(self) -> str:
        try:
            return subprocess.check_output(
                ["git", "--version"], stderr=subprocess.DEVNULL, timeout=15
            ).decode().strip()
        except Exception:
            return "not found"

    def _get_pip_list(self, output_folder: Optional[Path]) -> str:
        """Пытается получить список пакетов из portable Python сборки."""
        if not output_folder:
            return ""
        python_exe = output_folder / "python_portable" / "python.exe"
        if not python_exe.exists():
            # Linux/Mac
            for candidate in ["bin/python3.11", "bin/python3", "bin/python"]:
                p = output_folder / "python_portable" / candidate
                if p.exists():
                    python_exe = p
                    break
        if not python_exe.exists():
            return ""
        try:
            return subprocess.check_output(
                [str(python_exe), "-m", "pip", "list", "--format=columns"],
                stderr=subprocess.DEVNULL,
                timeout=15,
            ).decode()
        except Exception:
            return ""
