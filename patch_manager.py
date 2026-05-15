# patch_manager.py — Система патчей для известных репозиториев
import json
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Встроенные патчи для популярных AI-репозиториев.
# Внешние патчи можно добавлять в папку patches/*.json
BUILTIN_PATCHES: Dict[str, Dict] = {
    "cosyvoice": {
        "description": "CosyVoice TTS — голосовой синтез от Alibaba",
        "force_packages": ["setuptools<69.0.0", "wheel", "cython<3.0"],
        "replace_packages": {"openai-whisper": "openai-whisper>=20231117"},
        "skip_packages": ["matcha-tts"],  # установим вручную ниже
        "post_install": ["pip install matcha-tts --no-build-isolation"],
        "env_vars": {"HF_HOME": "./models", "MODELSCOPE_CACHE": "./models"},
        "launcher_args": "--model_dir models/CosyVoice-300M",
    },
    "stable-diffusion-webui": {
        "description": "AUTOMATIC1111 Stable Diffusion WebUI",
        "force_packages": ["torch==2.1.2", "torchvision==0.16.2"],
        "extra_index_urls": ["https://download.pytorch.org/whl/cu121"],
        "skip_packages": ["xformers"],  # опционально, может сломать сборку
        "env_vars": {
            "COMMANDLINE_ARGS": "--skip-python-version-check --no-half-vae",
            "PYTORCH_CUDA_ALLOC_CONF": "garbage_collection_threshold:0.6,max_split_size_mb:128"
        },
        "launcher_args": "--listen --port 7860",
    },
    "stable-diffusion-webui-forge": {
        "description": "Forge (форк AUTOMATIC1111)",
        "force_packages": ["torch==2.3.1+cu121", "torchvision==0.18.1+cu121"],
        "extra_index_urls": ["https://download.pytorch.org/whl/cu121"],
        "env_vars": {"PYTORCH_CUDA_ALLOC_CONF": "garbage_collection_threshold:0.6"},
    },
    "comfyui": {
        "description": "ComfyUI — нодовый интерфейс для Stable Diffusion",
        "force_packages": ["torch>=2.3.0", "torchvision", "torchaudio"],
        "extra_index_urls": ["https://download.pytorch.org/whl/cu128"],
        "env_vars": {},
        "launcher_args": "--listen 0.0.0.0 --port 8188",
    },
    "ollama": {
        "description": "Ollama — локальные LLM",
        "skip_packages": ["torch"],
        "env_vars": {"OLLAMA_HOST": "0.0.0.0:11434"},
    },
    "whisper": {
        "description": "OpenAI Whisper — распознавание речи",
        "replace_packages": {
            "openai-whisper": "openai-whisper>=20231117"
        },
        "force_packages": ["torch>=2.0.0", "torchaudio"],
        "extra_index_urls": ["https://download.pytorch.org/whl/cu128"],
    },
    "faster-whisper": {
        "description": "Faster Whisper (CTranslate2)",
        "force_packages": ["ctranslate2>=4.0.0"],
        "env_vars": {"CT2_VERBOSE": "0"},
    },
    "f5-tts": {
        "description": "F5-TTS — синтез речи",
        "force_packages": ["torch>=2.3.0", "torchaudio"],
        "extra_index_urls": ["https://download.pytorch.org/whl/cu128"],
        "env_vars": {},
    },
    "ace-step": {
        "description": "ACE-Step — музыкальная генерация",
        "force_packages": ["torch>=2.3.0"],
        "extra_index_urls": ["https://download.pytorch.org/whl/cu128"],
        "env_vars": {"GRADIO_SERVER_PORT": "7865"},
    },
    "fooocus": {
        "description": "Fooocus — генерация изображений",
        "force_packages": ["torch==2.1.0", "torchvision==0.16.0"],
        "extra_index_urls": ["https://download.pytorch.org/whl/cu121"],
    },
    "text-generation-webui": {
        "description": "Oobabooga Text Generation WebUI",
        "skip_packages": ["llama-cpp-python", "exllamav2"],
        "env_vars": {"GRADIO_SERVER_PORT": "7860"},
        "force_packages": ["torch>=2.1.0"],
        "extra_index_urls": ["https://download.pytorch.org/whl/cu121"],
    },
}


class PatchManager:
    """Управляет патчами для известных репозиториев."""

    PATCHES_DIR = Path("patches")

    def __init__(self):
        self.patches = dict(BUILTIN_PATCHES)
        self._load_external_patches()

    # ------------------------------------------------------------------ #
    #  Публичные методы                                                   #
    # ------------------------------------------------------------------ #

    def find_patch(self, repo_name: str, repo_path: str = None) -> Optional[Dict]:
        """
        Ищет патч для репозитория.
        Сначала ищет по имени, потом анализирует содержимое.
        """
        name_lower = repo_name.lower().replace("_", "-").replace(" ", "-")

        # Точное совпадение
        if name_lower in self.patches:
            logger.info(f"🔧 Применяем встроенный патч для: {repo_name}")
            return self.patches[name_lower]

        # Частичное совпадение (например "CosyVoice2" → "cosyvoice")
        for key, patch in self.patches.items():
            if key in name_lower or name_lower in key:
                logger.info(f"🔧 Применяем патч '{key}' для: {repo_name}")
                return patch

        # Анализ содержимого репозитория
        if repo_path:
            detected = self._detect_from_content(Path(repo_path))
            if detected and detected in self.patches:
                logger.info(f"🔧 Определён тип проекта по содержимому: {detected}")
                return self.patches[detected]

        logger.info(f"ℹ️ Патч для '{repo_name}' не найден — используем стандартную сборку.")
        return None

    def apply_to_requirements(
        self,
        req_lines: List[str],
        patch: Dict,
        logs: List[str]
    ) -> List[str]:
        """
        Применяет патч к списку строк requirements.txt.
        Возвращает модифицированный список.
        """
        if not patch:
            return req_lines

        result = list(req_lines)
        replaced = patch.get("replace_packages", {})
        skip = set(p.lower() for p in patch.get("skip_packages", []))
        forced = patch.get("force_packages", [])

        # 1. Заменяем/пропускаем пакеты
        new_result = []
        for line in result:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_result.append(line)
                continue

            pkg = re.split(r"[>=<!;\[\s]", stripped)[0].lower().replace("_", "-")

            if pkg in skip:
                logs.append(f"🔧 Патч: пропускаем {stripped}")
                new_result.append(f"# [PATCH:SKIP] {stripped}\n")
                continue

            if pkg in replaced:
                new_val = replaced[pkg]
                logs.append(f"🔧 Патч: заменяем {stripped} → {new_val}")
                new_result.append(f"{new_val}\n")
                continue

            new_result.append(line)

        # 2. Добавляем принудительные пакеты в начало
        if forced:
            header = [f"# === PATCH: force packages ===\n"]
            for pkg in forced:
                pkg_name = re.split(r"[>=<!;\[\s]", pkg)[0].lower().replace("_", "-")
                # Убираем дубликат если уже есть
                new_result = [
                    l for l in new_result
                    if pkg_name not in l.lower() or l.strip().startswith("#")
                ]
                header.append(f"{pkg}\n")
                logs.append(f"🔧 Патч: принудительно {pkg}")
            new_result = header + new_result

        return new_result

    def get_env_vars(self, patch: Dict) -> Dict[str, str]:
        """Возвращает переменные окружения из патча."""
        return patch.get("env_vars", {}) if patch else {}

    def get_extra_index_urls(self, patch: Dict) -> List[str]:
        """Возвращает дополнительные index-url из патча."""
        return patch.get("extra_index_urls", []) if patch else []

    def get_post_install_commands(self, patch: Dict) -> List[str]:
        """Возвращает команды для выполнения после установки пакетов."""
        return patch.get("post_install", []) if patch else []

    def save_patch(self, repo_name: str, patch: Dict) -> bool:
        """Сохраняет пользовательский патч в папку patches/."""
        try:
            self.PATCHES_DIR.mkdir(exist_ok=True)
            path = self.PATCHES_DIR / f"{repo_name.lower()}.json"
            path.write_text(json.dumps(patch, indent=2, ensure_ascii=False), encoding="utf-8")
            self.patches[repo_name.lower()] = patch
            logger.info(f"💾 Патч сохранён: {path}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения патча: {e}")
            return False

    def list_known_repos(self) -> List[Dict]:
        """Возвращает список известных репозиториев с патчами."""
        return [
            {"name": k, "description": v.get("description", "")}
            for k, v in self.patches.items()
        ]

    # ------------------------------------------------------------------ #
    #  Внутренние методы                                                  #
    # ------------------------------------------------------------------ #

    def _load_external_patches(self):
        """Загружает патчи из папки patches/*.json."""
        if not self.PATCHES_DIR.exists():
            return
        for f in self.PATCHES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                key = f.stem.lower()
                self.patches[key] = data
                logger.debug(f"📦 Загружен внешний патч: {key}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось загрузить патч {f.name}: {e}")

    def _detect_from_content(self, repo_path: Path) -> Optional[str]:
        """Определяет тип проекта по файлам репозитория."""
        indicators = {
            "stable-diffusion-webui": ["launch.py", "webui.py", "modules/sd_models.py"],
            "comfyui": ["comfy/", "nodes.py", "comfy_extras/"],
            "cosyvoice": ["cosyvoice/", "CosyVoice/"],
            "whisper": ["whisper/decoding.py", "whisper/model.py"],
            "f5-tts": ["f5_tts/", "F5TTS/"],
            "text-generation-webui": ["modules/text_generation.py", "modules/models.py"],
        }
        for project, files in indicators.items():
            for indicator in files:
                check = repo_path / indicator
                if check.exists():
                    return project
        return None
