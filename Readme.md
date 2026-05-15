# 📦 PortableAI Creator

> Автоматический сборщик портативных версий AI-приложений из Git-репозиториев.
> Клонируй → собери → запускай — без установки на любой системе.

![Python](https://img.shields.io/badge/Python-3.10--3.13-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.3+-lightgrey?logo=flask)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-informational)
![Tests](https://img.shields.io/badge/Tests-24%20passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Возможности

- **Сборка в один клик** — вставьте URL репозитория → получаете ZIP со встроенным Python и всеми зависимостями
- **Логи в реальном времени** — SSE-трансляция прямо в браузер
- **Встроенные патчи** — 12+ AI-проектов работают «из коробки» (CosyVoice, ComfyUI, Whisper, SD WebUI и др.)
- **GPU-детект** — автоопределение CUDA / ROCm / CPU и установка нужной версии PyTorch
- **Pre-flight проверки** — система готова к сборке? Диагностика перед стартом
- **Sanity check** — после сборки проверяет, что всё реально работает
- **Конвертация Conda** — `environment.yml` → `requirements.txt` на лету
- **Отчёты об ошибках** — если сборка упала, сгенерируется ZIP с логами и диагнозом
- **Docker** — готовый образ для развёртывания на сервере
- **Веб-интерфейс** — дашборд, настройки, запуск/остановка приложений

---

## 🚀 Быстрый старт

### Windows

```bat
git clone https://github.com/ESlavin1808/PortableAI-Creator.git
cd PortableAI-Creator
start.bat
```

При первом запуске автоматически создаст виртуальное окружение и установит зависимости. Откроется браузер с интерфейсом.

### Linux / macOS

```bash
git clone https://github.com/ESlavin1808/PortableAI-Creator.git
cd PortableAI-Creator
chmod +x install.sh start.sh
./install.sh
./start.sh
```

### Docker

```bash
docker compose up -d
# Откройте http://127.0.0.1:5000
```

После запуска откройте **http://127.0.0.1:5000** и вставьте URL репозитория — например `https://github.com/openai/whisper` или `https://github.com/AUTOMATIC1111/stable-diffusion-webui`.

---

## 📖 Как это работает

```
Git repo URL
    │
    ▼
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Pre-flight  │────▶│  Pipeline    │────▶│  Sanity      │
│  проверки    │     │  (9 шагов)   │     │  check       │
└─────────────┘     └──────────────┘     └──────────────┘
                          │
                    ┌─────┴──────┐
                    ▼            ▼
              ┌──────────┐ ┌──────────┐
              │ Portable │ │  Отчёт   │
              │ app + ZIP│ │  (если   │
              │          │ │  ошибка) │
              └──────────┘ └──────────┘
```

**Pipeline из 9 шагов:**
1. **Подготовка** — поиск патча, создание папки
2. **Копирование** — исходники репозитория
3. **Python** — установка портативной версии
4. **Зависимости** — pip install с учётом патча и GPU
5. **Post-install** — дополнительные команды из патча
6. **Установка проекта** — `pip install -e .` или копирование
7. **Лаунчеры** — .bat / .sh файлы запуска
8. **Проверка** — sanity check (импорт torch, cuda, gradio...)
9. **Архивация** — упаковка в ZIP

---

## 📋 Встроенные патчи

| Проект | Описание |
|--------|----------|
| `stable-diffusion-webui` | AUTOMATIC1111 |
| `stable-diffusion-webui-forge` | Forge (форк) |
| `comfyui` | ComfyUI нодовый интерфейс |
| `cosyvoice` | CosyVoice TTS от Alibaba |
| `whisper` / `faster-whisper` | OpenAI Whisper |
| `f5-tts` | F5-TTS синтез речи |
| `ace-step` | Музыкальная генерация |
| `fooocus` | Fooocus изображения |
| `text-generation-webui` | Oobabooga LLM |
| `ollama` | Ollama LLM |

Добавить новый — создать `patches/имя.json`.

---

## 📁 Структура проекта

```
PortableAI-Creator/
├── main.py              # Flask веб-интерфейс (маршруты, SSE)
├── builder.py           # Фасад сборки (делегирует в pipeline)
├── pipeline.py          # Конвейер из 9 шагов
├── git_parser.py        # Клонирование и анализ
├── platform_support.py  # Portable Python, лаунчеры, GPU
├── patch_manager.py     # Система патчей
├── preflight.py         # Pre-flight диагностика
├── sanity_check.py      # Тест после сборки
├── error_reporter.py    # ZIP-отчёты об ошибках
├── ai_optimizer.py      # Оптимизация размера
├── conda_support.py     # Conda → pip конвертация
├── validator.py         # Валидация сборки
├── settings.py          # Настройки (dataclass + JSON)
├── config.json          # Конфигурация (создаётся автоматом)
├── requirements.txt     # Зависимости
├── Dockerfile           # Контейнеризация
├── docker-compose.yml   # Docker Compose
├── .github/workflows/   # CI (тесты на push)
├── patches/             # Внешние патчи *.json
├── static/              # CSS, JS для веб-интерфейса
├── templates/           # HTML шаблоны Flask
└── tests/               # 24 юнит-теста (pytest)
```

---

## 🧪 Тесты

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

Все 24 теста проходят на Python 3.10–3.13.

---

## ⚙️ Настройки

Веб-интерфейс → `/settings`, либо `config.json`:

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `python_version` | `3.11` | Версия portable Python |
| `install_timeout` | `600` | Тайм-аут (сек) |
| `enable_compression` | `true` | ZIP-упаковка |
| `run_sanity_check` | `true` | Проверка после сборки |
| `allowed_hosts` | `127.0.0.1,localhost` | Доступ по хосту |

---

## 🐳 Docker

```bash
docker compose up -d
# или вручную:
docker build -t portableai-creator .
docker run -p 5000:5000 portableai-creator
```

Монтируемые тома: `./output`, `./patches`, `./data`.

---

## 🤝 Участие

Pull requests приветствуются. Особенно:
- Новые патчи в `patches/*.json`
- Тесты для validator.py, platform_support.py
- Улучшения Linux/macOS поддержки

---

## 📄 Лицензия

MIT — можно всё, включая коммерческое использование.

---

## ⭐ Если проект полезен

Поставьте звезду на GitHub — это помогает развитию.
