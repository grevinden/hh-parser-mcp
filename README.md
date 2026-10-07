# hh-mcp

[![Python ≥3.14](https://img.shields.io/badge/python-3.14%2B-blue)](https://www.python.org/)
[![FastMCP 4.x](https://img.shields.io/badge/FastMCP-4.x-purple)](https://github.com/PrefectHQ/fastmcp)
[![uv](https://img.shields.io/badge/uv-0.12.x-green)](https://docs.astral.sh/uv/)
[![prefab‑ui](https://img.shields.io/badge/prefab--ui-0.20%2B-orange)](https://github.com/PrefectHQ/prefab-ui)

**hh-mcp** — MCP-сервер (Model Context Protocol) для получения страниц с hh.ru
в формате Markdown. Предоставляет два backend-инструмента
([`get_vacancy`](src/hh_mcp/app.py:116), [`get_employer`](src/hh_mcp/app.py:141))
для LLM-агентов и два UI-входных инструмента
([`vacancy_app`](src/hh_mcp/app.py:168), [`employer_app`](src/hh_mcp/app.py:200))
на базе Prefab (генеративный UI).

Проект включает **dev-веб-приложение** (единый процесс: MCP-сервер + Starlette
UI) — запуск одной командой, без внешних зависимостей для фронтенда.

> Полное описание стека и конвенций — [`AGENTS.md`](AGENTS.md).

---

## Возможности

- **4 инструмента MCP** — 2 model-видимых (`get_vacancy`, `get_employer`) и 2
  UI-entry (`vacancy_app`, `employer_app`) на FastMCPApp.
- **Fetch-пайплайн SOLID/DIP** — SSRF-защита, HTTP/2-транспорт (httpx2),
  HTML-санитайзер с NoisePolicy, разрешение ссылок, конвертация в Markdown
  (markitdown). Иерархия исключений — [`errors.py`](src/hh_mcp/fetch/errors.py).
- **Три режима запуска** — stdio (для MCP-клиентов), HTTP (только MCP-сервер),
  единый dev (MCP + веб-UI в одном процессе).
- **Dev UI** — самодостаточная HTML-страница (без CDN) с отображением статуса,
  списка инструментов, формы вызова и JSON-ответов.
- **230 тестов** — `uv run pytest tests/ -v` (app, devapp, fetch-модуль,
  guards, html, links, converter, orchestrator, transport, config, errors).

---

## Тестируемые страницы

При вызове инструментов ожидается чистый Markdown с полезной информацией:

| URL | Тип |
|-----|-----|
| `https://hh.ru/vacancy/138156968` | Вакансия |
| `https://hh.ru/employer/11620617` | Работодатель |
| `https://hh.ru/vacancy/137911901` | Вакансия |
| `https://hh.ru/employer/2163044` | Работодатель |

---

## Требования

- **Python ≥3.14** (CPython 3.14.4)
- **uv ≥0.12.x** — единственный менеджер пакетов (в `.venv` нет `pip`);
  `uv.lock` обязателен к коммиту
- **ОС**: Linux (основная), macOS (совместимость, не тестировалась)

---

## Установка

```bash
git clone <repo-url> /path/to/hh-mcp
cd /path/to/hh-mcp

# Установка зависимостей в .venv
uv sync
```

После `uv sync` становятся доступны:
- все зависимости (`fastmcp[apps]`, `httpx2[http2]`, `markitdown`, `prefab-ui`,
  `playwright`);
- консольный скрипт `hh-mcp` (см. `[project.scripts]` в
  [`pyproject.toml`](pyproject.toml:14)).

> **Важно**: `pip install` не используется. Добавление зависимостей — только
> через `uv add <pkg>`.

---

## Запуск

### 1. Единый dev-режим (MCP-сервер + веб-UI)

```bash
# Через uv run
uv run python -m hh_mcp --dev --mcp-port 8000 --dev-port 8080 --host 127.0.0.1

# Или через консольный скрипт
hh-mcp --dev --mcp-port 8000 --dev-port 8080 --host 127.0.0.1
```

Открываются два адреса:
- **Dev UI**: [`http://127.0.0.1:8080`](http://127.0.0.1:8080) — самодостаточная
  HTML-страница с формой вызова инструментов.
- **MCP endpoint**: [`http://127.0.0.1:8000/mcp`](http://127.0.0.1:8000/mcp) —
  streamable HTTP для MCP-клиентов.

Остановка — `Ctrl+C` (SIGINT), оба сервера завершаются чисто, порты
освобождаются.

### 2. Только MCP-сервер (HTTP)

```bash
uv run python -m hh_mcp --transport http --host 127.0.0.1 --port 8000

# Или
hh-mcp --transport http --host 127.0.0.1 --port 8000
```

MCP-эндпоинт: `http://127.0.0.1:8000/mcp` (streamable HTTP).

### 3. STDIO (для MCP-клиентов)

```bash
uv run python -m hh_mcp
# Или
hh-mcp
```

Используется для интеграции с MCP-клиентами, поддерживающими stdio-транспорт
(например, Claude Desktop). Пример конфигурации `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hh-mcp": {
      "command": "/path/to/hh-mcp/.venv/bin/hh-mcp",
      "args": []
    }
  }
}
```

### CLI-флаги

| Флаг | По умолчанию | Описание |
|------|-------------|----------|
| `--transport` | `stdio` | Транспорт (`stdio`, `http`, `sse`, `streamable-http`) |
| `--host` | `127.0.0.1` | Адрес привязки HTTP-сервера |
| `--port` | `8000` | Порт MCP-сервера (HTTP / dev-режим) |
| `--dev` | — (флаг) | Включить dev-режим (MCP + веб-фронтенд) |
| `--mcp-port` | `8000` | Порт MCP-сервера в dev-режиме |
| `--dev-port` | `8080` | Порт веб-фронтенда в dev-режиме |

---

## Dev UI

Веб-приложение [`devapp.py`](src/hh_mcp/devapp.py) — Starlette ASGI,
самодостаточная HTML-страница (без CDN, без внешних скриптов).

**Страница `GET /`** отображает:
- статус подключения к MCP-серверу (connected/disconnected);
- версию протокола, имя сервера, количество инструментов;
- список tools / resources / prompts;
- форму вызова инструмента (поле name + JSON-редактор аргументов);
- ответ инструмента в текстовом виде;
- автообновление каждые 5 секунд.

### REST API

| Метод | Путь | Описание | Ответ |
|-------|------|----------|-------|
| `GET` | `/api/status` | Статус подключения к MCP | `{"connected": true, "mcp_url": "…", "server": "hh-mcp", "protocol_version": "2026-07-28", "tool_count": 4}` |
| `GET` | `/api/mcp` | Инструменты, ресурсы, промпты | `{"tools": [{…}], "resources": [{…}], "prompts": [{…}]}` |
| `POST` | `/api/mcp/call` | Вызов инструмента | `{"isError": bool, "content": […], "structuredContent": …}` |

> **Контракт POST /api/mcp/call**: JSON-тело содержит поле **`tool`** (строка,
> имя инструмента), **НЕ `name`**. Поле `arguments` — словарь параметров.

#### Примеры curl

```bash
# Статус
curl http://127.0.0.1:8080/api/status

# Список инструментов
curl http://127.0.0.1:8080/api/mcp

# Вызов get_vacancy
curl -X POST http://127.0.0.1:8080/api/mcp/call \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_vacancy","arguments":{"id":138156968}}'

# Вызов get_employer с невалидным ID (ожидается ошибка)
curl -X POST http://127.0.0.1:8080/api/mcp/call \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_employer","arguments":{"id":0}}'
```

**Проверено (live)**:
- `GET /api/status` → `{"connected": true, "mcp_url": "http://127.0.0.1:8000/mcp", "server": "hh-mcp", "protocol_version": "2026-07-28", "tool_count": 4}`
- `GET /api/mcp` → 4 инструмента + 2 prefab-ресурса.
- `POST /api/mcp/call` `{"tool": "get_employer", "arguments": {"id": 0}}` → `isError: true`, `content: [{"type":"text","text":"Invalid ID: 0"}]`
- `POST /api/mcp/call` `{"tool": "get_vacancy", "arguments": {"id": 138156968}}` → `isError: false`, Markdown «# Вакансия…»
- Прямой клиент → `http://127.0.0.1:8000/mcp`: initialize + list_tools OK.

---

## Инструменты MCP

| Имя | Видимость | Параметры | Описание |
|-----|-----------|-----------|----------|
| `get_vacancy` | model (`@app.tool(model=True)`) | `id: int` (строго положительный) | HTML вакансии hh.ru → Markdown. Timeout 30 с, макс. 120 000 символов |
| `get_employer` | model (`@app.tool(model=True)`) | `id: int` (строго положительный) | HTML страницы работодателя hh.ru → Markdown |
| `vacancy_app` | UI (`@app.ui()`) | — (запрашивает ID через Prefab Input) | UI-компонент: Column с полем ID и кнопкой CallTool |
| `employer_app` | UI (`@app.ui()`) | — | Аналогично для работодателя |

**Валидация**: `id <= 0` → `ToolError("Invalid ID: …")` до HTTP-запроса.
**Ошибки fetch** маппятся в `ToolError` (см. `_tool_error()` в
[`app.py`](src/hh_mcp/app.py:54)).

---

## Подключение MCP-клиента

В режимах HTTP и dev MCP-сервер доступен по адресу:

```
http://127.0.0.1:8000/mcp
```

Транспорт — **Streamable HTTP** (JSON-RPC over HTTP, одна сессия, метод POST).
Поддерживается любым MCP-клиентом, реализующим спецификацию streamable HTTP
(protocol version `2026-07-28`).

---

## Тесты

```bash
# Запуск всех тестов
uv run pytest tests/ -v
```

**230 тестов**, все passed. Покрытие:
- `test_mcp_app.py` — инструменты, валидация, error mapping;
- `test_devapp.py` — API `/api/status`, `/api/mcp`, `/api/mcp/call`, FakeClient;
- `test_guards.py` — SSRF-защита (localhost, userinfo, схемы);
- `test_html.py` — санитайзер, NoisePolicy;
- `test_links.py` — разрешение относительных ссылок;
- `test_converter.py` — HTML → Markdown;
- `test_orchestrator.py` — fetch-пайплайн целиком;
- `test_transport.py` — HTTP-транспорт (httpx2);
- `test_config.py` — RequestConfig / NoisePolicy;
- `test_errors.py` — иерархия исключений.

---

## Архитектура

```
┌──────────────────────────────────────────────────────────┐
│                      hh-mcp                              │
│  src/hh_mcp/                                             │
│  ├── __init__.py         — версия пакета (0.1.0)         │
│  ├── __main__.py         — CLI entry point (argparse)    │
│  ├── app.py              — FastMCPApp + 4 инструмента   │
│  ├── devapp.py           — dev-веб-приложение (Starlette)│
│  └── fetch/              — fetch-пайплайн (SOLID)        │
│      ├── __init__.py     — публичное API                 │
│      ├── config.py       — RequestConfig / NoisePolicy   │
│      ├── errors.py       — иерархия исключений           │
│      ├── guards.py       — SSRF-защита (UrlGuard)        │
│      ├── transport.py    — HTTP-транспорт (httpx2, HTTP2)│
│      ├── html.py         — HTML-санитайзер               │
│      ├── converter.py    — HTML → Markdown (markitdown)  │
│      ├── links.py        — разрешение относительных ссылок│
│      └── orchestrator.py — FetchService + fetch_as_markdown│
├── docs/                  — проектные документы           │
│   ├── plan_mcp_app.md    — архитектурный план            │
│   └── fetch_redesign.md  — SOLID-спецификация fetch     │
├── pyproject.toml         — метаданные, зависимости       │
└── AGENTS.md              — конвенции для агентов         │
```

### Жизненный цикл запроса

```
MCP Client / LLM → FastMCP (streamable HTTP / stdio) → FastMCPApp
     ↓
Tool fn (get_vacancy / get_employer)
     ↓
fetch_as_markdown(url, timeout=30, max_chars=120_000)
     ↓
guards.py (SSRF) → transport.py (httpx2, HTTP2) → html.py (Sanitizer + NoisePolicy)
     ↓
links.py (resolve_relative_links) → converter.py (MarkItDown)
     ↓
ToolResult → MCP Client
```

### Dev-режим (два ASGI-приложения в одном процессе)

```
MCP-сервер (uvicorn, порт 8000, путь /mcp)
     ↑
  asyncio.gather
     ↓
Веб-фронтенд (uvicorn, порт 8080) ← HTTP-запросы к MCP через fastmcp.client.Client
```

Оба сервера запускаются через `uvicorn.Server._serve()` (минуя
`capture_signals()`) с единым набором SIGINT/SIGTERM-обработчиков.

---

## Troubleshooting

### `fastmcp dev apps src/hh_mcp/app.py` не работает

Встроенный CLI `fastmcp dev apps <file>` **не поддерживает** `FastMCPApp` на
fastmcp 4.0.11:
- автодетекция завершается ошибкой `ERROR No server object found` (детекция
  принимает только `FastMCP | SDKServer`);
- даже при успешной детекции: `Failed to run server: 'FastMCPApp' object has
  no attribute 'run_async'`.

**Решение**: используйте собственный `--dev`-режим проекта:
```bash
hh-mcp --dev --mcp-port 8000 --dev-port 8080 --host 127.0.0.1
```

### 403 / антибот от hh.ru

Если hh.ru начинает блокировать HTTP-запросы (403 Forbidden), проект
резервирует `playwright` для browser-fetch (режим Headless Chrome).
В текущей версии `playwright` импортируется, но не используется —
подключение будет добавлено в будущем.

### SSRF-защита

`UrlGuard` ([`guards.py`](src/hh_mcp/fetch/guards.py:31)) отклоняет URL:
- с схемой, отличной от `http`/`https`;
- с логином/паролем (userinfo);
- с hostname, указывающими на локальные адреса (`localhost`, зоны `.local`,
  `.localhost`).

```python
validate_url("https://localhost/test")    # → SSRError
validate_url("https://example.com:443")   # → OK
```

---

## Безопасность

| Механизм | Реализация |
|----------|-----------|
| **SSRF-guard** | [`UrlGuard`](src/hh_mcp/fetch/guards.py:31) — URL-валидация до HTTP-запроса |
| **TLS verify** | `RequestConfig(verify_tls=True)` — проверка сертификатов |
| **Max body** | 4 MiB — `RequestConfig(max_body_bytes=4_194_304)` |
| **NoisePolicy** | [`config.py`](src/hh_mcp/fetch/config.py:65) — удаление навигации, рекламы, скриптов |

---

## Разработка

```bash
# Установка зависимостей
uv sync

# Добавление новой зависимости
uv add <pkg>

# Запуск тестов
uv run pytest tests/ -v
```

Все изменения следуют конвенциям [`AGENTS.md`](AGENTS.md): double quotes,
numpydoc-доки на английском, `__all__`-экспорты, константы `SCREAMING_SNAKE_CASE`,
PEP 604 (`X | None`), PEP 695.

---

## Документация

- [`docs/plan_mcp_app.md`](docs/plan_mcp_app.md) — архитектурный план (рус.)
- [`docs/apps_mode.md`](docs/apps_mode.md) — режим приложений: интерактивные инструменты (рус.)
- [`docs/fetch_redesign.md`](docs/fetch_redesign.md) — SOLID-спецификация fetch (англ.)
- [`AGENTS.md`](AGENTS.md) — конвенции проекта для агентов
- [`src/hh_mcp/app.py`](src/hh_mcp/app.py) — главный модуль приложения
- [`src/hh_mcp/__main__.py`](src/hh_mcp/__main__.py) — CLI entry point
- [`src/hh_mcp/devapp.py`](src/hh_mcp/devapp.py) — dev-веб-приложение