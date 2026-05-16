# main.py — Веб-интерфейс PortableAI Creator (с pre-flight, sanity check, patch system)
import os
import sys
import logging
import json
import subprocess
import shutil
import time
import stat
import threading
from queue import Queue
from pathlib import Path

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, send_file, abort, Response)

from git_parser import GitRepoParser
from settings import SettingsManager
from builder import PortableBuilder
from preflight import PreflightChecker
from patch_manager import PatchManager
from error_reporter import ErrorReporter

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 GB

# ── ALLOWED_HOSTS защита ──────────────────────────────────────────
@app.before_request
def check_allowed_host():
    allowed = settings_mgr.settings.allowed_hosts
    if allowed:
        hosts = [h.strip() for h in allowed.split(",") if h.strip()]
        if hosts:
            host_part = request.host.split(":")[0]  # без порта
            if host_part not in hosts:
                abort(403)

repo_parser = GitRepoParser()
settings_mgr = SettingsManager()
builder = PortableBuilder(settings_mgr)
patch_mgr = PatchManager()
reporter = ErrorReporter()

# ================================================================== #
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ                                           #
# ================================================================== #

def get_installed_apps():
    output_path = Path(settings_mgr.settings.output_dir)
    apps = []
    if not output_path.exists():
        return apps
    for item in output_path.iterdir():
        if item.is_dir() and item.name.endswith("_portable"):
            apps.append({
                "name": item.name.replace("_portable", ""),
                "path": str(item),
                "size_mb": round(
                    sum(f.stat().st_size for f in item.rglob('*') if f.is_file()) / 1048576, 1
                ),
                "is_running": is_process_running(item) if HAS_PSUTIL else False,
                "has_archive": (output_path / f"{item.name}.zip").exists()
            })
    return apps


def is_process_running(app_path: Path) -> bool:
    if not HAS_PSUTIL:
        return False
    python_exe = app_path / "python_portable" / "python.exe"
    if not python_exe.exists():
        return False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if cmdline and str(python_exe) in " ".join(cmdline):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def launch_app(app_path: Path):
    bat_file = app_path / f"run_{app_path.name.replace('_portable', '')}.bat"
    if bat_file.exists():
        os.startfile(str(bat_file))
        return True
    app_py = app_path / "app.py"
    if app_py.exists():
        python_exe = app_path / "python_portable" / "python.exe"
        subprocess.Popen([str(python_exe), str(app_py)], cwd=str(app_path))
        return True
    return False


def stop_app(app_path: Path) -> bool:
    if not HAS_PSUTIL:
        return False
    python_exe = app_path / "python_portable" / "python.exe"
    killed = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if cmdline and str(python_exe) in " ".join(cmdline):
                proc.kill()
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed


def force_remove_readonly(func, path, exc_info):
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise


def safe_delete_path(path: Path):
    if not path.exists():
        return True
    try:
        shutil.rmtree(path, onerror=force_remove_readonly)
        return True
    except Exception as e:
        logger.warning(f"Первая попытка удаления не удалась: {e}")
    for _ in range(5):
        time.sleep(1)
        try:
            shutil.rmtree(path, onerror=force_remove_readonly)
            return True
        except Exception:
            pass
    if sys.platform == 'win32':
        try:
            subprocess.run(['cmd', '/c', 'rd', '/s', '/q', str(path)],
                           check=True, timeout=10)
            return not path.exists()
        except Exception:
            pass
    return False


def format_result_html(data: dict) -> str:
    if not data.get('success'):
        return f'<p style="color:#ef4444;">❌ Ошибка: {data.get("error", "Неизвестная ошибка")}</p>'

    html_parts = []
    html_parts.append(
        f'<p>✅ <b>{data["repo_name"]}</b> (commit: <code>{data["commit"][:8]}</code>)</p>'
    )

    # Известный патч?
    known = patch_mgr.find_patch(data["repo_name"])
    if known:
        html_parts.append(
            f'<p style="color:#2563eb;">🔧 Патч найден: <b>{known.get("description", "")}</b></p>'
        )

    if data.get('detected_languages'):
        badges = ''.join(
            f'<span style="background:#e2e8f0;padding:2px 8px;border-radius:4px;'
            f'margin-right:4px;font-size:12px;">{lang}</span>'
            for lang in data['detected_languages']
        )
        html_parts.append(f'<p><b>Языки:</b> {badges}</p>')

    if data.get('dependencies'):
        html_parts.append(
            '<p><b>Найдены зависимости:</b></p>'
            '<ul style="font-size:13px;margin-top:5px;">'
        )
        for lang, deps in data['dependencies'].items():
            count = (len(deps) if isinstance(deps, list)
                     else sum(len(v) for v in deps.values() if isinstance(v, list)))
            html_parts.append(f'<li><b>{lang}:</b> {count} пакетов</li>')
        html_parts.append('</ul>')

    html_parts.append(
        f'<p style="color:#64748b;font-size:12px;margin-top:10px;">'
        f'📁 Путь: <code>{data["path"]}</code></p>'
    )

    safe_name = data['repo_name'].replace("'", "\\'").replace('"', '&quot;')
    safe_path = data['path'].replace("\\", "\\\\").replace("'", "\\'").replace('"', '&quot;')

    btn_html = f"""
    <div style="margin-top:20px;border-top:1px solid #eee;padding-top:15px;">
        <button onclick="startBuildSSE('{safe_name}', '{safe_path}')"
                class="btn btn-primary" style="width:100%;font-size:16px;padding:15px;">
            🛠️ СОБРАТЬ ПОРТАТИВНУЮ ВЕРСИЮ
        </button>
        <div id="buildStatus" style="margin-top:10px;font-weight:bold;"></div>
        <div id="sanityBlock" style="display:none;margin-top:10px;"></div>
        <div id="reportBlock" style="display:none;margin-top:8px;"></div>
        <div id="buildLogs" style="display:none;margin-top:10px;" class="log"></div>
    </div>
    """
    html_parts.append(btn_html)
    return ''.join(html_parts)


# ================================================================== #
#  МАРШРУТЫ                                                          #
# ================================================================== #

@app.route('/', methods=['GET'])
def index():
    return render_template(
        'index.html',
        result_html=request.args.get('result_html'),
        logs_text=request.args.get('logs_text'),
        preflight_html=request.args.get('preflight_html'),
    )

@app.route('/settings')
def settings_page():
    path_errors = settings_mgr.validate_paths()   # создаём папки, собираем ошибки
    return render_template(
        'settings.html',
        s=settings_mgr.settings,                  # 's' вместо 'settings' — не конфликтует
        path_errors=path_errors,
    )


@app.route('/settings/save', methods=['POST'])
def save_settings():
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No data'}), 400

        # Все ключи, которые разрешено сохранять
        INT_KEYS   = {'git_timeout_seconds', 'compression_level',
                      'log_max_size_mb', 'install_timeout'}
        FLOAT_KEYS = {'ai_confidence_threshold'}
        BOOL_KEYS  = {'git_shallow_clone', 'create_launcher', 'enable_compression',
                      'enable_ai_optimization', 'strip_debug_symbols', 'run_sanity_check',
                      'use_proxy', 'verify_ssl', 'log_to_file', 'enable_telemetry'}

        for key, value in data.items():
            if not hasattr(settings_mgr.settings, key):
                continue                           # тихо игнорируем неизвестные

            if key in INT_KEYS:
                try: value = int(value)
                except (ValueError, TypeError): pass
            elif key in FLOAT_KEYS:
                try: value = float(value)
                except (ValueError, TypeError): pass
            elif key in BOOL_KEYS:
                if isinstance(value, str):
                    value = value.lower() in ('true', '1', 'yes')

            settings_mgr.set(key, value, autosave=False)

        ok = settings_mgr.save()
        return jsonify({'success': ok}) if ok else jsonify({'success': False, 'error': 'Disk error'}), 500

    except Exception as e:
        logger.exception("save_settings error")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/settings/reset', methods=['POST'])
def reset_settings():
    ok = settings_mgr.reset_to_defaults()
    return jsonify({'success': ok})


@app.route('/api/validate_paths', methods=['POST'])
def api_validate_paths():
    errors = settings_mgr.validate_paths()
    return jsonify({'errors': errors, 'ok': len(errors) == 0})

@app.route('/analyze', methods=['GET', 'POST'])
def analyze_route():
    if request.method == 'GET':
        repo_url = request.args.get('repo', '').strip()
        branch = None
    else:
        repo_url = request.form.get('repo_url', '').strip()
        branch = request.form.get('branch')

    if not repo_url:
        return redirect(url_for('index'))

    # Pre-flight проверка
    checker = PreflightChecker(
        output_dir=settings_mgr.settings.output_dir,
        temp_dir=settings_mgr.settings.temp_dir
    )
    pf = checker.run(is_ai_project=True)
    preflight_html = pf["html"]

    logs = []
    try:
        logs.append(f"📥 Клонирование: {repo_url}")
        metadata = repo_parser.clone_repo(repo_url, branch)
        if metadata.get('success'):
            logs.append(f"✅ Клонировано: {metadata.get('files_count', 0)} файлов")
            result_html = format_result_html(metadata)
            return redirect(url_for('index',
                                    result_html=result_html,
                                    logs_text="\n".join(logs),
                                    preflight_html=preflight_html))
        else:
            logs.append(f"❌ Ошибка: {metadata.get('error')}")
            return redirect(url_for('index',
                                    logs_text="\n".join(logs),
                                    preflight_html=preflight_html))
    except Exception as e:
        logs.append(f"❌ Исключение: {str(e)}")
        return redirect(url_for('index',
                                logs_text="\n".join(logs),
                                preflight_html=preflight_html))

@app.route('/api/preflight', methods=['POST'])
def api_preflight():
    checker = PreflightChecker(
        output_dir=settings_mgr.settings.output_dir,
        temp_dir=settings_mgr.settings.temp_dir
    )
    result = checker.run(is_ai_project=True)
    return jsonify(result)

@app.route('/api/build_portable', methods=['POST'])
def api_build_portable():
    data = request.get_json()
    result = builder.build_from_repo(data.get('repo_name'), data.get('repo_path'))
    status = 200 if result['success'] else 500
    response = {
        'success': result['success'],
        'logs': result.get('logs', []),
        'archive_path': result.get('archive_path'),
        'sanity': result.get('sanity'),
        'report_path': result.get('report_path'),
        'error': result.get('error'),
    }
    return jsonify(response), status

@app.route('/api/apps', methods=['GET'])
def api_get_apps():
    return jsonify(get_installed_apps())

@app.route('/api/known_repos', methods=['GET'])
def api_known_repos():
    return jsonify(patch_mgr.list_known_repos())

@app.route('/api/app_control', methods=['POST'])
def api_app_control():
    data = request.json
    path = Path(data.get('path'))
    action = data.get('action')
    if action == 'run':
        return jsonify({'success': launch_app(path)})
    elif action == 'stop':
        return jsonify({'success': stop_app(path)})
    return jsonify({'success': False})

@app.route('/api/open_folder', methods=['POST'])
def api_open_folder():
    path = request.json.get('path')
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])
    return jsonify({'success': True})

@app.route('/api/delete_app', methods=['POST'])
def api_delete_app():
    data = request.json
    path = Path(data.get('path'))
    archive = Path(str(path) + ".zip")
    if not path.exists():
        return jsonify({'success': True, 'message': 'Папка уже отсутствует'})
    try:
        stop_app(path)
        time.sleep(2)
        deleted = safe_delete_path(path)
        if archive.exists():
            try: archive.unlink()
            except: pass
        if deleted:
            return jsonify({'success': True, 'message': 'Приложение успешно удалено'})
        return jsonify({'success': False,
                        'message': 'Не удалось удалить. Попробуйте перезагрузить ПК.'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'}), 500

@app.route('/download')
def download_file():
    file_path = request.args.get('file')
    if file_path and Path(file_path).exists():
        return send_file(file_path, as_attachment=True)
    return "Файл не найден", 404

@app.route('/download_report')
def download_report():
    file_path = request.args.get('file')
    if file_path and Path(file_path).exists():
        return send_file(file_path, as_attachment=True,
                         download_name=Path(file_path).name)
    return "Отчёт не найден", 404

@app.route('/build/sse')
def build_sse():
    """SSE-поток для логов сборки в реальном времени."""
    repo_input = request.args.get('repo', '').strip()
    if not repo_input:
        return "No repo specified", 400

    # Определяем: это URL или локальный путь?
    if '://' in repo_input:
        # URL → извлекаем имя и находим локальный путь
        repo_name = repo_input.rstrip('/').split('/')[-1].replace('.git', '')
        repo_path = Path(settings_mgr.settings.temp_dir) / "repos" / repo_name
    else:
        # Локальный путь → используем как есть
        repo_path = Path(repo_input)
        repo_name = repo_path.name

    q: Queue = Queue()

    def on_log(msg: str):
        q.put(msg)

    def run_build():
        try:
            builder.build_stream(repo_name, str(repo_path), on_log=on_log)
        except Exception as e:
            q.put(f"❌ {e}")
        finally:
            q.put("__DONE__")

    thread = threading.Thread(target=run_build, daemon=True)
    thread.start()

    def generate():
        while True:
            msg = q.get()
            if msg == "__DONE__":
                yield "data: __DONE__\n\n"
                break
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

if __name__ == '__main__':
    # Проверяем, что порт свободен
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', 5000))
        sock.close()
    except OSError:
        print()
        print("=" * 60)
        print("  [ОШИБКА] Порт 5000 уже занят!")
        print()
        # Пытаемся найти процесс, который занял порт
        pid_info = ""
        try:
            import subprocess
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True,
                timeout=5
            )
            for line in result.stdout.splitlines():
                if "127.0.0.1:5000" in line:
                    parts = line.strip().split()
                    if parts:
                        pid = parts[-1]
                        pid_info += f"    PID: {pid}\n"
                        # Пробуем узнать имя процесса
                        try:
                            proc = subprocess.run(
                                ["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv"],
                                capture_output=True, text=True, timeout=3
                            )
                            for pline in proc.stdout.splitlines()[1:2]:
                                name = pline.split(",")[0].strip('"')
                                pid_info += f"    Процесс: {name}\n"
                        except Exception:
                            pass
            if pid_info:
                print(f"  Найден процесс на порту 5000:")
                print(pid_info)
        except Exception:
            pass
        print("  Решения:")
        print("    1. Закройте программу, которая использует порт")
        print("    2. Или выполните: taskkill /PID <номер> /F")
        print("    3. Или измените порт в config.json")
        print("=" * 60)
        print()
        sys.exit(1)

    print("=" * 60)
    print("  >> PortableAI Creator <<")
    print("  >> http://127.0.0.1:5000")
    print("=" * 60)
    try:
        app.run(host='127.0.0.1', port=5000, debug=False)
    except OSError as e:
        print(f"\n  [ОШИБКА] Не удалось запустить сервер: {e}")
        input("\n  Нажмите Enter для выхода...")
    except KeyboardInterrupt:
        print("\n  [ГОТОВО] Сервер остановлен.")
