# hh-mcp

[![Python ≥3.14](https://img.shields.io/badge/python-3.14%2B-blue)](https://www.python.org/)
[![FastMCP 4.x](https://img.shields.io/badge/FastMCP-4.x-purple)](https://github.com/PrefectHQ/fastmcp)
[![uv](https://img.shields.io/badge/uv-0.12.x-green)](https://docs.astral.sh/uv/)
**hh-mcp** — MCP-сервер (Model Context Protocol) для получения страниц с hh.ru
в формате Markdown. Четыре текстовых инструмента — [`vacancy`](src/hh_mcp/app.py),
[`company`](src/hh_mcp/app.py), [`search`](src/hh_mcp/app.py) и
[`version`](src/hh_mcp/app.py).

Каждый инструмент возвращает `ToolResult` **только** с `content`: ответ несёт
данные ровно один раз. Браузерный Apps UI отключён намеренно — встроенный в
ответ Prefab-view дублировал бы каждую страницу, и клиент, обходящий 20 ID,
получал бы 40 страниц вместо 20 (см. [`docs/apps_mode.md`](docs/apps_mode.md)).

Запуск — нативный пускатель fastmcp из корня (`uv run fastmcp run` —
MCP-сервер; `uv run fastmcp dev apps fastmcp.json` — MCP + браузерный UI-превью).

> Полное описание стека и конвенций — [`AGENTS.md`](AGENTS.md).

---

## Возможности

- **4 текстовых инструмента MCP** — `vacancy`, `company`, `search`, `version`.
  Никакого UI в ответе: данные уходят ровно один раз (проверено на живом
  сервере — 1.04× к длине текста, `structuredContent` отсутствует).
- **`version` + `serverInfo.version`** — сборка видна в handshake (стандартное
  поле MCP) и отдельной тулзой, поэтому после деплоя сразу понятно, какой
  коммит разлился. Номер версии поднимается с каждым коммитом
  (`0.2.0` в [`pyproject.toml`](pyproject.toml)).
- **Fetch-пайплайн SOLID/DIP** — SSRF-защита, HTTP/2-транспорт (httpx2),
  HTML-санитайзер с NoisePolicy, разрешение ссылок, конвертация в Markdown
  (markitdown). Иерархия исключений — [`errors.py`](src/hh_mcp/fetch/errors.py).
- **Запуск — нативный пускатель fastmcp** (`uv run fastmcp run` / `uv run
  fastmcp dev apps fastmcp.json`) из корня репозитория; транспорты stdio/http/sse.
- **Никаких зависимостей на UI** — `prefab-ui` и экстра `fastmcp[apps]`
  удалены, в коде нет ни одного импорта `prefab_ui`.
- **Файловый кеш ответов** — `ResponseCachingMiddleware` + `FileTreeStore`
  (без Redis) в [`server.py`](server.py): повторный вызов `vacancy` /
  `company` с тем же id отдаётся из кеша и **не читает hh.ru повторно**
  (TTL 1 час; каталог `~/.cache/hh-mcp`, переопределяется `HH_MCP_CACHE_DIR`;
  отключается флагом `HH_MCP_CACHE=0`).
- **429 тестов** — `uv run pytest tests/ -v` (app, версия, конфиг деплоя,
  семантический индекс, fetch-модуль, guards, html, links, converter,
  orchestrator, transport, config, errors, enrich, caching).

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
- все зависимости (`fastmcp`, `httpx2[http2]`, `markitdown`,
  `upstash-search`).

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

### 2. Dev-режим (MCP + браузерное превью)

```bash
uv run fastmcp dev apps fastmcp.json
```

Открываются два адреса:
- **Dev UI**: `http://127.0.0.1:8080/?token=…` — браузерное превью
  (открывается автоматически; без токена — 403). Инструменты текстовые, без
  UI-view, поэтому пикер показывает только формы ввода из JSON-схем.
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
открывается автоматически). Это интерфейс **для отладки**: пикер показывает
все четыре инструмента (`vacancy`, `company`, `search`, `version`) и строит
форму ввода из их JSON-схем; в нём же видна панель операций сервера (все вызовы
`tools/call` с аргументами и JSON-ответами). Страницу вакансии интерфейс не
рисует — UI-view в ответе намеренно нет, см. «Инструменты MCP».

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

# Вызов vacancy (типы коэрсятся по схеме автоматически)
uv run fastmcp call http://127.0.0.1:8000/mcp vacancy id=138156968

# Вызов company, JSON-вывод (content + structuredContent)
uv run fastmcp call http://127.0.0.1:8000/mcp company id=11620617 --json
```

Более низкоуровневый вариант — прямой JSON-RPC запрос к `/mcp`
(streamable HTTP, требуется рукопожатие initialize → `Mcp-Session-Id`).
Направление «MCP → REST» из документации FastMCP реализуется только
обёрткой в FastAPI (`FastMCP.from_fastapi` / `mcp.http_app`), см. gofastmcp.com
/ integrations / fastapi.

---

## Инструменты MCP

Все инструменты объявлены как `@mcp.tool` и возвращают `ToolResult` только с
`content`. Два правила, из-за которых это важно:

- возврат `-> str` заставил бы fastmcp продублировать текст в
  `structuredContent.result` (wrap-result) — данные ушли бы в контекст дважды;
- Prefab-view в `structured_content` — третья копия тех же данных.

Замер на живом сервере (`tools/call` по JSON-RPC): длина ответа ÷ длина текста —
**1.04×** для `vacancy` и `company`, 1.24× для `search` (это JSON-обёртка),
`structuredContent` отсутствует.

| Имя | Параметры | Модель получает (`content`) |
|-----|-----------|----------------------------|
| `vacancy` | `id: int` (строго положительный) | Markdown страницы вакансии hh.ru (timeout 30 с, макс. 120 000 символов) |
| `company` | `id: int` (строго положительный) | Markdown страницы компании hh.ru |
| `search` | `text: str`, `page: int = 0` | «Найдено N вакансий (страница P): …» — список ID |
| `version` | — | JSON одной строкой: `version`, `commit`, `build`, `python`, `fastmcp` |

**Версия сборки**: `FastMCP("hh-mcp", version=BUILD_ID)` публикует значение в
стандартном поле `serverInfo.version` ответа `initialize` — его читает любой
MCP-клиент. Тулза `version` даёт то же плюс детали. Версия живёт в
`[project].version` (`pyproject.toml`) и поднимается с каждым коммитом; локально
`BUILD_ID` выглядит как `0.2.0+113e522` (версия + короткий коммит), на деплое —
просто `0.2.0`, потому что `.git` в артефакте нет.

**Валидация**: `id <= 0` → `ToolError("Invalid ID: …")` до HTTP-запроса.
**Ошибки fetch** маппятся в `ToolError` (см. `_tool_error()` в
[`app.py`](src/hh_mcp/app.py)).

**Закрытые вакансии** не 404: hh.ru редиректит на региональный лендинг
(`kolomna.hh.ru/vrsurvey/...`), и после санитайзера остаётся один заголовок
`# HeadHunter`. Такой ответ (тело < `MIN_CONTENT_CHARS` = 200 символов)
отвергается с `ToolError("hh.ru returned no vacancy content … closed or
archived vacancy redirects to a landing page")` — лучше явная ошибка, чем
«вакансия из 12 символов».

---

## Подключение MCP-клиента

В режимах HTTP и dev MCP-сервер доступен по адресу:

```
http://127.0.0.1:8000/mcp
```

Транспорт — **Streamable HTTP** (JSON-RPC over HTTP, одна сессия, метод POST).
Поддерживается любым MCP-клиентом, реализующим спецификацию streamable HTTP
(protocol version `2026-07-28`).

> Второй вызов `vacancy` с тем же id возвращается из файлового кеша
> (см. [Кеширование ответов](#кеширование-ответов)).

---

## Кеширование ответов

Чтобы одна и та же запись (вакансия / работодатель) не читалась с hh.ru
повторно, в [`server.py`](server.py) подключён штатный
`ResponseCachingMiddleware` с файловым хранилищем `FileTreeStore`
(`py-key-value-aio`, уже в зависимостях fastmcp — Redis не нужен):

- **Кешируются** только успешные ответы `vacancy` / `company` (`search`
  исключён: выдача меняется от страницы к странице)
  (`CACHED_TOOLS` в `server.py`); ошибки и остальные инструменты не кешируются.
- **Ключ кеша** — `авторизация : версия : имя инструмента : аргументы`:
  вызов `vacancy {"id": 138156968}` всегда даёт один и тот же ключ.
- **TTL** — 1 час (`CACHE_TTL_S`); по истечении следующий вызов снова
  уходит на hh.ru.
- **Каталог кеша** — `~/.cache/hh-mcp` по умолчанию; переопределяется
  переменной окружения `HH_MCP_CACHE_DIR`. Кеш переживает рестарт сервера
  (файлы на диске).
- **Отключение** — `HH_MCP_CACHE=0` (также `off` / `false` / `no`): middleware
  не подключается вовсе, каталог кеша не создаётся и каждый вызов идёт на
  hh.ru. Полезно при отладке, когда нужен свежий ответ.

```bash
# Пример: другой каталог кеша
HH_MCP_CACHE_DIR=/var/cache/hh-mcp uv run fastmcp run

# Пример: без кеша (каждый вызов читает hh.ru)
HH_MCP_CACHE=0 uv run fastmcp run
```

> Каталог кеша удаляйте **только при остановленном сервере**: живой
> `FileTreeStore` держит открытые дескрипторы и без каталога падает с
> `FileNotFoundError`.

---

## Семантический индекс (Upstash Search)

Каждый успешный fetch вакансии или работодателя (best-effort, ошибки
индексации никогда не видны в ответе) кладёт страницу в Upstash Search.
Документ намеренно минимальный — столько полей, сколько нужно для поиска «по
номеру или по смыслу»:

```json
{
  "id": "vacancy/38185674",
  "content": {"text": "# Ведущий программист 1С\n\nОпыт с 1С, удалённо."},
  "metadata": {"fetched_at": "2026-10-08T16:20:31.482130+00:00"}
}
```

- **id** — путь страницы, поэтому документ находится по номеру, работодатель
  не collide-ится с вакансией того же номера, а URL восстанавливается как
  `https://hh.ru/{id}`;
- **content** — одно поле `text`: Upstash эмбедит все поля content, то есть
  это и есть семантический индекс;
- **metadata** — только время чтения страницы. `url`, `source` и `type` не
  хранятся: они выводятся из id, а дубликат рано или поздно с ним разойдётся.

Настройка — переменные окружения `UPSTASH_SEARCH_REST_URL`,
`UPSTASH_SEARCH_REST_TOKEN`, `UPSTASH_SEARCH_INDEX` (по умолчанию `hh_mcp`).
Кеш-хиты не индексируются: запись идёт только после реального чтения hh.ru.

> Тесты никогда не пишут в живой индекс: `tests/conftest.py` подменяет вызов
> на копилку и убирает `UPSTASH_SEARCH_*` из окружения.

---

## Развёртывание на Prefect Horizon

Horizon читает [`fastmcp.json`](fastmcp.json) и считает его **авторитетным**:
он управляет установкой зависимостей и версией Python, а к `pyproject.toml`
за пределами конфига **не возвращается**.

> A configuration selects the whole environment… If the configuration declares
> no dependencies, Horizon installs none, so list everything your server
> imports, including `fastmcp`.
> — [Build system](https://docs.horizon.prefect.io/platform/build-system)

Поэтому в `environment` обязателен `project`:

```json
{
  "environment": {
    "type": "uv",
    "python": "3.14",
    "project": "."
  }
}
```

| Поле `environment` | Эффект в Horizon |
|--------------------|------------------|
| `project` | Ставит каталог как проект, используя лежащий рядом `uv.lock` (frozen `uv sync`) — вместе с пакетом `hh_mcp` и всеми его зависимостями |
| `dependencies` | Ставит перечисленные пакеты (PEP 508) |
| `requirements` | Ставит указанный requirements-файл |
| `python` | Запрашивает версию Python; должна удовлетворять выбранному проекту |

**Без `project` сборка падает** на шаге проверки зависимостей:
`fastmcp is not included in your dependencies` — Horizon ничего не ставит и не
находит `fastmcp`. Правка `pyproject.toml` (в т.ч. добавление `fastmcp` в
`dependencies`) эту ошибку **не устраняет**: при наличии `fastmcp.json`
файлы репозитория не сканируются.

Что Horizon **не** поддерживает:

- `deployment.env` игнорируется — значения (`HH_MCP_CACHE`, `HH_MCP_CACHE_DIR`,
  `UPSTASH_SEARCH_REST_URL/TOKEN/INDEX`) задаются как **environment variables**
  сервера в Horizon;
- `environment.editable` не поддерживается — пакеты перечисляются в
  `environment.dependencies`;
- если в настройках сервера указан **dependency file**, он имеет приоритет над
  `fastmcp.json` (тогда `project` игнорируется).

Сборка: таймаут 15 минут; зависимости устанавливаются frozen-синком из
`uv.lock`, поэтому лишних пакетов (например, `playwright`) в образ не попадает.

---

## Тесты

```bash
# Запуск всех тестов
uv run pytest tests/ -v
```

**429 тестов**, все passed. Покрытие:
- `test_mcp_app.py` — инструменты, валидация, error mapping, контракт «одна
  копия данных в ответе», отсутствие UI-meta;
- `test_version.py` — версия из метаданных пакета, коммит, `BUILD_ID`,
  `runtime_info`;
- `test_fastmcp_json.py` — конфиг деплоя: транспорт, `log_level` не `DEBUG`,
  `environment.project`, entrypoint;
- `test_search_index.py` — форма документа в Upstash Search на фейковом
  клиенте (id = путь страницы, content = `text`, metadata = `fetched_at`);
- `test_indexing_guard.py` — индексация только при реальном fetch; тесты не
  пишут в живой индекс (`tests/conftest.py` подменяет вызов и чистит
  `UPSTASH_SEARCH_*` из окружения);
- `test_caching.py` — файловый кеш: повторный id не дёргает fetch; флаг
  `HH_MCP_CACHE=0`;
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
│  ├── app.py              — FastMCP + 3 инструмента (Tools)  │
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
MCP Client / LLM → FastMCP (streamable HTTP / stdio)
     ↓
Tool fn (vacancy / company / search / version)  → ToolResult{content}
     ↓
fetch_as_markdown(url, timeout=30, max_chars=120_000)
     ↓
guards.py (SSRF) → transport.py (httpx2, HTTP2) → html.py (Sanitizer + NoisePolicy)
     ↓
links.py (resolve_relative_links) → converter.py (MarkItDown)
     ↓
ToolResult{content: данные ровно один раз, без UI-копии}
     ↓
MCP Client (1.04× к длине текста)
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

Если hh.ru начинает блокировать HTTP-запросы (403 Forbidden), выход —
browser-fetch в режиме Headless Chrome: потребуется вернуть `playwright`
в зависимости и подключить его в fetch-пайплайне. Сейчас он не используется,
поэтому и не зависит.

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