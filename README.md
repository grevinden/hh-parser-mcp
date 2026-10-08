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

Запуск — нативный пускатель fastmcp из корня (`uv run fastmcp run` —
MCP-сервер; `uv run fastmcp dev apps fastmcp.json` — MCP + браузерный UI-превью).

> Полное описание стека и конвенций — [`AGENTS.md`](AGENTS.md).

---

## Возможности

- **6 инструментов MCP** — 3 model-видимых (`get_vacancy`, `get_employer`,
  `search_vacancies`) и 3 UI-entry (`vacancy_app`, `employer_app`, `search_app`)
  на FastMCPApp. `search_app` показывает результат поиска в панели.
- **Fetch-пайплайн SOLID/DIP** — SSRF-защита, HTTP/2-транспорт (httpx2),
  HTML-санитайзер с NoisePolicy, разрешение ссылок, конвертация в Markdown
  (markitdown). Иерархия исключений — [`errors.py`](src/hh_mcp/fetch/errors.py).
- **Запуск — нативный пускатель fastmcp** (`uv run fastmcp run` / `uv run
  fastmcp dev apps fastmcp.json`) из корня репозитория; транспорты stdio/http/sse.
- **Dev UI** — браузерное превью UI-инструментов (`fastmcp dev apps`).
- **Файловый кеш ответов** — `ResponseCachingMiddleware` + `FileTreeStore`
  (без Redis) в [`server.py`](server.py): повторный вызов `get_vacancy` /
  `get_employer` с тем же id отдаётся из кеша и **не читает hh.ru повторно**
  (TTL 1 час; каталог `~/.cache/hh-mcp`, переопределяется `HH_MCP_CACHE_DIR`).
- **347 тестов** — `uv run pytest tests/ -v` (app, fetch-модуль, guards, html,
  links, converter, orchestrator, transport, config, errors, enrich, caching).

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
  `playwright`).

> **Важно**: `pip install` не используется. Добавление зависимостей — только
> через `uv add <pkg>`. Консольного скрипта `hh-mcp` нет и не создавать —
> запуск только через `uv run fastmcp …`.

---

## Запуск

Запуск — **только через нативный пускатель fastmcp из корня репозитория**
(конфиг `fastmcp.json` ищется автоматически в текущем каталоге).

### 1. MCP-сервер (HTTP)

```bash
uv run fastmcp run
```

MCP-эндпоинт: `http://127.0.0.1:8000/mcp` (streamable HTTP).
Переопределение транспорта: `uv run fastmcp run --transport stdio`.

### 2. Dev-режим (MCP + браузерный UI-превью)

```bash
uv run fastmcp dev apps fastmcp.json
```

Открываются два адреса:
- **Dev UI**: `http://127.0.0.1:8080/?token=…` — браузерное превью
  UI-инструментов (открывается автоматически; без токена — 403).
- **MCP endpoint**: `http://127.0.0.1:8000/mcp` — streamable HTTP для
  MCP-клиентов.

> У этой подкоманды `SERVER-SPEC` обязателен (`fastmcp dev apps --help` →
> `[required]`) — в отличие от `fastmcp run`, конфиг здесь не авто-ищется.

### 3. STDIO (для MCP-клиентов)

```bash
uv run fastmcp run --transport stdio
```

Используется для интеграции с MCP-клиентами, поддерживающими stdio-транспорт
(например, Claude Desktop). Пример конфигурации `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hh-mcp": {
      "command": "/path/to/hh-mcp/.venv/bin/uv",
      "args": ["run", "fastmcp", "run", "--transport", "stdio"]
    }
  }
}
```

### Флаги запуска (`fastmcp run`)

| Флаг | По умолчанию | Описание |
|------|-------------|----------|
| `--transport` | из `fastmcp.json` (`http`) | Транспорт (`stdio`, `http`, `sse`, `streamable-http`) |
| `--host` | `127.0.0.1` | Адрес привязки HTTP-сервера |
| `--port` | `8000` | Порт MCP-сервера |
| `--path` | `/mcp` | Путь эндпоинта |

Dev-режим — отдельная подкоманда `fastmcp dev apps fastmcp.json`
(флаги `--mcp-port`, `--dev-port`, `--no-reload`).

---

## Dev UI

Dev-режим — нативный (`uv run fastmcp dev apps fastmcp.json`): MCP-сервер
на порту 8000 (`/mcp`) + браузерный UI превью на порту 8080 (токен-URL,
открывается автоматически). Это интерфейс **для отладки** UI-инструментов
(`vacancy_app` / `employer_app`); в нём же видна панель операций сервера
(все вызовы `tools/call` с аргументами и JSON-ответами).

Прежний собственный dev-UI (`src/hh_mcp/devapp.py`, Starlette, страница
`GET /` и REST `/api/*`) **удалён** — см. коммит `a30bcb9`.

### Вызов инструментов без MCP-клиента (CLI-мост)

REST-интерфейс `/api/*` существовал у `src/hh_mcp/devapp.py` и **удалён**
вместе с ним (коммит `a30bcb9`, dev-режим стал нативным `fastmcp dev apps`).
Сейчас у сервера нет REST API; единственная HTTP-точка — MCP JSON-RPC
на `/mcp`.

Стандартный способ вызвать инструменты из шелла, скрипта или агента без
MCP-клиента — клиентские команды fastmcp (`fastmcp list`, `fastmcp call`):

```bash
# Список инструментов
uv run fastmcp list http://127.0.0.1:8000/mcp

# Вызов get_vacancy (типы коэрсятся по схеме автоматически)
uv run fastmcp call http://127.0.0.1:8000/mcp get_vacancy id=138156968

# Вызов get_employer, JSON-вывод (content + structuredContent)
uv run fastmcp call http://127.0.0.1:8000/mcp get_employer id=11620617 --json
```

Более низкоуровневый вариант — прямой JSON-RPC запрос к `/mcp`
(streamable HTTP, требуется рукопожатие initialize → `Mcp-Session-Id`).
Направление «MCP → REST» из документации FastMCP реализуется только
обёрткой в FastAPI (`FastMCP.from_fastapi` / `mcp.http_app`), см. gofastmcp.com
/ integrations / fastapi.

---

## Инструменты MCP

| Имя | Видимость | Параметры | Описание |
|-----|-----------|-----------|----------|
| `get_vacancy` | model (`@app.tool(model=True)`) | `id: int` (строго положительный) | HTML вакансии hh.ru → Markdown. Timeout 30 с, макс. 120 000 символов |
| `get_employer` | model (`@app.tool(model=True)`) | `id: int` (строго положительный) | HTML страницы работодателя hh.ru → Markdown |
| `search_vacancies` | model (`@app.tool(model=True)`) | `text: str`, `page: int = 0` | Поиск вакансий на hh.ru → плоский список ID (`list[int]`). Пагинация: `page`; за пределами выдачи — пустой список |
| `vacancy_app` | UI (`@app.ui()`) | — (запрашивает ID через Prefab Input) | UI-компонент: Column с полем ID и кнопкой CallTool |
| `employer_app` | UI (`@app.ui()`) | — | Аналогично для работодателя |
| `search_app` | UI (`@app.ui()`) | — (запрашивает запрос и страницу) | Панель поиска: поля запроса/страницы, кнопка и блок с найденными ID |

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

> Второй вызов `get_vacancy` с тем же id возвращается из файлового кеша
> (см. [Кеширование ответов](#кеширование-ответов)).

---

## Кеширование ответов

Чтобы одна и та же запись (вакансия / работодатель) не читалась с hh.ru
повторно, в [`server.py`](server.py) подключён штатный
`ResponseCachingMiddleware` с файловым хранилищем `FileTreeStore`
(`py-key-value-aio`, уже установлен через `fastmcp[apps]` — Redis не нужен):

- **Кешируются** только успешные ответы `get_vacancy` / `get_employer`
  (`CACHED_TOOLS` в `server.py`); ошибки и остальные инструменты не кешируются.
- **Ключ кеша** — `авторизация : версия : имя инструмента : аргументы`:
  вызов `get_vacancy {"id": 138156968}` всегда даёт один и тот же ключ.
- **TTL** — 1 час (`CACHE_TTL_S`); по истечении следующий вызов снова
  уходит на hh.ru.
- **Каталог кеша** — `~/.cache/hh-mcp` по умолчанию; переопределяется
  переменной окружения `HH_MCP_CACHE_DIR`. Кеш переживает рестарт сервера
  (файлы на диске).

```bash
# Пример: другой каталог кеша
HH_MCP_CACHE_DIR=/var/cache/hh-mcp uv run fastmcp run
```

---

## Тесты

```bash
# Запуск всех тестов
uv run pytest tests/ -v
```

**347 тестов**, все passed. Покрытие:
- `test_mcp_app.py` — инструменты, валидация, error mapping, UI-entry;
- `test_caching.py` — файловый кеш: повторный id не дёргает fetch;
- `test_enrich.py` — обогащение employer-карточки;
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
│  ├── app.py              — FastMCPApp + 4 инструмента   │
│  └── fetch/              — fetch-пайплайн (SOLID)        │
│      ├── __init__.py     — публичное API                 │
│      ├── config.py       — RequestConfig / NoisePolicy   │
│      ├── errors.py       — иерархия исключений           │
│      ├── guards.py       — SSRF-защита (UrlGuard)        │
│      ├── transport.py    — HTTP-транспорт (httpx2, HTTP2)│
│      ├── html.py         — HTML-санитайзер               │
│      ├── converter.py    — HTML → Markdown (markitdown)  │
│      ├── links.py        — разрешение относительных ссылок│
│      ├── enrich.py       — обогащение employer-карточки  │
│      └── orchestrator.py — FetchService + fetch_as_markdown│
├── server.py              — entry point пускателя (fastmcp)│
├── fastmcp.json           — конфиг нативного запуска      │
├── docs/                  — проектные документы           │
│   ├── apps_mode.md       — режим приложений (рус.)       │
│   ├── plan_mcp_app.md    — архитектурный план (рус.)     │
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

### Dev-режим (нативный `fastmcp dev apps fastmcp.json`)

Один процесс пускателя поднимает два слушателя:

```
MCP-сервер (uvicorn, порт 8000, путь /mcp)
     ↑
  fastmcp dev apps fastmcp.json
     ↓
Dev-UI / браузерное превью (порт 8080, токен-URL) → MCP через app bridge
```

---

## Troubleshooting

### `fastmcp dev apps` не видит сервер

`fastmcp dev apps` требует явный `SERVER-SPEC` (в отличие от `fastmcp run`,
который сам ищет `fastmcp.json` в текущем каталоге). Правильный вызов:

```bash
uv run fastmcp dev apps fastmcp.json
```

`fastmcp dev apps .` падает — спецификацией должен быть файл, а не каталог.

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
- [`server.py`](server.py) — entry point нативного пускателя