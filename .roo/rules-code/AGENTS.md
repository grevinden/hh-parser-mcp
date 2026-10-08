# Project Coding Rules (Non-Obvious Only)

- uv only: `uv add <pkg>` / `uv sync` / `uv run`; в `.venv` нет `pip` (не использовать); `uv.lock` коммитить.
- Python 3.14: `X | None` (PEP 604) вместо `Optional`; PEP 695 type-params ok; `from __future__ import annotations` не нужен.
- FastMCP 4.x (НЕ 2.x/3.x): API только через code-indexer `cix` → `github.com/PrefectHQ/fastmcp@main`; онлайн-доки (2.x-эпоха) устарели.
- HTTP: в server-code — только async-клиенты; пакет — `httpx2` (`import httpx2 as httpx`), классического `httpx` в стеку нет; `requests`/sync запретить внутри `async def`.
- `fetch.py` намеренно sync (port Go `webfetch`) — «чинить» в async без решения нельзя (sync httpx внутри async tool блокирует event loop).
- De-facto стандарт = стиль `fetch.py`: double quotes, numpydoc-доки (EN), `# ---`-секции, `__all__`, SCREAMING_SNAKE, underscores в числах; linter/formatter не настроены — не подключать молча.
- API-ключи только через env (при появлении — `.env.example`); импорт-имя пакета — `hh_mcp` (src-layout).
