# AGENTS.md

Читай документацию по адресу https://gofastmcp.com/llms.txt

Фиксируй изменения в git commits. Создавай прослеживаемую последовательность
изменений. Сделай коммит, когда закончил работу над задачей.

## Что это

MCP-сервер над hh.ru: три текстовых инструмента и два ресурса.

- `vacancy(id)` — страница вакансии, `company(id)` — карточка работодателя
  (оба возвращают Markdown);
- `search(text, page=0)` — поиск с фиксированными фильтрами, возвращает список
  id одной страницы;
- ресурс `hh-mcp://search-guide` — поисковый язык hh.ru и зафиксированные
  фильтры, `hh-mcp://version` — версия сборки.

Тулза объявлена через `@mcp.tool` и возвращает **естественный тип** (`str` у
страниц, `list[int]` у `search`) — конверт строит fastmcp. Значение поэтому едет
и в `content[0].text`, и в `structuredContent.result`: у `search` это копейки, у
страниц — ~2.1× веса ответа. Удвоение принято сознательно ради единой простой
формы всех трёх тулз.

## Слои

- `server.py` — точка входа для нативного пускателя fastmcp: кладёт `src` на
  sys.path, поднимает логирование пространства `hh_mcp`, подключает кеш.
- `src/hh_mcp/app.py` — поверхность MCP: `@mcp.tool` / `@mcp.resource`.
- `src/hh_mcp/service.py` — ходы на hh.ru: URL страниц, фиксированные фильтры
  поиска, текст ошибок.
- `src/hh_mcp/fetch/` — сеть: SSRF-проверка, HTTP-транспорт, HTML → Markdown.
- `src/hh_mcp/cache/` — дисковый кеш ответов (один уровень).
- `src/hh_mcp/version.py` — версия сборки, `search_guide.py` — текст справочника.

Заметки по слоям («почему так», а не «что делает код») — в `llms.txt` рядом с
кодом: `src/hh_mcp/llms.txt`, `src/hh_mcp/fetch/llms.txt`,
`src/hh_mcp/cache/llms.txt`.

## Команды

- `uv run fastmcp run` — MCP-сервер по `fastmcp.json` (transport http,
  `http://127.0.0.1:8000/mcp`). Конфиг ищется автоматически в cwd, path не
  указывать.
- `uv run fastmcp dev apps fastmcp.json` — dev-режим (MCP + браузерный UI). У
  этой подкоманды SERVER-SPEC обязателен.
- `uv run pytest tests/ -q` — весь прогон (515 тестов).
- `uv add <pkg>` — единственный способ добавить зависимость.

## Жёсткие правила

- **Тулза делает работу на hh.ru, справочник и метаданные — ресурс.** Тулза
  висит в схеме каждого запроса агента, ресурс читают по требованию.
- **Тулза возвращает естественный тип, конверт строит fastmcp.** Руками
  `ToolResult` не собираем: `-> str` у страниц, `-> list[int]` у `search`. Плата —
  fastmcp зеркалит значение в `structuredContent.result` (~2.1× на страницу, замер
  на живом сервере). UI-view (Prefab) по-прежнему нет: это была бы третья копия.
- **Валидация аргументов — в сигнатуре, а не в теле.** `PositiveInt` /
  `NonNegativeInt` / `NonBlankStr` (`StringConstraints(strip_whitespace=True,
  min_length=1)`) отсекают мусор на границе MCP ещё до вызова тела тулзы
  (`test_bad_id_is_rejected`, `test_validation`).
- **Сообщение об ошибке — факт, а не версия.** 404 у вакансии и 400 у
  работодателя сводятся к «страницы нет»; никаких «возможно, в архиве»
  (`test_message_does_not_speculate`).
- **Неразрывные пробелы в выводе сворачиваются в обычный** (`U+00A0`, `U+202F`,
  `U+2007`) — выходная гарантия `normalize_markdown`.
- **URI ресурса обязан быть назван в описании тулзы, которая его читает**
  (`search` → `hh-mcp://search-guide`), иначе агент о ресурсе не узнает.

## Сборка и деплой

- Пакетом проект не собирается: `[tool.uv] package = false`, `[build-system]`
  нет. Версия живёт в `pyproject.toml` (`[project].version`), `version.py`
  читает её через `tomllib`.
- `fastmcp.json`: `log_level: INFO` — `DEBUG` даёт `Handler called:` на каждый
  запрос; `environment.project: "."` обязателен для Prefect Horizon, иначе
  сборка падает с `fastmcp is not included in your dependencies`.
- Horizon игнорирует `deployment.env` — переменные окружения задаются в его
  панели, `.env` на деплой не попадает.
- Кеш: каталог `HH_MCP_CACHE_DIR` (по умолчанию `~/.cache/hh-mcp`, удалять
  только при остановленном сервере), `HH_MCP_CACHE=0` отключает middleware.

## Стек

Python ≥3.14; `uv` — единственный менеджер (в `.venv` нет `pip`); `fastmcp 4.x`
(не 2.x/3.x); `httpx2[http2]` (Pydantic-форк, классического `httpx` нет);
`markitdown`. `uv.lock` обязателен к коммиту.

## Стиль

`src/hh_mcp/`, импорт-имя пакета — `hh_mcp`. Двойные кавычки, `# ---` разделы,
`__all__`, SCREAMING_SNAKE-константы, underscores в числах (`120_000`).
Комментарий — одна-две строки про то, **почему** так, а не пересказ кода:
длинные пояснения живут в `llms.txt`, а не в модулях.

## Test cases

Ожидаем чистый Markdown с полезной информацией, без внутренних ссылок, внешние
ссылки сохраняются:

- https://hh.ru/vacancy/138156968
- https://hh.ru/employer/11620617
- https://hh.ru/vacancy/137911901
- https://hh.ru/employer/2163044

## Безопасность (SSRF)

`UrlGuard` ([`guards.py`](src/hh_mcp/fetch/guards.py)) работает по **allowlist**:
пропускает только `hh.ru` и его поддомены (напр. `kolomna.hh.ru`). Всё
остальное — IP-литералы (`127.0.0.1`, `[::1]`, `169.254.169.254`, десятичные
формы), `localhost`/`.local`, любые посторонние домены — отклоняется
(`SSRError`).

Allowlist действует **на каждый хоп редиректа**: `HttpxTransport` идёт за
редиректами вручную (`follow_redirects=False`) и пропускает каждый `Location`
через guard, поэтому 302 с публичного хоста на `localhost` не проходит.

Проверки: `tests/test_guards.py` (allowlist, IP-литералы, поддомены) и
`tests/test_transport.py::test_redirect_to_blocked_host_is_rejected`.
