@echo off
chcp 65001 >nul
cd /d "%~dp0"
title PortableAI Creator — Установка

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   📦 PortableAI Creator — Установка     ║
echo  ╚══════════════════════════════════════════╝
echo.

:: ── Проверка Python ───────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Python не найден в PATH.
    echo.
    echo  Установите Python 3.10–3.12 с https://python.org/downloads/
    echo  При установке ОБЯЗАТЕЛЬНО отметьте "Add Python to PATH"
    echo.
    start https://python.org/downloads/
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python %PY_VER% найден.

:: ── Проверка Git ──────────────────────────────────────────────────
git --version >nul 2>&1
if errorlevel 1 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] Git не найден.
    echo  Git нужен для клонирования репозиториев.
    echo  Скачать: https://git-scm.com/download/win
    echo.
    set /p CONT="Продолжить без Git? (y/n): "
    if /i not "%CONT%"=="y" ( pause & exit /b 1 )
) else (
    for /f "tokens=3" %%v in ('git --version') do echo  [OK] Git %%v найден.
)

:: ── Создание виртуального окружения ──────────────────────────────
if exist "venv\Scripts\activate.bat" (
    echo  [OK] Виртуальное окружение уже существует.
) else (
    echo  [УСТАНОВКА] Создаём виртуальное окружение...
    python -m venv venv
    if errorlevel 1 (
        echo  [ОШИБКА] Не удалось создать venv.
        pause & exit /b 1
    )
    echo  [OK] Виртуальное окружение создано.
)

:: ── Установка зависимостей ────────────────────────────────────────
echo  [УСТАНОВКА] Устанавливаем зависимости...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Не удалось установить зависимости.
    echo  Проверьте интернет и попробуйте снова.
    pause & exit /b 1
)

:: ── Создание папок ────────────────────────────────────────────────
if not exist "output\portable" mkdir "output\portable"
if not exist "temp"            mkdir "temp"
if not exist "logs"            mkdir "logs"
if not exist "patches"         mkdir "patches"

:: ── Проверка Flask ────────────────────────────────────────────────
venv\Scripts\python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo  [ОШИБКА] Flask не установился. Попробуйте ещё раз.
    pause & exit /b 1
)

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   ✅ Установка завершена успешно!        ║
echo  ║   Запустите start.bat для старта.        ║
echo  ╚══════════════════════════════════════════╝
echo.
pause
