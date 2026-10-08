# Режим приложений FastMCP: интерактивные инструменты

> Раздел отвечает на вопросы: что такое «режим приложений» (apps mode),
> чем UI-инструмент отличается от обычного инструмента, как передаются
> параметры, кто кого вызывает и как вызывать hh-mcp из другого приложения
> по API.

> **Актуально для hh-mcp:** отдельных UI-инструментов нет. Все три тулзы
> (`vacancy`, `company`, `search`) работают **одновременно** для модели и для
> браузера — см. §1.1. Описание ролей `@app.ui()` / `@app.tool()` ниже
> сохранено как справочный материал о механике FastMCP.

---

## 1.1. Один инструмент — модель и браузер (как в hh-mcp)

Это штатный сценарий FastMCP Apps, описанный в
[gofastmcp.com/apps/prefab](https://gofastmcp.com/apps/prefab). Два элемента:

1. **`app=PrefabAppConfig(...)`** в декораторе — инструмент получает
   синтезированный ресурс рендерера `ui://prefab/tool/<hash>/renderer.html`
   и попадает в браузерный пикер; форма ввода строится из его JSON-схемы.
2. **`ToolResult(content=…, structured_content=…)`** — «The user sees the
   chart. The model sees the summary»: `content` уходит модели, `structured_content`
   рисует рендерер (раздел «Giving the LLM context» в документации).

```python
from fastmcp.apps import PrefabAppConfig
from fastmcp.tools import ToolResult
from prefab_ui.components import Column, DataTable, DataTableColumn, Markdown

UI_CONFIG = PrefabAppConfig(visibility=["app", "model"])

@mcp.tool(app=UI_CONFIG)
def search(text: str, page: int = 0) -> ToolResult:
    """Найти вакансии."""
    ids = fetch_ids(text, page)

    with Column(gap=4, css_class="p-6") as view:
        DataTable(
            columns=[DataTableColumn(key="id", header="Vacancy ID", sortable=True)],
            rows=[{"id": i} for i in ids],
            search=True,
        )

    summary = f"Найдено {len(ids)} вакансий: " + ", ".join(map(str, ids))
    return ToolResult(content=summary, structured_content=view)
```

**Почему это важно и неочевидно.** Если вернуть из тулзы «просто данные», то
`structuredContent` будет содержать `result`/`$prefab`-обёртку без `view`, и
рендерер покажет бесконечный спиннер «Waiting for content…»: он рисует
`structuredContent.view` и больше ничего (`prefab_ui/renderer/app.html`).
Именно `structured_content` с компонентом делает страницу рабочей.

Проверено на живом сервере (`tools/list` + `tools/call`):

| Тулза | `resourceUri` | `structuredContent` | `content[0].text` |
|---|---|---|---|
| `vacancy` | `ui://prefab/tool/<hash>/renderer.html` | `$prefab` + `view` | Markdown страницы |
| `company` | то же | `$prefab` + `view` | Markdown компании |
| `search` | то же | `$prefab` + `view` (`DataTable`) | список ID |

Отдельная `@app.ui()`-панель по-прежнему нужна, когда UI **сам** вызывает
backend-тулзы (форма с кнопкой, CRUD, мастер) — для этого есть `FastMCPApp`
и `CallTool`. В hh-mcp это не требуется: форму ввода рисует пикер по схеме.

---

## 1.2. Справочно: две роли инструментов в FastMCP

Обычный MCP-инструмент (например, `vacancy`) принимает JSON-аргументы и
возвращает текст. Его вызывает модель (LLM) или внешний клиент.

**Режим приложений (apps / Interactive Tools)** — это способ превратить
инструмент в **интерактивную страницу в браузере**: формы, кнопки, поля ввода,
таблицы, графики. Такой инструмент возвращает не текст, а **дерево UI-компонентов**
(Prefab), которое хост (клиент MCP с поддержкой приложений) рендерит как
живой интерфейс. Пользователь видит приложение и работает с ним мышью.

В hh-mcp это реализовано через `FastMCPApp` — обёртку, которая разделяет
инструменты на две роли:

| Роль | Декоратор | Что делает | Кто вызывает |
|---|---|---|---|
| **UI-точка входа** (entry point) | `@app.ui()` | Возвращает дерево компонентов — открывает панель в браузере | Модель / клиент |
| **Backend-инструмент** | `@app.tool()` | Собственно выполняет работу, возвращает данные | UI (через `CallTool`), модель — только при `model=True` |

Подход описан в официальной документации FastMCP:
[gofastmcp.com/apps/fastmcp-app](https://gofastmcp.com/apps/fastmcp-app).

---

## 2. Как это устроено в hh-mcp

В `src/hh_mcp/app.py` зарегистрированы **3 инструмента**, и каждый из них
обслуживает обе аудитории (механика — §1.1):

| Инструмент | Параметры | Результат |
|---|---|---|
| `vacancy(id)` | `{"id": integer}` — обязательный | Markdown страницы hh.ru |
| `company(id)` | `{"id": integer}` — обязательный | Markdown страницы компании |
| `search(text, page)` | `{"text": string}` — обязательный, `page: int = 0` | `list[int]` — ID вакансий |

Отдельных `@app.ui()`-входов нет: раньше были `vacancy_app` / `employer_app` /
`search_app`, но они дублировали те же функции и требовали отдельной схемы.
Теперь браузер запускает ту же тулзу, что и модель, — форма строится из её же
`inputSchema`. Схема исторической связки (для справки):

```python
@app.ui()
def vacancy_app() -> Column:              # 1. Модель открывает панель (исторически)
    id_input = Input(placeholder="ID вакансии…", name="vacancy_id")  # 2. Поле ввода
    return Column(
        children=[
            Heading("Просмотр вакансии"),
            id_input,
            Button(
                "Получить вакансию",
                on_click=CallTool(
                    tool="vacancy",                    # 3. Кнопка → vacancy
                    arguments={"id": "{{ vacancy_id }}"},  # 4. id берётся из поля
                    on_success=ShowToast("Готово", variant="success"),
                    on_error=ShowToast("Ошибка", variant="error"),
                ),
            ),
        ],
    )
```

Схема параметров у клиента-модели (проверено на живой реализации):

| Инструмент | Схема параметров (`inputSchema`) |
|---|---|
| `vacancy` | `{"id": {"type": "integer"}}` — обязательный |
| `company` | `{"id": {"type": "integer"}}` — обязательный |
| `search` | `{"text": {"type": "string"}, "page": {"type": "integer", "default": 0}}` |

Это те же схемы, из которых пикер строит браузерную форму, — дублей нет.

---

## 3. Параметры: кто, как и через что их передаёт

### 3.1. Через обычный API (JSON)

Любой MCP-клиент вызывает backend-инструмент, передавая аргументы **JSON**:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "vacancy",
    "arguments": {"id": 138156968}
  }
}
```

### 3.2. Через UI (без JSON руками)

Пользователь **не пишет JSON**: он вводит значение в поле ввода. Дальше:

1. `Input(name="vacancy_id")` кладёт значение поля в состояние интерфейса под
   ключом `vacancy_id`.
2. В `arguments` кнопки написано `{"id": "{{ vacancy_id }}"}` — это **шаблонная
   подстановка** (interpolation): перед вызовом `{{ vacancy_id }}` заменяется
   текущим значением поля.
3. `CallTool` отправляет на сервер ровно тот же
   `tools/call` `{"name": "vacancy", "arguments": {"id": …}}`, что и в 3.1.

То есть UI — это удобная обёртка над тем же самым JSON-RPC-вызовом.

### 3.3. Как ввод попадает в тулзу в браузере

В пикере форма генерируется автоматически из `inputSchema`, и отправка идёт
через `POST /api/launch` с теми же именем тулзы и аргументами, что и в 3.1.
Ручная подстановка `{{ поле }}` нужна только в самописной `@app.ui()`-панели:
там `Input(name="vacancy_id")` кладёт значение в состояние, а в
`arguments` написано `{"id": "{{ vacancy_id }}"}` — шаблонная подстановка перед
вызовом.

---

## 4. Кто кого вызывает: видимость (visibility)

«Какие-то функции вызываются, какие-то нет» — это про **видимость**:

| Декоратор | Видимость по умолчанию | Виден модели (LLM) | Виден UI (кнопкам/формам) |
|---|---|---|---|
| `@app.ui()` | `["model"]` | ✅ | ❌ (отклоняется) |
| `@app.tool()` | `["app"]` | ❌ | ✅ |
| `@app.tool(model=True)` | `["app", "model"]` | ✅ | ✅ |

В hh-mcp все три тулзы объявлены как
`@mcp.tool(app=PrefabAppConfig(visibility=["app", "model"]))`, поэтому их видит и
модель, и браузерный пикер.

Следствия:

- **Модель** вызывает 3 инструмента и получает Markdown / `list[int]`.
- **UI** (панель в браузере) может вызывать только backend-инструменты —
  через `CallTool`. Сам себя он вызвать не может.
- Если убрать `model=True`, инструмент исчезнет из списка модели, но останется
  доступным кнопкам UI.

> ⚠️ Видимость — **не** граница безопасности: инструмент остаётся вызываемым
> по прямому `tools/call` любым клиентом, знающим его имя. Защита — на уровне
> авторизации/валидации сервера.

---

## 5. Есть ли API? Как вызвать hh-mcp из другого приложения

**API есть** — это стандартный MCP-сервер по протоколу JSON-RPC, ничего
«приложенческого» в транспорте нет. Режим приложений меняет только **содержимое
ответа**, не способ вызова.

### 5.1. Точка входа

По умолчанию (transport `http`, см. `fastmcp.json`):

```
http://127.0.0.1:8000/mcp
```

### 5.2. Список инструментов

```
POST /mcp
```

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
```

Ответ содержит 3 инструмента: `vacancy`, `company`, `search`.

### 5.3. Вызов инструмента

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/call",
 "params": {"name": "vacancy", "arguments": {"id": 138156968}}}
```

Ответ — `isError: false` и Markdown страницы. Поиск:

```json
{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
 "params": {"name": "search", "arguments": {"text": "Программист 1С", "page": 0}}}
```

Ответ — `list[int]` идентификаторов вакансий.

### 5.4. (исторически) Вызов UI-инструмента

Отдельных UI-инструментов больше нет. Раньше вызов выглядел так:

```json
{"jsonrpc": "2.0", "id": 4, "method": "tools/call",
 "params": {"name": "vacancy_app", "arguments": {}}}
```

Ответ — `isError: false`, текст `[Rendered Prefab UI]` и поле
`structured_content` с деревом компонентов (`{"$prefab": …, "view": …}`).
Это дерево рендерит **хост, поддерживающий приложения** (FastMCP dev-UI,
Prefab-хост). Обычный JSON-клиент получит тот же ответ, но без рендера —
полезной нагрузки (текста вакансии) здесь нет, её даёт `vacancy`.

### 5.5. Итог

| Нужно | Инструмент | Аргументы |
|---|---|---|
| Получить Markdown вакансии | `vacancy` | `{"id": int}` |
| Получить Markdown компании | `company` | `{"id": int}` |
| Найти ID вакансий | `search` | `{"text": str, "page": int}` |

### 5.6. Формат ответа: что видит модель и что рисует браузер

Ответ `tools/call` на `search` — это `ToolResult` (см. §1.1):

```json
{
  "content": [{"type": "text", "text": "Найдено 17 вакансий (страница 0): 138103881, …"}],
  "structuredContent": {
    "$prefab": {"version": "0.3"},
    "view": {"type": "Div", "cssClass": "pf-app-root", "children": [ … DataTable … ]}
  }
}
```

- `content[0].text` — то, что читает модель (для `vacancy` / `company` это
  Markdown страницы целиком);
- `structuredContent.view` — то, что рисует рендерер Prefab.

Обе части — штатный вывод fastmcp 4.x, данные не дублируются: `view` содержит
только дерево компонентов, а сами ID лежат в `content`.

### 5.7. Тосты «Готово» / «Ошибка» — только для самописных панелей

В hh-mcp тостов нет: браузер запускает тулзы через пикер и показывает ответ на
странице хоста. Тосты относятся к самописным `@app.ui()`-панелям — там, где UI
сам вызывает backend-тулзу через `CallTool`.

Если такая панель понадобится, механизм такой: `on_success` →
`SetState(key=…, value="{{ $result }}")`, затем `If(condition="{{ … }}")`
рисует значение; `$result` доступен в scope обработчика. `on_error` показывает
**текст ошибки** через подстановку `{{ $error }}` — например, для
несуществующего ID hh.ru отвечает 404, и пользователь увидит `HTTP 404 …`
вместо глухого «Ошибка».

---

## 6. Генеративный интерфейс (Generative UI) — отдельная вещь

Не путать интерактивные инструменты (то, что в hh-mcp) с **Generative UI**
([gofastmcp.com/apps/generative](https://gofastmcp.com/apps/generative)):

- Интерактивный инструмент — интерфейс описан в коде (`@mcp.tool(app=True)`
  возвращает Prefab-компонент, либо UI вызывает backend через `FastMCPApp`).
- Generative UI — **модель сама пишет код интерфейса на ходу**: инструмент
  `generate_prefab_ui` принимает Python-код (строку), выполняет его в песочнице
  (Pyodide) и рендерит результат как приложение.

---

## 7. Поток запроса целиком

```
Модель (MCP)                              hh-mcp (FastMCP)
──────────────────                        ──────────────────
tools/call vacancy {id}  ──►  fetch_as_markdown(hh.ru/vacancy/{id})
                                     │
                                     ▼
                       ToolResult{content: Markdown,      ──►  модели
                                   structured_content: view}

Браузер (Apps UI):
пользователь → пикер → форма из inputSchema → POST /api/launch
              → GET /launch → хост вызывает ту же тулзу с теми же аргументами
              → structuredContent.view рисуется рендерером Prefab
```

---

## 8. Типичные заблуждения (коротко)

1. **«Параметры надо передавать JSON»** — да, на уровне протокола всегда JSON
   (`arguments`). В UI пользователь передаёт их не руками, а через поля форм и
   подстановку `{{ }}`.
2. **«Какие-то функции вызываются, какие-то нет»** — это видимость
   (`model`/`app`), см. таблицу в разделе 4.
3. **«Непонятно, есть ли API»** — есть: обычный MCP JSON-RPC на `/mcp`; все
   3 инструмента видны в `tools/list`.
4. **«UI-инструменты и обычные — это разные сущности?»** — в hh-mcp нет:
   тулзы одни и те же, браузер запускает ту же `vacancy`/`company`/`search`,
   что и модель (см. §1.1). Отдельная `@app.ui()`-панель нужна только ради
   собственного layout'а.
5. **«Тулза вернула данные, а в браузере “Waiting for content…”»** — значит в
   `structuredContent` нет `view`. Рендерер рисует только `view`; возвращайте
   `ToolResult(content=…, structured_content=<Prefab-компонент>)` (см. §1.1).
7. **«Вакансия вернулась как `# HeadHunter` на 12 символов»** — вакансия
   закрыта/снята: hh.ru отдал лендинг, а не карточку. Инструмент это отвергает
   (`MIN_CONTENT_CHARS`), чтобы не выдавать пустоту за данные.
8. **«Инструмент не появился в веб-инструментах»** — пикер показывает тулзы с
   `resourceUri` в `meta["ui"]`, который даёт `app=True` /
   `app=PrefabAppConfig(...)`; обычный `@mcp.tool()` без него в пикер не попадает.
   Дополнительно: `tools/list` кешируется middleware на 5 минут, поэтому после
   изменения состава инструментов подождите TTL, либо запустите с чистым
   каталогом (`HH_MCP_CACHE_DIR=/tmp/hh-cache`), либо вовсе без кеша
   (`HH_MCP_CACHE=0`).
9. **«Нажал кнопку — а результат не видно»** — в пикере ответ показывается на
   странице хоста и в панели операций dev-UI; в своей `@app.ui()`-панели
   результат нужно положить в состояние через `SetState(…, "{{ $result }}")`
   (см. §5.7).

---

## 9. Ссылки

- FastMCPApp (UI вызывает backend-тулзы): <https://gofastmcp.com/apps/fastmcp-app>
- Интерактивные инструменты (`app=True`, `ToolResult`): <https://gofastmcp.com/apps/prefab>
- Обзор режима приложений: <https://gofastmcp.com/apps/overview>
- Generative UI: <https://gofastmcp.com/apps/generative>
- Быстрый старт: <https://gofastmcp.com/apps/quickstart>
- Реализация в проекте: [`src/hh_mcp/app.py`](../src/hh_mcp/app.py)