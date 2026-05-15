@echo off
chcp 65001 >nul
cd /d "%~dp0"
title PortableAI Creator — Обновление

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   🔄 PortableAI Creator — Обновление    ║
echo  ╚══════════════════════════════════════════╝
echo.

:: ── Проверка Git ──────────────────────────────────────────────────
git --version >nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Git не найден. Обновление через git невозможно.
    pause & exit /b 1
)

:: ── Показываем текущую версию ─────────────────────────────────────
echo  [INFO] Текущий коммит:
git log -1 --format="  %%h  %%s  (%%ar)" 2>nul
echo.

:: ── Сохраняем config.json ────────────────────────────────────────
set CONFIG_BACKUP=0
if exist "config.json" (
    copy /y "config.json" "config.json.bak" >nul
    set CONFIG_BACKUP=1
    echo  [OK] Настройки сохранены в config.json.bak
)

:: ── Получаем обновления из GitHub ────────────────────────────────
echo  [ОБНОВЛЕНИЕ] Загружаем изменения с GitHub...
git pull origin main
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Не удалось получить обновления.
    echo  Проверьте интернет или наличие конфликтов.
    if "%CONFIG_BACKUP%"=="1" (
        copy /y "config.json.bak" "config.json" >nul
        echo  [OK] Настройки восстановлены из резервной копии.
    )
    pause & exit /b 1
)

:: ── Восстанавливаем config.json ──────────────────────────────────
if "%CONFIG_BACKUP%"=="1" (
    copy /y "config.json.bak" "config.json" >nul
    echo  [OK] Настройки восстановлены.
)

:: ── Обновляем зависимости Python ─────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo  [УСТАНОВКА] Создаём виртуальное окружение...
    python -m venv venv
)

echo  [ОБНОВЛЕНИЕ] Обновляем Python-зависимости...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\pip install -r requirements.txt --upgrade
if errorlevel 1 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] Некоторые пакеты не обновились.
)

:: ── Показываем новую версию ───────────────────────────────────────
echo.
echo  [INFO] Новый коммит:
git log -1 --format="  %%h  %%s  (%%ar)" 2>nul
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   ✅ Обновление завершено!               ║
echo  ║   Запустите start.bat                    ║
echo  ╚══════════════════════════════════════════╝
echo.
pause
