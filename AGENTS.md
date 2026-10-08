# AGENTS.md

Читай документацию по адресу https://gofastmcp.com/llms.txt

This file provides guidance to agents when working with code in this repository.
Фиксируй изменения в git commits.
Создавай прослеживаемую последовательность изменений.
Сделай коммит, когда закончил работу над задачей.

## Сервис предоставляет следующие возможности. 
- Получение данных о работодателе по идентификатору employer_id
- Получение данных о вакансии + о работодателе по идентификатору vacancy_id
- Кеш из двух уровней: **диск** (FileTreeStore, TTL 1 ч, `HH_MCP_CACHE=0` отключает, каталог `HH_MCP_CACHE_DIR` = `~/.cache/hh-mcp`; удалять только при остановленном сервере) → **база** (документ Upstash Search по id `vacancy/38185674`, TTL `HH_MCP_SEARCH_TTL_S` = 86400 с, свежесть по `fetched_at`, непроверяемая метка = протухло) → **сайт**. Каждый шаг пишется в лог (`hh_mcp.server` / `hh_mcp.search_index` / `hh_mcp.app`): `disk cache hit|miss|write`, `db cache hit|miss|stale|write`, `page served from db tier`, `page fetched from hh.ru` — только id и размер, без текста страницы.
- Версия сборки: ресурс `hh-mcp://version` (JSON: version, commit, build, python, fastmcp, search, search_error) + стандартное поле `serverInfo.version` в `initialize`; версия живёт в `pyproject.toml`
- Опциональная индексация страниц в Upstash Search (best-effort): успешные fetch-и вакансий/работодателей отправляются в индекс (env UPSTASH_SEARCH_REST_URL/TOKEN/INDEX), кеш-хиты не индексируются. Документ минимальный: id = путь страницы (`vacancy/38185674`, восстанавливает URL как `https://hh.ru/{id}`), content = одно поле `text` с Markdown (его и эмбедит Upstash), metadata = одно поле `fetched_at` (ISO 8601 UTC). Никаких `url`/`source`/`type` — они выводимы из id. **Переменные `UPSTASH_SEARCH_*` должны быть заданы в окружении деплоя**: `fastmcp.json` их не задаёт (Horizon игнорирует `deployment.env`), `.env` на деплой не попадает; состояние видно в `version()`: `search` = `ready`/`missing`/`unavailable`/`error` плюс `search_error` с текстом последней ошибки (`search_index.status()` делает пробу чтением `list_indexes`, ошибки записи помнятся в `_LAST_ERROR`, а не глотаются).


## Состояние проекта
- **ПРОЕКТ ПОЛНОСТЬЮ РАБОТАЕТ**: MCP-сервер с текстовыми инструментами; единственный вход — нативный пускатель `fastmcp run` из корня (см. «Команды»).
- `src/hh_mcp/app.py` — `FastMCP("hh-mcp", version=BUILD_ID)` с 3 инструментами: `vacancy(id)`, `company(id)`, `search(text, page=0)`; все объявлены как `@mcp.tool` (без `app=`) и возвращают `ToolResult(content=…)` **только с текстом**.
- **ЖЁСТКОЕ ПРАВИЛО: справочник и метаданные — ресурсы, не тулзы.** Тулза попадает в схему каждого запроса агента; на бесполезную `version` он всё равно отвечал. Ресурсы: `hh-mcp://search-guide` (операторы поискового языка hh.ru + зафиксированные фильтры, текст в `src/hh_mcp/search_guide.py` как `SEARCH_GUIDE_MD`) и `hh-mcp://version` (`runtime_info()`). Обе функции объявлены `@mcp.resource(...) -> str` — у ресурсов нет `ToolResult`/`structuredContent`, дублирования данных не бывает by construction. **URI ресурса обязан быть назван в описании тулзы, которая его читает** (`search`), иначе агент не узнает о ресурсе — проверяет `tests/test_mcp_app.py::TestResources::test_search_tool_points_at_the_guide`. Регрессии: `test_version_is_not_a_tool`.
- `SEARCH_PARAMS` + `_search_url(text, page)` в `app.py` — фиксированные параметры запроса (18 пар, порядок как у hh.ru, повторы `experience`/`label`/`work_format`/`search_field`); контракт — посписочное сравнение с кортежем в тесте. Операторы (`!`, `"`, `~`, `*`, `AND`/`OR`/`NOT`) переживают `quote_plus` без искажений.
- `_http_status_message(status, subject)` + `HttpStatusError` (подкласс `TransportError`, поля `status_code`/`url`/`host`) — строку httpx не разбираем (в ней хост после редиректа и ссылка на MDN), `_tool_error(exc, subject=…)` называет страницу. **ЖЁСТКОЕ ПРАВИЛО: сообщение об ошибке — это факт, а не версия.** hh.ru даёт 404 на несуществующую вакансию и 400 на несуществующего работодателя; оба → «X does not exist on hh.ru (HTTP N)». Никаких «возможно, id неверный / страница удалена / вакансия в архиве» — агент получает вывод, а не меню причин, а выдуманная причина хуже отсутствующей (тесты `test_message_does_not_speculate`, `test_400_and_404_say_the_same_thing`). Пустая выдача `search` сообщает только действующие фильтры (факт о сервере), не причину пустоты.
- **ЖЁСТКОЕ ПРАВИЛО: данные в ответе — ровно одна копия.** Причины, по которым это ломается: (1) возврат `-> str` — fastmcp зеркалит текст в `structuredContent.result` (wrap-result); (2) Prefab-view в `structured_content` — вторая копия тех же данных. Замер до/после: 2.10× / 2.17× / 4.41× → 1.04× к длине текста. Регрессии: `tests/test_mcp_app.py::TestSingleCopyResponse`. Обоснование и как вернуть UI — `docs/apps_mode.md`.
- Браузерный Apps UI **отключён** намеренно: `prefab-ui` и экстра `fastmcp[apps]` удалены, импортов `prefab_ui` в коде нет. Сервер всё равно не может отличить вызов модели от вызова приложения (документировано в `fastmcp/apps/config.py`), а флага «запущен с UI» не существует.
- `src/hh_mcp/search_index.py` — второй уровень кеша: `read_page(doc_type, doc_id, max_age_s)` читает документ по id, `index_hh_page` пишет, `status()`/`last_error()`/`search_ttl_s()`/`index_name()`/`endpoint()` — диагностика. **`normalize_url(raw)` обязателен на границе окружения**: значение `UPSTASH_SEARCH_REST_URL` приходит из `.env` (там в кавычках), из `export` и из панели развёртывания (там без схемы) — httpx отвергает оба варианта с `UnsupportedProtocol`, и это выглядело как «сервер не пишет в базу». `_build_client()` больше не зовёт `Search.from_env()` (он читает переменные как есть), а передаёт нормализованные значения в `Search(url=…, token=…)`; предупреждение `UPSTASH_SEARCH_REST_URL is not a plain absolute URL` пишется один раз в лог.
- **ЖЁСТКОЕ ПРАВИЛО: лимит документа — 4096 байт UTF-8, а не символов.** Upstash отвечает `UpstashError: Content is too long: 6461, max: 4096` — русское описание на 6 294 символа весит 6 461 байт, и страница молча не индексировалась (обе вакансии из списка test cases). `split_for_storage(md, max_bytes=MAX_DOC_BYTES)` режет по границе UTF-8, желательно по `\n\n`; `index_hh_page` пишет части одним `upsert` под id `страница`, `страница~2`, …, добавляя в `metadata` `part`/`parts`; `read_page` такую страницу не отдаёт (`split into N parts, cache needs the whole page`) — половина страницы не является страницей. Единицы в логах: `chars=` — символы, `bytes=` — вес в UTF-8; путать их нельзя, именно из-за этого лимит выглядел как «страница влезла».
- `src/hh_mcp/version.py` — `package_version()` (из метаданных установленного пакета), `short_commit()` (git, иначе `unknown`), `build_id()`, `BUILD_ID`, `runtime_info()`. Коммит не должен ломать старт: нет git / нет `.git` / нет коммитов → `unknown`. `runtime_info()` отдаёт `version`, `commit`, `build`, `python`, `fastmcp`, `search`, `search_endpoint` (хост индекса после нормализации; токен не светится никогда), `search_error`.
- `server.py` (корень) — entry point пускателя: `_configure_logging()` поднимает stderr-хендлер для пространства имён `hh_mcp` (fastmcp настраивает только свой логгер и выключает проброс — без этого наши записи о кеше исчезают) и добавляет `ResponseCachingMiddleware` с `LoggingFileTreeStore` (подкласс `FileTreeStore`, логирующий `get`/`put`) (файловый кеш, без Redis; каталог `~/.cache/hh-mcp`, env `HH_MCP_CACHE_DIR`; `HH_MCP_CACHE=0` — middleware не подключается, каталог не создаётся) к серверу из `hh_mcp.app.mcp`, объект `mcp` (entrypoint из `fastmcp.json`).
- `fastmcp.json` (корень) — конфиг нативного запуска (source: `server.py` → `mcp`; deployment: transport `http`, `/mcp`, `log_level: INFO` — **`DEBUG` запрещён** тестом `test_fastmcp_json.py`, он даёт `Handler called:` на каждый запрос; локальная отладка — `fastmcp run --log-level DEBUG`; environment: `uv` + `python: 3.14` + **`project: "."`**). Поле `project` обязательно для Prefect Horizon: он считает `fastmcp.json` авторитетным и без `project`/`dependencies`/`requirements` **не ставит ничего** (сборка падает с `fastmcp is not included in your dependencies`); правки `pyproject.toml` это не лечат. Horizon игнорирует `deployment.env` (значения — только через его environment variables) и не поддерживает `environment.editable`.
- `src/hh_mcp/fetch/` — SOLID/DIP fetch-пайплайн (10 модулей: guards, transport, html, links, converter, orchestrator, config, errors, enrich, __init__).
- `tests/` — 17 тестовых модулей, 581 тест (в т.ч. `test_version.py`, `test_fastmcp_json.py`, `test_search_index.py`, `test_indexing_guard.py`, `test_cache_tiers.py`, `test_disk_cache_logging.py`).
- `tests/conftest.py` ставит `HH_MCP_CACHE=0` **до** импорта тестов: импорт `server.py` иначе прикрепляет реальный middleware к общему `hh_mcp.app.mcp` и пишет в `~/.cache/hh-mcp`, ломая соседние тесты. Там же автофикстуры гасят `UPSTASH_SEARCH_*`, подменяют `index_hh_page` на копилку, переводят логгер `hh_mcp` на проброс (иначе `caplog` ничего не видит) и сбрасывают `search_index._LAST_ERROR` между тестами.
- **ЖЁСТКОЕ ПРАВИЛО: тесты не пишут в живой индекс.** `tests/conftest.py` подменяет `app.index_hh_page` на Recorder-копилку (autouse) и вычищает `UPSTASH_SEARCH_*` из окружения; фикстура `indexed_pages` позволяет проверять, что индексировалось бы. Иначе фикстурный текст («Тело страницы.», «PAGEMARKER») попадает в production-индекс и портит семантический поиск.
- Удалены: `src/hh_mcp/__main__.py` (CLI `hh-mcp`, `--dev`), `src/hh_mcp/devapp.py` (свой dev UI) — dev-режим теперь нативный (`fastmcp dev apps`); Prefab-view из `app.py` — ответ перестал дублироваться.

## Стек
- Python ≥3.14 (CPython 3.14.4); uv 0.12.23 — единственный менеджер: в `.venv` нет `pip` (не использовать); `uv.lock` — существует, обязателен к коммиту.
- Зависимости: `fastmcp 4.0.11` (4.x — НЕ 2.x/3.x), `httpx2[http2]` (Pydantic-форк; классического `httpx` в стеку нет), `markitdown`, `upstash-search`. Убраны как неиспользуемые: `playwright`, `pydantic`, `prefab-ui` и экстра `fastmcp[apps]`.

## Команды
Запуск — **только через нативный пускатель fastmcp, из корня репозитория**:
- `uv run fastmcp run` — MCP-сервер по `fastmcp.json`: конфиг ищется **автоматически** в cwd, path не указывать (transport `http`, `http://127.0.0.1:8000/mcp`). Работает: сервер поднимается, `/mcp` отвечает, все 3 инструмента и 2 ресурса видны клиенту.
- `uv run fastmcp dev apps fastmcp.json` — dev-режим: MCP-сервер + браузерный UI (Prefab/AppBridge, автооткрытие браузера; флаги `--mcp-port`, `--dev-port`, `--no-reload`). Нюанс: у **этой подкоманды** `SERVER-SPEC` обязателен (`fastmcp dev apps --help` → `[required]`) — в отличие от `fastmcp run`, конфиг здесь не авто-ищется.
- `uv run fastmcp run --transport stdio` — переопределение транспорта поверх конфига.
- **Удалено и не воссоздавать**: console-script `hh-mcp` (`[project.scripts]`), `python -m hh_mcp`, `hh-mcp --dev` (свой dev UI в одном процессе).
- `uv run pytest tests/ -v` — полный прогон (581 passed).
- **Один тест**: `uv run pytest tests/test_guards.py -v` (модуль) или `uv run pytest tests/test_guards.py::test_name -v` (функция); class: `tests/test_mcp_app.py::TestResources::test_search_tool_points_at_the_guide`.
- `uv add <pkg>` — единственная установка (уходит в `pyproject.toml`); ruff/mypy молча не подключать.

## Безопасность (SSRF) — указание
- `UrlGuard` должен работать по **allowlist хостов: разрешены только `hh.ru` и его поддомены** (напр. `kolomna.hh.ru`). Всё остальное — IP-литералы (`127.0.0.1`, `[::1]`, `169.254.169.254`, десятичные формы), `localhost`/`.local`, приватные и внутренние адреса, любые посторонние домены — отклонять (`SSRError`).
- Allowlist обязан действовать **на каждый hop редиректа**: guard только на входе недостаточно (302 с публичного хоста на localhost сейчас его обходит).
- Обязательная проверка: `https://localhost/test` должен падать (через `fetch_as_markdown` или `UrlGuard` прямой вызов).
- headers не передаются: ошибка guard — это ошибка валидации, дальше raw headers не передаём.

## Структура / Стиль
- `src/hh_mcp/`; импорт-имя пакета — `hh_mcp` (underscore; дефис невозможен).
- Код под 3.14: `X | None` (PEP 604), PEP 695 type-params ok; linter не настроен — de-facto стандарт = `fetch.py`: double quotes, numpydoc-доки (EN), `# ---`-разделы, `__all__`, SCREAMING_SNAKE-константы, underscores в числах (`120_000`).

## Среда
- FastMCP API: канонический источник — `code-indexer` (MCP-сервер `cix`) → `github.com/PrefectHQ/fastmcp@main` (main = 4.x; онлайн-доки 2.x-эпохи устарели).
- PyCharm: SDK проекта = `.venv` — интерпретатор не менять (при несовпадении — сброс SDK, а не новый venv); `.venv` gitignored (`.gitignore` в корне: `.venv/`, `.env`, `.idea/`, `.roo/`, `.gigacode/`).

## Test cases
Ожидаем чистый markdown с полезной информацией, без внутренних ссылок, внешние ссылки сохраняются:
- https://hh.ru/vacancy/138156968
- https://hh.ru/employer/11620617
- https://hh.ru/vacancy/137911901
- https://hh.ru/employer/2163044