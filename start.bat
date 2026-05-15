@echo off
chcp 65001 >nul 2>&1
ver >nul

title PortableAI Creator

echo ========================================
echo   PortableAI Creator — запуск
echo ========================================
echo.

:: ── Проверка venv ────────────────────────────────────────────────
if not exist "venv\Scripts\python.exe" (
    echo [ОШИБКА] Виртуальное окружение не найдено.
    echo Запустите install.bat для первой установки.
    pause
    exit /b 1
)

:: ── Проверка Flask ────────────────────────────────────────────────
venv\Scripts\python.exe -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo [УСТАНОВКА] Flask не найден, устанавливаю зависимости...
    venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось обновить pip.
        pause
        exit /b 1
    )
    venv\Scripts\pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Установка зависимостей провалилась.
        pause
        exit /b 1
    )
    echo [OK] Зависимости установлены.
)

:: ── Повторная проверка ───────────────────────────────────────────
venv\Scripts\python.exe -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] Flask всё ещё не найден после установки.
    pause
    exit /b 1
)

:: ── Проверка порта 5000 ──────────────────────────────────────────
netstat -an 2>nul | find "127.0.0.1:5000" >nul
if %errorlevel% equ 0 (
    echo.
    echo [ПРЕДУПРЕЖДЕНИЕ] Порт 5000 уже занят!
    echo Возможно работает предыдущая копия программы.
    echo Закройте её или смените порт в настройках.
    echo.
)

:: ── Запуск ────────────────────────────────────────────────────────
echo [OK] Окружение готово.
echo.
echo Сайт откроется в браузере через пару секунд.
echo Адрес: http://127.0.0.1:5000
echo Для остановки нажмите Ctrl+C в этом окне.
echo.

:: Авто-открытие браузера с задержкой 2 секунды
start "" /b cmd /c "ping 127.0.0.1 -n 3 >nul && start http://127.0.0.1:5000" >nul 2>&1

venv\Scripts\python.exe main.py

:: Если сюда попали — main.py завершился (ошибка или Ctrl+C)
echo.
if %errorlevel% neq 0 (
    echo [ОШИБКА] main.py завершился с кодом %errorlevel%
    echo.
) else (
    echo [ГОТОВО] Сервер остановлен.
    echo.
)
pause
