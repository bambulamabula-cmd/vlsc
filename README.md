# VLSC

Минимальный FastAPI-сервис для mobile-first мониторинга серверов с веб-интерфейсом, импортом VLESS URI, сканированием и хранением истории проверок в SQLite.

## Возможности

- Веб-дашборд: список серверов, состояние сканирования и карточка сервера.
- Импорт VLESS URI (текстом или `.txt` файлом).
- API для списка серверов, деталей, jobs и экспорта CSV.
- Управление сканированием (`start/stop`) и отчистка истории (`retention cleanup`).
- Локальное хранение данных через SQLite + SQLAlchemy.

## Стек

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy 2.x
- Pydantic Settings
- Jinja2 (шаблоны)

> ⚠️ Начиная с текущей версии поддержка Python 3.10 прекращена (breaking change для окружений на 3.10).

## Структура проекта

```text
app/
  main.py
  config.py
  db.py
  models.py
  checks/
  services/
  utils/
  vless/
  web/
    routes.py
    templates/
    static/
tests/
```

## Быстрый старт

```bash
git clone <repo-url> vlsc
cd vlsc
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

Для разработки:

```bash
pip install -e ".[dev]"
```

Запуск:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Проверка:

- UI: `http://127.0.0.1:8000/`
- Health: `http://127.0.0.1:8000/health`

## Настройки (ENV)

Конфигурация читается из переменных с префиксом `VLSC_` (см. `app/config.py`):

- `VLSC_APP_NAME` (default: `VLSC`)
- `VLSC_DEBUG` (default: `false`)
- `VLSC_CHECK_TIMEOUT_SECONDS` (default: `10`)
- `VLSC_REQUEST_TIMEOUT_SECONDS` (default: `20`)
- `VLSC_CONCURRENCY_LIMIT` (default: `20`)
- `VLSC_SQLITE_PATH` (default: `./vlsc.db`)
- `VLSC_RETENTION_DAYS` (default: `30`)
- `VLSC_XRAY_ENABLED` (default: `false`)

Пример:

```bash
export VLSC_SQLITE_PATH=./data/vlsc.db
export VLSC_XRAY_ENABLED=true
```

## API (кратко)

- `GET /health` — health-check.
- `GET /` — dashboard.
- `GET /scan` — страница запуска/контроля сканирования.
- `GET /servers/{id}` — страница деталей сервера.
- `POST /api/import` — импорт URI (`uris_text` и/или `uris_file`).
- `GET /api/servers` — список серверов (`alive`, `xray`, `top`, `sort`).
- `GET /api/servers/{server_id}` — сервер + история проверок.
- `POST /api/scan/start` — запуск сканирования (`mode`).
- `POST /api/scan/stop` — остановка активного сканирования.
- `GET /api/jobs/{job_id}` — статус задачи.
- `GET /api/export` — экспорт серверов в CSV.
- `POST /api/retention/cleanup` — очистка и агрегация истории.

## Termux (Android)

```bash
pkg update && pkg upgrade -y
pkg install -y python git clang libffi openssl
```

Далее шаги те же, что в «Быстрый старт».

Рекомендации:

- Добавьте Termux в исключения Battery Optimization.
- Для долгих сессий используйте `termux-wake-lock`.
- Не завышайте `VLSC_CONCURRENCY_LIMIT` на слабых устройствах.

## Ограничения

- Фоновые процессы в Android/Termux могут быть ограничены системой.
- SQLite может стать узким местом при высокой параллельности.
- Долгие фоновые задачи лучше запускать с внешним watchdog/рестартом.
