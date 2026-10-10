---
name: Слои: поверхность / сценарии / чтение / кеш
description: Код разложен на слои — MCP-поверхность, сценарии hh.ru, чтение интернета, кеширование и тонкий композиционный корень
metadata:
  type: decision
---

`app.py` перерос во всё сразу: MCP-инструменты, URL-ы hh.ru, оркестрация
страниц, тексты ошибок и поисковый запрос. Разложено послойно (коммит `32a6a2c`):

- `app.py` — только MCP-поверхность: инструменты `vacancy`/`company`/`search` и
  ресурсы `hh-mcp://search-guide`, `hh-mcp://version`.
- `service.py` — сценарии hh.ru: `SEARCH_PARAMS`, `_search_url`, `tool_error`,
  `fetch_page_markdown`, `search_vacancy_ids`, лимиты `TIMEOUT_S`, `MAX_CHARS`,
  `MIN_CONTENT_CHARS`.
- `fetch/` — чтение из интернета и HTML → Markdown.
- `cache/` — дисковый кеш: `LoggingFileTreeStore`, `_approx_chars`,
  `cache_enabled`, `attach(mcp)`.
- `server.py` — тонкий композиционный корень (`attach(mcp)`).

**Как применять:** сценарную логику класть в `service.py`, кеш — в `cache/`,
а поверхность `app.py` держать тонкой.
