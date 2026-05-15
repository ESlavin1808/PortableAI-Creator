#!/usr/bin/env bash
cd "$(dirname "$0")"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   🔄 PortableAI Creator — Обновление    ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Проверка Git ──────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    echo "  [ОШИБКА] Git не найден."
    exit 1
fi

# ── Текущая версия ────────────────────────────────────────────────
echo "  [INFO] Текущий коммит:"
git log -1 --format="    %h  %s  (%ar)" 2>/dev/null
echo ""

# ── Сохраняем config.json ────────────────────────────────────────
CONFIG_BACKUP=0
if [ -f "config.json" ]; then
    cp config.json config.json.bak
    CONFIG_BACKUP=1
    echo "  [OK] Настройки сохранены в config.json.bak"
fi

# ── Получаем обновления ───────────────────────────────────────────
echo "  [ОБНОВЛЕНИЕ] Загружаем изменения с GitHub..."
git pull origin main
if [ $? -ne 0 ]; then
    echo "  [ОШИБКА] Не удалось обновиться."
    [ $CONFIG_BACKUP -eq 1 ] && cp config.json.bak config.json && \
        echo "  [OK] Настройки восстановлены."
    exit 1
fi

# ── Восстанавливаем config.json ──────────────────────────────────
if [ $CONFIG_BACKUP -eq 1 ]; then
    cp config.json.bak config.json
    echo "  [OK] Настройки восстановлены."
fi

# ── Обновляем зависимости ─────────────────────────────────────────
if [ ! -f "venv/bin/activate" ]; then
    echo "  [УСТАНОВКА] Создаём виртуальное окружение..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "  [ОБНОВЛЕНИЕ] Обновляем Python-зависимости..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --upgrade

# ── Права на скрипты (на случай если добавились новые) ───────────
chmod +x *.sh 2>/dev/null

# ── Новая версия ──────────────────────────────────────────────────
echo ""
echo "  [INFO] Новый коммит:"
git log -1 --format="    %h  %s  (%ar)" 2>/dev/null
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   ✅ Обновление завершено!               ║"
echo "  ║   Запустите: ./start.sh                  ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
