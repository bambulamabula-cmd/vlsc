# VLSC

Минимальный каркас FastAPI-приложения для мобильного (mobile-first) мониторинга серверов.

## Структура

```text
app/
  main.py
  config.py
  db.py
  models.py
  vless/
  checks/
  services/
  utils/
  web/
    routes.py
    templates/
    static/
tests/
```

## Быстрый запуск в Termux (Android)

1. Установите Termux (F-Droid версия предпочтительнее).
2. Установите зависимости системы:
   ```bash
   pkg update && pkg upgrade -y
   pkg install -y python git clang libffi openssl
   ```
3. Клонируйте проект и создайте виртуальное окружение:
   ```bash
   git clone <repo-url> vlsc
   cd vlsc
   python -m venv .venv
   source .venv/bin/activate
   ```
4. Установите Python-зависимости:
   ```bash
   pip install --upgrade pip
   pip install fastapi uvicorn sqlalchemy pydantic pydantic-settings jinja2 pytest httpx
   ```
5. Запустите приложение:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
6. Откройте в браузере Android: `http://127.0.0.1:8000`.

## Ограничения Android/Termux

- Фоновые процессы могут «замораживаться» системой, особенно при выключенном экране.
- Aggressive Doze/App Standby могут ограничивать сетевую активность и таймеры.
- SQLite на медленных накопителях может быть узким местом при высоком `concurrency`.
- Долгие фоновые задачи нестабильны без внешнего watchdog/пере-запуска.

## Рекомендации по энергосбережению

- Добавьте Termux в исключения оптимизации батареи (`Battery optimization -> Don't optimize`).
- Используйте `termux-wake-lock` перед длительным запуском и `termux-wake-unlock` после.
- Поддерживайте низкий `concurrency_limit` и разумные таймауты в `app/config.py`.
- Для регулярного старта задач используйте Termux:Boot + безопасные интервалы.

## Проверка работоспособности

- Health-check: `GET /health`
- Главная страница: `GET /`
- Страница сканирования: `GET /scan`
- Детали сервера: `GET /servers/{id}`
