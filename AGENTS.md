# AGENTS.md

This file provides guidance to agents when working with code in this repository.
Фиксируй изменения в git commits.
Создавай прослеживаемую последовательность изменений.
Сделай коммит, когда закончил работу над задачей.

## Сервис предоставляет следующие возможности. 
- Получение данных о работодателе. 
- Получение данных о вакансии. 
  - Данные о вакансии должны включать раздел с данными о работодателе. Так, чтобы их можно было отделить по какому-то разделителю. 


## Состояние проекта
- **ПРОЕКТ ПОЛНОСТЬЮ РАБОТАЕТ**: MCP-сервер + dev UI в одном процессе, 230 тестов green.
- `src/hh_mcp/app.py` — `FastMCPApp("hh-mcp")` с 4 инструментами (2 model, 2 UI).
- `src/hh_mcp/__main__.py` — CLI (argparse, `[project.scripts]` → `hh-mcp`).
- `src/hh_mcp/devapp.py` — dev-веб-приложение (Starlette) с REST API `/api/status`, `/api/mcp`, `POST /api/mcp/call`.
- `src/hh_mcp/fetch/` — SOLID/DIP fetch-пайплайн (9 модулей: guards, transport, html, links, converter, orchestrator, config, errors, __init__).
- `tests/` — 10 тестовых модулей, 230 тестов.

## Стек
- Python ≥3.14 (CPython 3.14.4); uv 0.12.17 — единственный менеджер: в `.venv` нет `pip`; `uv.lock` — существует, обязателен к коммиту.
- Зависимости: `fastmcp 4.0.11` (4.x — НЕ 2.x/3.x), `httpx2[http2]` (Pydantic-форк; классического `httpx` в стеку нет), `markitdown`, `playwright` (импортируется нигде — зарезервирован под browser-fetch).

## Команды
- `uv run python -m hh_mcp` / `hh-mcp` — **работает**: запуск MCP-сервера (stdio).
- `hh-mcp --dev --mcp-port 8000 --dev-port 8080 --host 127.0.0.1` — единый dev-процесс (MCP + веб-UI).
- `hh-mcp --transport http --host 127.0.0.1 --port 8000` — только MCP (streamable HTTP).
- `uv run pytest tests/ -v` — 230 passed; none `::test_name` — полный прогон.
- `uv add <pkg>` — единственная установка (уходит в `pyproject.toml`); ruff/mypy молча не подключать.
- SSRF-проверка: `https://localhost/test` должен падать (через `fetch_as_markdown` или `UrlGuard` прямой вызов).

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