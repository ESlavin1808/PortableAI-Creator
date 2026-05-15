#!/usr/bin/env bash
cd "$(dirname "$0")"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   📦 PortableAI Creator — Установка     ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Проверка Python ───────────────────────────────────────────────
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  [ОШИБКА] Python 3.10+ не найден."
    echo "  Ubuntu/Debian:  sudo apt install python3 python3-venv python3-pip"
    echo "  macOS:          brew install python"
    exit 1
fi

PY_VER=$($PYTHON --version 2>&1)
echo "  [OK] $PY_VER найден ($PYTHON)"

# ── Проверка Git ──────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    echo "  [ПРЕДУПРЕЖДЕНИЕ] Git не найден."
    echo "  Ubuntu/Debian:  sudo apt install git"
    echo "  macOS:          brew install git"
    read -p "  Продолжить без Git? (y/n): " CONT
    [ "$CONT" != "y" ] && exit 1
else
    echo "  [OK] $(git --version)"
fi

# ── Проверка python3-venv (Linux) ────────────────────────────────
if ! $PYTHON -m venv --help &>/dev/null; then
    echo "  [УСТАНОВКА] Устанавливаем python3-venv..."
    sudo apt-get install -y python3-venv 2>/dev/null || \
    sudo yum install -y python3-venv 2>/dev/null || \
    echo "  [!] Установите вручную: sudo apt install python3-venv"
fi

# ── Виртуальное окружение ─────────────────────────────────────────
if [ -d "venv" ]; then
    echo "  [OK] Виртуальное окружение уже существует."
else
    echo "  [УСТАНОВКА] Создаём виртуальное окружение..."
    $PYTHON -m venv venv
    if [ $? -ne 0 ]; then
        echo "  [ОШИБКА] Не удалось создать venv."
        exit 1
    fi
    echo "  [OK] Виртуальное окружение создано."
fi

# ── Установка зависимостей ────────────────────────────────────────
echo "  [УСТАНОВКА] Устанавливаем зависимости..."
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "  [ОШИБКА] Не удалось установить зависимости."
    exit 1
fi

# ── Создание папок ────────────────────────────────────────────────
mkdir -p output/portable temp logs patches

# ── Права на sh-скрипты ───────────────────────────────────────────
chmod +x start.sh update.sh 2>/dev/null

# ── Проверка Flask ────────────────────────────────────────────────
python -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  [ОШИБКА] Flask не установился."
    exit 1
fi

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   ✅ Установка завершена!                ║"
echo "  ║   Запустите: ./start.sh                  ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
