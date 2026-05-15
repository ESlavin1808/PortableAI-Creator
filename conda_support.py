# conda_support.py — парсинг environment.yml и конвертация в pip
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple


# Пакеты которые есть в conda но отсутствуют на PyPI или имеют другое имя
CONDA_TO_PIP: Dict[str, str] = {
    "pytorch":          "torch",
    "pytorch-cuda":     "",           # пустая строка = нет pip-аналога
    "cudatoolkit":      "",
    "cudnn":            "",
    "mkl":              "",
    "mkl-service":      "",
    "nccl":             "",
    "libfaiss-avx2":    "faiss-cpu",
    "faiss":            "faiss-cpu",
    "faiss-gpu":        "faiss-gpu",
    "ffmpeg":           "",           # системная зависимость
    "sox":              "",
    "libsndfile":       "",
    "ninja":            "ninja",
    "cmake":            "cmake",
    "pkg-config":       "",
    "gcc":              "",
    "gxx":              "",
    "openssl":          "",
    "ca-certificates":  "",
    "certifi":          "certifi",
    "conda":            "",
    "pip":              "",
    "python":           "",
    "setuptools":       "setuptools",
    "wheel":            "wheel",
}

# Conda-каналы которые игнорируем (не конвертируем их пакеты)
SKIP_CHANNELS = {"defaults", "conda-forge", "nvidia", "pytorch"}


class CondaConverter:
    def __init__(self, env_yml: Path):
        self.env_yml = env_yml
        self.logs: List[str] = []

    def convert(self) -> Tuple[List[str], List[str]]:
        """
        Парсит environment.yml.
        Возвращает (pip_deps, skipped_deps).
        pip_deps  — список строк для requirements.txt
        skipped   — пакеты без pip-аналога (только предупреждения)
        """
        try:
            data = self._parse_yaml(self.env_yml)
        except Exception as e:
            self.logs.append(f"❌ Ошибка парсинга environment.yml: {e}")
            return [], []

        pip_deps: List[str] = []
        skipped:  List[str] = []

        deps = data.get("dependencies", [])
        for dep in deps:
            # Pip-блок: - pip:\n  - package
            if isinstance(dep, dict) and "pip" in dep:
                for pip_pkg in dep["pip"]:
                    if isinstance(pip_pkg, str):
                        pip_deps.append(pip_pkg.strip())
                continue

            if not isinstance(dep, str):
                continue

            pkg, version = self._split_conda_dep(dep)
            pkg_lower = pkg.lower()

            # Пропускаем python/pip/setuptools — они уже есть в portable
            if pkg_lower in {"python", "pip", "setuptools", "wheel"}:
                continue

            pip_name = CONDA_TO_PIP.get(pkg_lower)

            if pip_name is None:
                # Пакет не в таблице — пробуем использовать как есть
                # (большинство conda-пакетов совпадают с PyPI именами)
                entry = pkg if not version else f"{pkg}{version}"
                pip_deps.append(entry)
                self.logs.append(f"🔄 conda→pip: {pkg}{version or ''}")

            elif pip_name == "":
                # Нет pip-аналога
                skipped.append(pkg)
                self.logs.append(f"⚠️ Нет pip-аналога для conda-пакета: {pkg} (системная зависимость?)")

            else:
                # Есть явный маппинг
                entry = pip_name if not version else f"{pip_name}{version}"
                pip_deps.append(entry)
                self.logs.append(f"🔄 conda→pip: {pkg} → {pip_name}{version or ''}")

        # Дедупликация с сохранением порядка
        seen = set()
        unique = []
        for d in pip_deps:
            key = re.split(r"[>=<!;\[\s]", d)[0].lower()
            if key not in seen:
                seen.add(key)
                unique.append(d)

        self.logs.append(
            f"✅ Конвертировано: {len(unique)} pip-зависимостей, "
            f"пропущено {len(skipped)} conda-only пакетов."
        )
        return unique, skipped

    def write_requirements(self, dest: Path, torch_index_url: str = "") -> bool:
        """
        Конвертирует environment.yml и записывает requirements.txt.
        Возвращает True если файл создан и не пустой.
        """
        pip_deps, skipped = self.convert()

        if not pip_deps:
            self.logs.append("⚠️ После конвертации нет pip-зависимостей.")
            return False

        with open(dest, "w", encoding="utf-8") as f:
            f.write("# Сгенерировано из environment.yml\n")
            if torch_index_url:
                f.write(f"# --extra-index-url {torch_index_url}\n")
            if skipped:
                f.write(f"# Пропущены conda-only пакеты: {', '.join(skipped)}\n")
            f.write("\n")
            for dep in pip_deps:
                f.write(dep + "\n")

        return True

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                             #
    # ------------------------------------------------------------------ #

    def _split_conda_dep(self, dep: str) -> Tuple[str, str]:
        """
        Разбирает conda-зависимость вида 'numpy=1.24.0' или 'numpy>=1.24'
        в (name, version_spec).
        Conda использует = как ==, pip использует ==.
        """
        # conda: numpy=1.24  →  numpy==1.24
        # conda: numpy>=1.24 →  numpy>=1.24 (уже pip-совместимо)
        m = re.match(r'^([A-Za-z0-9_\-\.]+)\s*([><=!].*)$', dep.strip())
        if m:
            name = m.group(1)
            ver  = m.group(2)
            # Одиночный = → ==
            ver = re.sub(r'(?<![=<>!])=(?!=)', '==', ver)
            return name, ver
        # Нет версии
        return dep.strip(), ""

    def _parse_yaml(self, path: Path) -> Dict:
        """
        Минимальный YAML-парсер для environment.yml без внешних зависимостей.
        Поддерживает структуру conda environment.yml.
        """
        text = path.read_text(encoding="utf-8")
        result: Dict = {}
        current_key = None
        current_list = None
        pip_list = None
        in_pip = False
        indent_stack: List[int] = []

        for raw_line in text.splitlines():
            if not raw_line.strip() or raw_line.strip().startswith("#"):
                continue

            indent = len(raw_line) - len(raw_line.lstrip())
            line   = raw_line.strip()

            # Верхний уровень: ключ: значение
            if indent == 0 and ":" in line and not line.startswith("-"):
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip()
                if val:
                    result[key] = val
                else:
                    result[key] = []
                    current_key = key
                    current_list = result[key]
                    in_pip = False
                continue

            # Элемент списка верхнего уровня
            if indent == 2 and line.startswith("- ") and current_key == "dependencies":
                item = line[2:].strip()
                if item == "pip:":
                    in_pip = True
                    pip_list = []
                    current_list.append({"pip": pip_list})
                else:
                    in_pip = False
                    current_list.append(item)
                continue

            # Pip-подсписок
            if indent == 4 and line.startswith("- ") and in_pip and pip_list is not None:
                pip_list.append(line[2:].strip())
                continue

        return result