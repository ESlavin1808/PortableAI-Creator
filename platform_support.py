# platform_support.py
import os
import sys
import shutil
import subprocess
import requests
import zipfile
import tarfile
from pathlib import Path
from typing import Dict, List, Tuple


# ------------------------------------------------------------------ #
#  URL-шаблоны                                                        #
# ------------------------------------------------------------------ #

def _python_url(version: str, platform: str) -> str:
    if platform == "win32":
        return f"https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"
    tag = "20240224"
    if platform == "linux":
        return (
            f"https://github.com/indygreg/python-build-standalone/releases/download/{tag}/"
            f"cpython-{version}+{tag}-x86_64-unknown-linux-gnu-install_only.tar.gz"
        )
    return (
        f"https://github.com/indygreg/python-build-standalone/releases/download/{tag}/"
        f"cpython-{version}+{tag}-aarch64-apple-darwin-install_only.tar.gz"
    )


PYTHON_VERSION = "3.11.9"

PLATFORM_CONFIG = {
    "win32": {
        "python_exe":   "python.exe",
        "pip_exe":      "Scripts/pip.exe",
        "scripts_dir":  "Scripts",
        "archive_ext":  "zip",
        "launcher_ext": ".bat",
        "path_sep":     "\\",
        "incompatible": {
            "torchcodec", "torchao", "triton", "flash-attn", "bitsandbytes",
            "xformers", "deepspeed", "onnxruntime-gpu", "tensorrt-cu12",
        },
    },
    "linux": {
        "python_exe":   "bin/python3.11",
        "pip_exe":      "bin/pip3.11",
        "scripts_dir":  "bin",
        "archive_ext":  "tar.gz",
        "launcher_ext": ".sh",
        "path_sep":     "/",
        "incompatible": {"torchcodec", "torchao", "mlx", "mlx-lm"},
    },
    "darwin": {
        "python_exe":   "bin/python3.11",
        "pip_exe":      "bin/pip3.11",
        "scripts_dir":  "bin",
        "archive_ext":  "tar.gz",
        "launcher_ext": ".sh",
        "path_sep":     "/",
        "incompatible": {"torchcodec", "torchao", "triton", "onnxruntime-gpu", "tensorrt-cu12"},
    },
}

CUDA_CONFIG = {
    "win32":  "https://download.pytorch.org/whl/cu128",
    "linux":  "https://download.pytorch.org/whl/cu128",
    "darwin": "",
}


def get_platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return "win32"


def get_config() -> Dict:
    return PLATFORM_CONFIG[get_platform()]


def get_incompatible_packages() -> set:
    return get_config()["incompatible"]


# ------------------------------------------------------------------ #
#  Установка Python                                                   #
# ------------------------------------------------------------------ #

class PythonInstaller:
    def __init__(self, output_folder: Path, temp_dir: Path, logs: list,
                 version: str = PYTHON_VERSION):
        self.folder   = output_folder
        self.temp_dir = temp_dir
        self.logs     = logs
        self.version  = version
        self.platform = get_platform()
        self.cfg      = get_config()

    def setup(self) -> Tuple[Path, dict]:
        python_dir = self.folder / "python_portable"
        python_exe = python_dir / self.cfg["python_exe"]
        pip_exe    = python_dir / self.cfg["pip_exe"]

        if python_exe.exists() and pip_exe.exists():
            try:
                out = subprocess.check_output(
                    [str(python_exe), "--version"],
                    stderr=subprocess.STDOUT,
                    timeout=10,
                ).decode().strip()
                cached_ver = out.split()[-1]
                if cached_ver == self.version:
                    self.logs.append(f"✅ Portable Python {self.version} уже настроен.")
                    return python_exe, self._make_env(python_dir)
                else:
                    self.logs.append(f"⚠️ Кэш Python {cached_ver} ≠ {self.version}, пересборка...")
            except Exception:
                pass

        self._download_and_extract(python_dir)

        if self.platform == "win32":
            self._activate_site_packages(python_dir)
            self._install_pip_windows(python_dir, python_exe)

        pip_exe_path = python_dir / self.cfg["pip_exe"]
        if not pip_exe_path.exists():
            raise Exception(f"pip не найден после установки: {pip_exe_path}")

        env = self._make_env(python_dir)
        self._install_build_tools(python_exe, env)

        self.logs.append(f"✅ Portable Python {self.version} готов.")
        return python_exe, env

    def _download_and_extract(self, python_dir: Path):
        url      = _python_url(self.version, self.platform)
        ext      = self.cfg["archive_ext"]
        filename = f"python-{self.version}-{self.platform}.{ext}"
        archive  = self.temp_dir / filename

        if not archive.exists():
            self.logs.append(f"📥 Скачивание Python {self.version}...")
            try:
                resp = requests.get(url, stream=True, timeout=300)
                resp.raise_for_status()
                with open(archive, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
            except requests.RequestException as e:
                raise Exception(f"Ошибка скачивания Python {self.version}: {e}")
        else:
            self.logs.append(f"📦 Используем кэшированный Python {self.version}.")

        self.logs.append("📂 Распаковка Python...")
        if python_dir.exists():
            shutil.rmtree(python_dir)
        python_dir.mkdir(parents=True)

        if ext == "zip":
            with zipfile.ZipFile(archive, "r") as zf:
                zf.extractall(python_dir)
        elif ext == "tar.gz":
            with tarfile.open(archive, "r:gz") as tf:
                tf.extractall(python_dir)
            inner = python_dir / "python"
            if inner.exists():
                for item in inner.iterdir():
                    shutil.move(str(item), str(python_dir / item.name))
                inner.rmdir()

        if self.platform != "win32":
            python_exe = python_dir / self.cfg["python_exe"]
            python_exe.chmod(0o755)
            bin_dir = python_dir / self.cfg["scripts_dir"]
            if bin_dir.exists():
                for f in bin_dir.iterdir():
                    if f.is_file():
                        f.chmod(0o755)

    def _activate_site_packages(self, python_dir: Path):
        for pth_file in python_dir.glob("python*._pth"):
            content = pth_file.read_text(encoding="utf-8")
            if "#import site" in content:
                pth_file.write_text(
                    content.replace("#import site", "import site"),
                    encoding="utf-8",
                )
                self.logs.append("🔧 Активирован import site в .pth файле.")
            break

        # Создаём sitecustomize.py — добавляет корень portable в sys.path
        # (embeddable Python игнорирует PYTHONPATH, даже с import site)
        site_pkg = python_dir / "Lib" / "site-packages"
        sc_file = site_pkg / "sitecustomize.py"
        if site_pkg.exists() and not sc_file.exists():
            sc_file.write_text(
                "import sys, os\n"
                "# Добавляем корень portable (родитель python_portable/) в sys.path\n"
                "# __file__ = .../python_portable/Lib/site-packages/sitecustomize.py\n"
                "root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))\n"
                "if root not in sys.path:\n"
                "    sys.path.insert(0, root)\n",
                encoding="utf-8",
            )
            self.logs.append("🔧 Создан sitecustomize.py (sys.path fix для embeddable Python).")

    def _install_pip_windows(self, python_dir: Path, python_exe: Path):
        env = self._make_env(python_dir)
        self.logs.append("📦 Установка pip...")
        get_pip = python_dir / "get-pip.py"
        resp = requests.get("https://bootstrap.pypa.io/get-pip.py", timeout=120, stream=True)
        resp.raise_for_status()
        with open(get_pip, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        subprocess.check_call(
            [str(python_exe.resolve()), str(get_pip.resolve()),
             "--no-warn-script-location", "--quiet"],
            env=env,
            timeout=120,
        )
        get_pip.unlink()

    def _install_build_tools(self, python_exe: Path, env: dict):
        """Установка базовых инструментов сборки — без pkg_resources проверок."""
        self.logs.append("🔧 Установка setuptools, wheel, hatchling...")
        try:
            subprocess.check_call(
                [
                    str(python_exe.resolve()), "-m", "pip", "install",
                    "setuptools", "wheel", "hatchling", "packaging",
                    "--no-warn-script-location",
                    "--quiet",
                ],
                env=env,
                timeout=120,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.logs.append("✅ Build tools установлены.")
        except subprocess.TimeoutExpired:
            self.logs.append("⚠️ Timeout build tools — продолжаем без них.")
        except Exception as e:
            self.logs.append(f"⚠️ Build tools пропущены: {e}")

    def _make_env(self, python_dir: Path) -> dict:
        env = os.environ.copy()
        env.pop("PYTHONUSERBASE", None)
        env.pop("PYTHONHOME",     None)
        env["PYTHONNOUSERSITE"] = "1"

        if (python_dir / "Lib" / "site-packages").exists():
            site_pkg = str(python_dir / "Lib" / "site-packages")
        else:
            import glob
            candidates = glob.glob(str(python_dir / "lib" / "python3*" / "site-packages"))
            site_pkg = candidates[0] if candidates else ""

        env["PYTHONPATH"] = site_pkg
        env["PATH"] = (
            str(python_dir) + os.pathsep +
            str(python_dir / self.cfg["scripts_dir"]) + os.pathsep +
            env.get("PATH", "")
        )
        portable_temp = self.folder / "_build_temp"
        portable_temp.mkdir(exist_ok=True)
        env["TEMP"] = env["TMP"] = str(portable_temp)
        env["PIP_CACHE_DIR"] = str(self.folder / "_pip_cache")
        return env


# ------------------------------------------------------------------ #
#  GPU детектор                                                       #
# ------------------------------------------------------------------ #

def detect_torch_args(logs: list) -> List[str]:
    platform = get_platform()

    if platform == "darwin":
        logs.append("🍎 macOS: torch с поддержкой MPS.")
        return []

    try:
        if subprocess.run(
            ["nvidia-smi"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        ).returncode == 0:
            url = CUDA_CONFIG[platform]
            logs.append(f"🎮 NVIDIA GPU найдена, CUDA: {url}")
            return ["--extra-index-url", url]
    except Exception:
        pass

    if platform == "linux":
        try:
            if subprocess.run(
                ["rocm-smi"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            ).returncode == 0:
                logs.append("🔴 AMD ROCm GPU найдена.")
                return ["--extra-index-url", "https://download.pytorch.org/whl/rocm6.2"]
        except Exception:
            pass

    logs.append("💻 GPU не найден, используется CPU-версия torch.")
    return []


# ------------------------------------------------------------------ #
#  Генератор лаунчеров                                                #
# ------------------------------------------------------------------ #

class LauncherGenerator:
    def __init__(self, output_dir: Path):
        self.output_dir  = output_dir
        self.platform    = get_platform()
        self.cfg         = get_config()
        self.python_dir  = output_dir / "python_portable"
        self.scripts_dir = self.python_dir / self.cfg["scripts_dir"]

    def create(self, entries: List[Dict]):
        for ep in entries:
            self._write(ep)
        self._write_shell()  # всегда создаём shell для ручного ввода

    def _write(self, ep: Dict):
        name = ep["name"]
        if self.platform == "win32":
            cmd = self._win_cmd(name, ep["type"], ep)
            bat = self._make_bat(cmd, name, ep["type"])
            (self.output_dir / f"run_{name}.bat").write_text(bat, encoding="utf-8")
        else:
            cmd = self._unix_cmd(name, ep["type"], ep)
            sh = self._make_sh(cmd, name, ep["type"])
            path = self.output_dir / f"run_{name}.sh"
            path.write_text(sh, encoding="utf-8")
            path.chmod(0o755)

    def _make_bat(self, cmd: str, name: str, ep_type: str) -> str:
        lines = [
            "@echo off",
            'chcp 65001 >nul 2>&1',
            'cd /d "%~dp0"',
            'set "PYTHONNOUSERSITE=1"',
            'set "PATH=%~dp0python_portable;%~dp0python_portable\\Scripts;%PATH%"',
            '',
            'if not exist "%~dp0python_portable\\python.exe" (',
            '    echo [ERROR] Python не найден!',
            '    echo Папка python_portable отсутствует.',
            '    echo Запустите сборку заново.',
            '    pause',
            '    exit /b 1',
            ')',
        ]
        if ep_type == "py":
            lines.extend([
                'if "%*"=="" (',
                f'    echo ^> {cmd}',
                '    echo.',
                '    echo === Справка ===',
                f'    {cmd} --help',
                '    echo.',
                '    echo === Запуск ===',
                f'    echo Пример: {cmd} ^<аргументы^>',
                '    echo.',
                '    echo Для интерактивной работы используйте shell.bat',
                '    pause',
                '    exit /b 0',
                ')',
                cmd,
            ])
        else:
            lines.append(cmd)
        lines.extend([
            'if errorlevel 1 (',
            '    echo.',
            '    echo [ЗАВЕРШЕНО С ОШИБКОЙ]',
            '    echo Для ручного ввода команд используйте shell.bat',
            ')',
            'pause',
        ])
        return '\n'.join(lines) + '\n'

    def _make_sh(self, cmd: str, name: str, ep_type: str) -> str:
        lines = [
            '#!/usr/bin/env bash',
            'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
            'export PYTHONNOUSERSITE=1',
            'export PATH="$DIR/python_portable/bin:$PATH"',
        ]
        if ep_type == "py":
            # Для Linux: справка + команда
            lines.extend([
                f'echo "=== {name} --help ==="',
                f'{cmd} --help',
                'echo "=== Запуск ==="',
                f'echo "Пример: {cmd} <аргументы>"',
                'echo.',
                cmd,
            ])
        else:
            lines.append(cmd)
        lines.append('echo "Exit code: $?"')
        return '\n'.join(lines) + '\n'

    def _win_cmd(self, name: str, ep_type: str, ep: Dict) -> str:
        if ep_type == "cli":
            exe = self.scripts_dir / f"{name}.exe"
            if exe.exists():
                return f'"%~dp0python_portable\\Scripts\\{name}.exe" %*'
            return f'"%~dp0python_portable\\python.exe" -m {name} %*'
        script = ep.get("script", name)
        return f'"%~dp0python_portable\\python.exe" "{script}" %*'

    def _unix_cmd(self, name: str, ep_type: str, ep: Dict) -> str:
        if ep_type == "cli":
            exe = self.scripts_dir / name
            if exe.exists():
                return f'"$DIR/python_portable/bin/{name}"'
            return f'"$DIR/python_portable/bin/python3.11" -m {name}'
        script = ep.get("script", name)
        return f'"$DIR/python_portable/bin/python3.11" "{script}"'

    def _write_shell(self):
        name = "shell"
        if self.platform == "win32":
            bat = (
                "@echo off\n"
                "chcp 65001 >nul 2>&1\n"
                'cd /d "%~dp0"\n'
                'set "PYTHONNOUSERSITE=1"\n'
                'set "PATH=%~dp0python_portable;%~dp0python_portable\\Scripts;%PATH%"\n'
                "echo.\n"
                "echo === Portable Python Shell ===\n"
                "echo.\n"
                'echo Python: "%~dp0python_portable\\python.exe"\n'
                "echo.\n"
                "echo Примеры команд:\n"
                "echo   python app.py --help\n"
                "echo   python main.py -i video.mp4 -o output\n"
                "echo.\n"
                "cmd.exe /k\n"
            )
            (self.output_dir / f"{name}.bat").write_text(bat, encoding="utf-8")
        else:
            sh = (
                "#!/usr/bin/env bash\n"
                'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
                'export PYTHONNOUSERSITE=1\n'
                'export PATH="$DIR/python_portable/bin:$PATH"\n'
                'exec bash\n'
            )
            path = self.output_dir / f"{name}.sh"
            path.write_text(sh, encoding="utf-8")
            path.chmod(0o755)