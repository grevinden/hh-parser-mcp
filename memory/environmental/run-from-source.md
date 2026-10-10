---
name: Запуск из исходников, без сборки пакета
description: Модуль не собирается и не ставится как дистрибутив — приложение стартует из исходников стандартным пускателем fastmcp
metadata:
  type: environmental
---

Собирать модуль не нужно: приложение запускается стандартным пускателем.
`[tool.uv] package = false`, `[build-system]` отсутствует, `uv.lock` помечает
проект как `virtual`. Версия читается из `pyproject.toml` через `tomllib`
(`version.package_version()`), а `server.py` кладёт `src` в `sys.path`; pytest
настроен `pythonpath = ["src", "."]`.

**Как применять:** не добавлять `[build-system]` и console-scripts; установка —
только `uv add <pkg>`; запуск — `uv run fastmcp run` из корня репозитория.
