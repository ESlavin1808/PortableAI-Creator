#!/usr/bin/env bash
cd "$(dirname "$0")"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   📦 PortableAI Creator                 ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Проверка установки ────────────────────────────────────────────
if [ ! -f "venv/bin/activate" ]; then
    echo "  [!] Окружение не найдено. Запустите сначала:"
    echo "      ./install.sh"
    exit 1
fi

source venv/bin/activate

python -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  [!] Зависимости не установлены. Запустите ./install.sh"
    exit 1
fi

echo "  [OK] Окружение активировано."
echo "  [>>] http://127.0.0.1:5000"
echo ""

# Открываем браузер (работает на macOS и большинстве Linux)
(sleep 2 && \
    if command -v xdg-open &>/dev/null; then
        xdg-open http://127.0.0.1:5000
    elif command -v open &>/dev/null; then
        open http://127.0.0.1:5000
    fi
) &

python main.py

echo ""
echo "  Сервер остановлен."
