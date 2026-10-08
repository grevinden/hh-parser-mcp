# AGENTS.md

This file provides guidance to agents when working with code in this repository.
Фиксируй изменения в git commits.
Создавай прослеживаемую последовательность изменений.
Сделай коммит, когда закончил работу над задачей.

## Сервис предоставляет следующие возможности. 
- Получение данных о работодателе по идентификатору employer_id
- Получение данных о вакансии + о работодателе по идентификатору vacancy_id
- Файловый кеш ответов: повторный запрос того же id отдаётся из FileTreeStore (TTL 1 ч), hh.ru повторно не читается; кеш отключается флагом `HH_MCP_CACHE=0`, каталог — `HH_MCP_CACHE_DIR` (по умолчанию `~/.cache/hh-mcp`; удалять только при остановленном сервере)
- Опциональная индексация страниц в Upstash Search (best-effort): успешные fetch-и вакансий/работодателей отправляются в индекс (env UPSTASH_SEARCH_REST_URL/TOKEN/INDEX), кеш-хиты не индексируются


## Состояние проекта
- **ПРОЕКТ ПОЛНОСТЬЮ РАБОТАЕТ**: MCP-сервер + интерактивные инструменты (FastMCP Apps); единственный вход — нативный пускатель `fastmcp run` из корня (см. «Команды»).
- `src/hh_mcp/app.py` — `FastMCP("hh-mcp")` с 3 инструментами: `vacancy(id)`, `company(id)`, `search(text, page=0)`. Каждый объявлен как `@mcp.tool(app=PrefabAppConfig(visibility=["app", "model"]))` и возвращает `ToolResult(content=…, structured_content=…)` — штатный механизм FastMCP Apps: модель получает текст, браузер рисует Prefab view. **Никаких самодельных `resourceUri`/`FastMCPApp`/`register_tool` — только документированный API.** `search` парсит HTML серпа hh.ru; за пределами выдачи (page > N) — пустой список.
- `server.py` (корень) — entry point пускателя: добавляет `ResponseCachingMiddleware` с `FileTreeStore` (файловый кеш, без Redis; каталог `~/.cache/hh-mcp`, env `HH_MCP_CACHE_DIR`; `HH_MCP_CACHE=0` — middleware не подключается, каталог не создаётся) к серверу из `hh_mcp.app.mcp`, объект `mcp` (entrypoint из `fastmcp.json`).
- `fastmcp.json` (корень) — конфиг нативного запуска (source: `server.py` → `mcp`; deployment: transport `http`, `/mcp`; environment: `uv` + `python: 3.14` + **`project: "."`**). Поле `project` обязательно для Prefect Horizon: он считает `fastmcp.json` авторитетным и без `project`/`dependencies`/`requirements` **не ставит ничего** (сборка падает с `fastmcp is not included in your dependencies`); правки `pyproject.toml` это не лечат. Horizon игнорирует `deployment.env` (значения — только через его environment variables) и не поддерживает `environment.editable`.
- `src/hh_mcp/fetch/` — SOLID/DIP fetch-пайплайн (10 модулей: guards, transport, html, links, converter, orchestrator, config, errors, enrich, __init__).
- `tests/` — 11 тестовых модулей, 377 тестов.
- Удалены: `src/hh_mcp/__main__.py` (CLI `hh-mcp`, `--dev`), `src/hh_mcp/devapp.py` (свой dev UI) — dev-режим теперь нативный (`fastmcp dev apps`).

## Стек
- Python ≥3.14 (CPython 3.14.4); uv 0.12.17 — единственный менеджер: в `.venv` нет `pip`; `uv.lock` — существует, обязателен к коммиту.
- Зависимости: `fastmcp 4.0.11` (4.x — НЕ 2.x/3.x), `httpx2[http2]` (Pydantic-форк; классического `httpx` в стеку нет), `markitdown`, `prefab-ui`, `upstash-search`. `playwright` и `pydantic` из прямых зависимостей убраны: первый кодом не используется (browser-fetch не реализован), второй приходит транзитивно через fastmcp.

## Команды
Запуск — **только через нативный пускатель fastmcp, из корня репозитория**:
- `uv run fastmcp run` — MCP-сервер по `fastmcp.json`: конфиг ищется **автоматически** в текущем каталоге, аргумент не указывать (transport `http`, `http://127.0.0.1:8000/mcp`). Работает: сервер поднимается, `/mcp` отвечает, все 3 инструмента видны клиенту.
- `uv run fastmcp dev apps fastmcp.json` — dev-режим: MCP-сервер + браузерный UI (Prefab/AppBridge, автооткрытие браузера; флаги `--mcp-port`, `--dev-port`, `--no-reload`). Нюанс: у **этой подкоманды** `SERVER-SPEC` обязателен (`fastmcp dev apps --help` → `[required]`) — в отличие от `fastmcp run`, конфиг здесь не авто-ищется.
- `uv run fastmcp run --transport stdio` — переопределение транспорта поверх конфига.
- **Удалено и не воссоздавать**: console-script `hh-mcp` (`[project.scripts]`), `python -m hh_mcp`, `hh-mcp --dev` (свой dev UI в одном процессе).
- `uv run pytest tests/ -v` — 377 passed; none `::test_name` — полный прогон.
- `uv add <pkg>` — единственная установка (уходит в `pyproject.toml`); ruff/mypy молча не подключать.

## Безопасность (SSRF) — указание
- `UrlGuard` должен работать по **allowlist хостов: разрешены только `hh.ru` и его поддомены** (напр. `kolomna.hh.ru`). Всё остальное — IP-литералы (`127.0.0.1`, `[::1]`, `169.254.169.254`, десятичные формы), `localhost`/`.local`, приватные и внутренние адреса, любые посторонние домены — отклонять (`SSRError`).
- Allowlist обязан действовать **на каждый hop редиректа**: guard только на входе недостаточно (302 с публичного хоста на localhost сейчас его обходит).
- Обязательная проверка: `https://localhost/test` должен падать (через `fetch_as_markdown` или `UrlGuard` прямой вызов).

## Структура / Стиль
- `src/hh_mcp/`; импорт-имя пакета — `hh_mcp` (underscore; дефис невозможен).
- Код под 3.14: `X | None` (PEP 604), PEP 695 type-params ok; linter не настроен — de-facto стандарт = `fetch.py`: double quotes, numpydoc-доки (EN), `# ---`-разделы, `__all__`, SCREAMING_SNAKE-константы, underscores в числах (`120_000`).

## Среда
- FastMCP API: канонический источник — `code-indexer` (MCP-сервер `cix`) → `github.com/PrefectHQ/fastmcp@main` (main = 4.x; онлайн-доки 2.x-эпохи устарели).
- PyCharm: SDK проекта = `.venv` — интерпретатор не менять (при несовпадении — сброс SDK, а не новый venv); `.venv` gitignored (`.gitignore` в корне отсутствует).

## Test cases
Ожидаем чистый markdown с полезной информацией, без внутренних ссылок, внешние ссылки сохраняются:
- https://hh.ru/vacancy/138156968
- https://hh.ru/employer/11620617
- https://hh.ru/vacancy/137911901
- https://hh.ru/employer/2163044