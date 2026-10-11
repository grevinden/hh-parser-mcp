# hh-mcp

[![Python ≥3.14](https://img.shields.io/badge/python-3.14%2B-blue)](https://www.python.org/)
[![FastMCP 4.x](https://img.shields.io/badge/FastMCP-4.x-purple)](https://github.com/PrefectHQ/fastmcp)
[![uv](https://img.shields.io/badge/uv-0.12.x-green)](https://docs.astral.sh/uv/)
**hh-mcp** — MCP-сервер (Model Context Protocol) для получения страниц с hh.ru
в формате Markdown. Три текстовых инструмента — [`vacancy`](src/hh_mcp/app.py),
[`company`](src/hh_mcp/app.py) и [`search`](src/hh_mcp/app.py) — и два ресурса:
[`search-guide`](src/hh_mcp/search_guide.py) (как составлять поисковый запрос) и
[`version`](src/hh_mcp/app.py) (какая сборка запущена).

Инструменты объявлены через `@mcp.tool` и возвращают **естественный тип**: `str`
для `vacancy`/`company` (Markdown страницы) и `list[int]` для `search` (id одной
страницы). Конверт — `content` + `structuredContent.result` — строит fastmcp
(см. [`docs/apps_mode.md`](docs/apps_mode.md)).

Запуск — нативный пускатель fastmcp из корня (`uv run fastmcp run` —
MCP-сервер; `uv run fastmcp dev apps fastmcp.json` — MCP + браузерный UI-превью).

> Полное описание стека и конвенций — [`AGENTS.md`](AGENTS.md).

---

## Возможности

- **3 текстовых инструмента MCP** — `vacancy`, `company`, `search`.
  Никакого UI в ответе: каждая тулза возвращает свой тип, а fastmcp строит
  конверт `content` + `structuredContent.result`.
- **Справочник и метаданные — ресурсами, не тулзами** — `hh-mcp://search-guide`
  (операторы запроса hh.ru: `AND`, `OR`, `NOT`, кавычки, `~`, `*`, `NAME:`,
  `COMPANY_NAME:`, `DESCRIPTION:`) и `hh-mcp://version`. Тулза попадает в схему
  каждого запроса агента, и на бесполезную `version` он всё равно отвечал;
  ресурс читают только по запросу.
- **`serverInfo.version`** — сборка видна в handshake (стандартное поле MCP)
  даже без чтения ресурсов, поэтому после деплоя сразу понятно, какой коммит
  разлился. Номер версии поднимается с каждым коммитом
  (`0.4.0` в [`pyproject.toml`](pyproject.toml)).
- **Fetch-пайплайн SOLID/DIP** — SSRF-защита, HTTP/2-транспорт (httpx2),
  HTML-санитайзер с NoisePolicy, разрешение ссылок, конвертация в Markdown
  (markitdown). Выход после конвертации нормализуется: картинки удаляются, а
  неразрывные пробелы (`U+00A0`, `U+202F`, `U+2007`) сворачиваются в обычный.
  Иерархия исключений — [`errors.py`](src/hh_mcp/fetch/errors.py).
- **Запуск — нативный пускатель fastmcp** (`uv run fastmcp run` / `uv run
  fastmcp dev apps fastmcp.json`) из корня репозитория; транспорты stdio/http/sse.
- **Никаких зависимостей на UI** — в коде нет импортов UI-библиотек: ответ
  строит fastmcp из типа тулзы, Prefab-view не добавляется.
- **Файловый кеш ответов** — `ResponseCachingMiddleware` + `FileTreeStore`
  (без Redis) в [`cache/`](src/hh_mcp/cache/disk.py): повторный вызов `vacancy` /
  `company` с тем же id отдаётся из кеша и **не читает hh.ru повторно**
  (TTL 1 час; каталог `~/.cache/hh-mcp`, переопределяется `HH_MCP_CACHE_DIR`;
  отключается флагом `HH_MCP_CACHE=0`).
- **515 тестов** — `uv run pytest tests/ -q` (app, версия, конфиг деплоя,
  fetch-модуль, guards, html, links, converter, orchestrator, transport,
  config, errors, enrich, кеш).

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

После `uv sync` становятся доступны все зависимости (`fastmcp`,
`httpx2[http2]`, `markitdown`).

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
все три инструмента (`vacancy`, `company`, `search`) и строит
форму ввода из их JSON-схем; в нём же видна панель операций сервера (все вызовы
`tools/call` с аргументами и JSON-ответами). Страницу вакансии интерфейс не
рисует — UI-view в ответе намеренно нет, см. «Инструменты MCP».

### Вызов инструментов без MCP-клиента

Единственная HTTP-точка сервера — MCP JSON-RPC на `/mcp`. Вызвать инструменты
из шелла, скрипта или агента можно клиентскими командами fastmcp
(`fastmcp list`, `fastmcp call`):

```bash
# Список инструментов
uv run fastmcp list http://127.0.0.1:8000/mcp

# Вызов vacancy (типы коэрсятся по схеме автоматически)
uv run fastmcp call http://127.0.0.1:8000/mcp vacancy idn=138156968

# Вызов company, JSON-вывод (content + зеркало в structuredContent.result)
uv run fastmcp call http://127.0.0.1:8000/mcp company idn=11620617 --json
```

Более низкоуровневый вариант — прямой JSON-RPC запрос к `/mcp`
(streamable HTTP, требуется рукопожатие initialize → `Mcp-Session-Id`).

---

## Инструменты MCP

Все инструменты объявлены как `@mcp.tool` и возвращают естественный тип; конверт
строит fastmcp — значение попадает в `content` и зеркалится в
`structuredContent.result` (wrap-result). Для `search` (`list[int]`) зеркало
копеечное, для страниц (`str`) — удваивает ответ: замер на живом сервере даёт
**2.08×** для `vacancy` и **2.11×** для `company`. Это осознанная плата за единую
простую форму всех трёх тулз.

- собирать `ToolResult` руками не нужно — тип в сигнатуре уже описывает форму;
- UI-view (App/Prefab) в `structuredContent` дал бы третью копию, поэтому
  зависимостей на UI в проекте нет.

Аргументы валидирует схема (Pydantic): `PositiveInt`, `NonNegativeInt`,
`NonBlankStr`. Мусор отсекается на границе MCP, тело тулзы вызывается только с
валидными значениями.

| Имя | Параметры | Возвращает | Клиент получает |
|-----|-----------|-----------|-----------------|
| `vacancy` | `idn: PositiveInt` | `str` | Markdown вакансии в `content` + зеркало в `structuredContent.result` (timeout 30 с, макс. 120 000 символов) |
| `company` | `idn: PositiveInt` | `str` | Markdown страницы компании — так же |
| `search` | `text: NonBlankStr`, `page: NonNegativeInt = 0` | `list[int]` | JSON-массив id в `content` (`[111,222]`) + `structuredContent.result`; пустая выдача — `[]` |

**Фильтры `search` зафиксированы** (`SEARCH_PARAMS` в `service.py`, ровно те
параметры, что шлёт сам hh.ru из drawer-фильтра): зарплата 2 раза в месяц,
полная занятость, опыт от 1 года, только прямые работодатели (`not_from_agency`),
готовые оформить по ТК, любой формат работы (удалённо / офис / гибрид), поиск по
названию вакансии, названию компании и описанию. Параметрами тулзы они не
выведены намеренно: агент, продублировавший их в `text`, только тратит ширину
запроса. Порядок пар и повторяющиеся ключи (`experience`, `label`,
`work_format`, `search_field`) — часть контракта, тест сверяет сгенерированную
строку запроса с кортежем посписочно.

### Ресурсы

| URI | Имя | Содержимое |
|---|---|---|
| `hh-mcp://search-guide` | `SearchGuide` | Markdown-справочник: зафиксированные фильтры, операторы поискового языка hh.ru (`!`, `"`, `~`, `*`, `AND`, `OR`, `NOT`, скобки), поиск по полям (`NAME:`, `COMPANY_NAME:`, `DESCRIPTION:`, `!ID`, `!COMPANY_ID`), рецепты и порядок работы. Текст — в [`search_guide.py`](src/hh_mcp/search_guide.py) |
| `hh-mcp://version` | `BuildInfo` | JSON одной строкой: `version`, `commit`, `build`, `python`, `fastmcp` |

**Инструмент или ресурс** — не украшение, а вопрос цены в токенах: тулза
попадает в схему каждого запроса агента, и на бесполезную `version` он всё
равно отвечал, расходуя и контекст, и вызов. Справочник и метаданные сборки
читаются по требованию. Всё, что делает работу на hh.ru, остаётся тулзой.
URI ресурса назван в описании тулзы `search` — иначе агент не узнает, что он
существует (на это есть тест).

**Версия сборки**: `FastMCP("hh-mcp", version=BUILD_ID)` публикует значение в
стандартном поле `serverInfo.version` ответа `initialize` — его читает любой
MCP-клиент. Ресурс `hh-mcp://version` даёт то же плюс детали. Версия живёт в
`[project].version` (`pyproject.toml`) и поднимается с каждым коммитом; локально
`BUILD_ID` выглядит как `0.4.0+a1b2c3d` (версия + короткий коммит), на деплое —
просто `0.4.0`, потому что `.git` в артефакте нет.

**Валидация**: `id <= 0` → `ToolError("Invalid ID: …")` до HTTP-запроса.
**Ошибки fetch** маппятся в `ToolError` (см. `tool_error()` в
[`service.py`](src/hh_mcp/service.py)).

**Понятные сообщения вместо кодов.** Ответ 4xx/5xx поднимает
`HttpStatusError` (подкласс `TransportError`) — он несёт `status_code`, `url`
и `host` данными, поэтому приложение не разбирает строку httpx (в ней лежат
хост после редиректа и ссылка на MDN — именно из-за них несуществующая вакансия
выглядела как «HTTP 404 … For more information check: developer.mozilla.org»).
`_http_status_message()` переводит статус в человеческий текст и называет
страницу, а не хост:

```
Vacancy 1 does not exist on hh.ru (HTTP 404).
Employer page 999999999999 does not exist on hh.ru (HTTP 400).
hh.ru rate-limited the request (HTTP 429): retry later.
```

**Сообщение сообщает факт, а не версию.** hh.ru отвечает 404 на несуществующую
вакансию и 400 на несуществующего работодателя — оба статуса сводятся к одному
выводу («такой страницы нет»), потому что это единственное, что известно
наверняка. Никаких догадок вроде «id неверный, страница удалена, вакансия в
архиве»: агенту нужен вывод, а не список причин, и выдуманная причина хуже
отсутствующей. Проверяется тестами (`test_message_does_not_speculate`,
`test_400_and_404_say_the_same_thing`).

Закрытая вакансия может ответить и 200: hh.ru редиректит на региональный
лендинг (`kolomna.hh.ru/vrsurvey/...`), и после санитайзера остаётся один
заголовок `# HeadHunter`. Такой ответ (тело < `MIN_CONTENT_CHARS` = 200
символов) отвергается фразой «страница не имеет содержимого на hh.ru» — без
версий о том, закрыта вакансия или нет.

**Пустая выдача `search`** сообщает, какие фильтры действуют (зарплата 2 раза в
месяц, полная занятость, опыт от 1 года, без агентств и ГПХ, формат работы).
Это факт о самом сервере, а не догадка о причине пустого результата.

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

Штатный `ResponseCachingMiddleware` с файловым хранилищем `FileTreeStore`
(без Redis) подключается в `server.py`.

| Где | Ключ | TTL | Отключение |
|---|---|---|---|
| `~/.cache/hh-mcp` | инструмент + аргументы | 1 час | `HH_MCP_CACHE=0` |

Кешируются только успешные ответы `vacancy` / `company`; `search` исключён —
его выдача меняется от страницы к странице. Каталог переопределяется
`HH_MCP_CACHE_DIR`, кеш переживает рестарт сервера. `HH_MCP_CACHE=0` (также
`off` / `false` / `no`) отключает middleware вовсе, и каталог тогда не
создаётся.

Каждое решение видно в логе — ключ и размер, но никогда текст страницы:

```
INFO: disk cache miss: key=dba9f90f…
INFO: page fetched from hh.ru: url=https://hh.ru/vacancy/38185674 chars=6289
INFO: disk cache write: key=dba9f90f… chars=6289 ttl=3600
```

```bash
# Пример: другой каталог дискового кеша
HH_MCP_CACHE_DIR=/var/cache/hh-mcp uv run fastmcp run

# Пример: без кеша
HH_MCP_CACHE=0 uv run fastmcp run
```

### Логи

Сообщения пишутся в stderr на уровне из `log_level` в `fastmcp.json`
(`INFO` — по умолчанию). Их видимость настраивает точка входа:
`fastmcp` конфигурирует только свой логгер и отключает проброс, поэтому
`server._configure_logging()` поднимает обработчик для пространства имён
`hh_mcp` — иначе записи о кеше ушли бы в корневой логгер без хендлера и
пропали бы. Локальная отладка: `fastmcp run --log-level DEBUG`.

> Каталог кеша удаляйте **только при остановленном сервере**: живой
> `FileTreeStore` держит открытые дескрипторы и без каталога падает с
> `FileNotFoundError`.

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

- `deployment.env` игнорируется — значения (`HH_MCP_CACHE`, `HH_MCP_CACHE_DIR`)
  задаются как **environment variables** сервера в Horizon;
- `environment.editable` не поддерживается — пакеты перечисляются в
  `environment.dependencies`;
- если в настройках сервера указан **dependency file**, он имеет приоритет над
  `fastmcp.json` (тогда `project` игнорируется).

Сборка: таймаут 15 минут; зависимости устанавливаются frozen-синком из
`uv.lock`, поэтому лишних пакетов в образ не попадает.

---

## Тесты

```bash
# Запуск всех тестов
uv run pytest tests/ -v
```

**515 тестов**, все passed. Покрытие:
- `test_mcp_app.py` — инструменты, валидация аргументов схемой, error mapping,
  точный набор фильтров `search` и сохранность операторов, форма ответа
  (естественный тип → `content` + зеркало в `structuredContent.result`),
  отсутствие UI-meta, регистрация и содержимое обоих ресурсов (включая проверку,
  что `version` — не тулза, а справочник документирует все операторы и все
  зафиксированные фильтры);
- `test_version.py` — версия из `pyproject.toml`, коммит, `BUILD_ID`,
  `runtime_info`;
- `test_fastmcp_json.py` — конфиг деплоя: транспорт, `log_level` не `DEBUG`,
  `environment.project`, entrypoint;
- `test_disk_cache_logging.py` — `LoggingFileTreeStore`: hit/miss/write в лог,
  размер вместо содержимого;
- `test_caching.py` — файловый кеш: повторный id не дёргает fetch; флаг
  `HH_MCP_CACHE=0`;
- `test_enrich.py` — обогащение employer-карточки;
- `test_guards.py` — SSRF-защита (allowlist `hh.ru`, IP-литералы, `localhost`,
  userinfo, схемы);
- `test_html.py` — санитайзер, NoisePolicy;
- `test_links.py` — разрешение относительных ссылок;
- `test_converter.py` — HTML → Markdown, нормализация (картинки, неразрывные
  пробелы);
- `test_orchestrator.py` — fetch-пайплайн целиком;
- `test_transport.py` — HTTP-транспорт (httpx2);
- `test_config.py` — RequestConfig / NoisePolicy;
- `test_errors.py` — иерархия исключений.

---

## Архитектура

```
src/hh_mcp/
├── __init__.py         логгер пакета (hh_mcp)
├── app.py              поверхность MCP: 3 тулзы, 2 ресурса
├── service.py          ходы на hh.ru: URL страниц, фильтры, текст ошибок
├── search_guide.py     текст ресурса hh-mcp://search-guide
├── version.py          версия сборки (pyproject.toml + короткий коммит)
├── llms.txt            заметки по слою
├── cache/              дисковый кеш ответов
│   ├── __init__.py     логгер слоя кеша (hh_mcp.cache)
│   ├── disk.py         FileTreeStore + ResponseCachingMiddleware
│   └── llms.txt        заметки по слою
└── fetch/              fetch-пайплайн (SOLID/DIP)
    ├── __init__.py     публичное API
    ├── config.py       RequestConfig / NoisePolicy
    ├── errors.py       иерархия исключений
    ├── guards.py       SSRF-защита (UrlGuard)
    ├── transport.py    HTTP-транспорт (httpx2, HTTP/2)
    ├── html.py         HTML-санитайзер
    ├── converter.py    HTML → Markdown (markitdown)
    ├── links.py        разрешение относительных ссылок
    ├── enrich.py       обогащение employer-карточки
    ├── orchestrator.py FetchService + fetch_as_markdown
    └── llms.txt        заметки по слою

server.py               entry point пускателя (fastmcp)
fastmcp.json            конфиг нативного запуска
docs/                   проектные документы
pyproject.toml          метаданные, зависимости
AGENTS.md               конвенции для агентов
```

### Жизненный цикл запроса

```
MCP Client / LLM → FastMCP (streamable HTTP / stdio)
     ↓
Tool fn (vacancy / company → str; search → list[int])
Resource fn (search-guide / version) → str
     ↓
fetch_as_markdown(url, timeout=30, max_chars=120_000)
     ↓
guards.py (SSRF) → transport.py (httpx2, HTTP2) → html.py (Sanitizer + NoisePolicy)
     ↓
links.py (resolve_relative_links) → converter.py (MarkItDown)
     ↓
fastmcp envelope: content + structuredContent.result (wrap-result)
     ↓
MCP Client (search — копейки; страницы — 2.1× к длине текста)
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

Если hh.ru начинает блокировать HTTP-запросы (403 Forbidden), текст ошибки
говорит об этом прямо («hh.ru blocked the request (HTTP 403)»). Обхода в
проекте нет: запросы идут обычным HTTP-клиентом без браузера.

### SSRF-защита

`UrlGuard` ([`guards.py`](src/hh_mcp/fetch/guards.py)) пропускает только URL на
`hh.ru` и его поддомены, а всё прочее отклоняет:
- любой посторонний домен (`example.com`, `hh.ru.evil.com`) — вне allowlist;
- схему, отличную от `http`/`https`;
- логин/пароль (userinfo);
- локальные адреса (`localhost`, зоны `.local`, `.localhost`) и IP-литералы
  (`127.0.0.1`, `[::1]`, `169.254.169.254`, десятичные/hex-формы).

```python
validate_url("https://localhost/test")    # → SSRError
validate_url("https://example.com:443")   # → SSRError (вне allowlist)
validate_url("https://kolomna.hh.ru/")    # → OK (поддомен hh.ru)
```

Allowlist действует и на входе, и **на каждом хопе редиректа**: транспорт идёт
за редиректами вручную (`follow_redirects=False`), пропуская каждый `Location`
через `UrlGuard`, поэтому 302 с `hh.ru` на `localhost` не проходит.

---

## Безопасность

| Механизм | Реализация |
|----------|-----------|
| **SSRF-guard** | [`UrlGuard`](src/hh_mcp/fetch/guards.py) — URL-валидация до HTTP-запроса |
| **TLS verify** | `RequestConfig(verify_tls=True)` — проверка сертификатов |
| **Max body** | 4 MiB — `RequestConfig(max_body_bytes=4_194_304)` |
| **NoisePolicy** | [`config.py`](src/hh_mcp/fetch/config.py) — удаление навигации, рекламы, скриптов |

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
`__all__`-экспорты, константы `SCREAMING_SNAKE_CASE`, PEP 604 (`X | None`),
PEP 695. Комментарий — одна-две строки про «почему»; длинные пояснения живут в
`llms.txt`, а не в модулях.

---

## Документация

- [`docs/plan_mcp_app.md`](docs/plan_mcp_app.md) — архитектурный план (рус.)
- [`docs/apps_mode.md`](docs/apps_mode.md) — режим приложений: интерактивные инструменты (рус.)
- [`docs/fetch_redesign.md`](docs/fetch_redesign.md) — SOLID-спецификация fetch (англ.)
- [`AGENTS.md`](AGENTS.md) — конвенции проекта для агентов
- [`src/hh_mcp/llms.txt`](src/hh_mcp/llms.txt), [`fetch/llms.txt`](src/hh_mcp/fetch/llms.txt), [`cache/llms.txt`](src/hh_mcp/cache/llms.txt) — заметки по слоям
- [`src/hh_mcp/app.py`](src/hh_mcp/app.py) — поверхность MCP
- [`src/hh_mcp/service.py`](src/hh_mcp/service.py) — ходы на hh.ru
- [`server.py`](server.py) — entry point нативного пускателя