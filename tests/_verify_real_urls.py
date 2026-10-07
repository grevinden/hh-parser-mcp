"""Manual verification: run the real pipeline against the 4 spec URLs.

Fills in live hh.ru payloads. Not part of the pytest suite (no ``test_``
prefix and the name starts with an underscore); run it directly.
"""

import logging

from hh_mcp.fetch.orchestrator import fetch_as_markdown

logging.basicConfig(level=logging.WARNING)

URLS = [
    "https://hh.ru/vacancy/138156968",
    "https://hh.ru/employer/11620617",
    "https://hh.ru/vacancy/137911901",
    "https://hh.ru/employer/2163044",
]

for url in URLS:
    print("=" * 70)
    print("URL:", url)
    print("=" * 70)
    try:
        md = fetch_as_markdown(url)
    except Exception as exc:  # noqa: BLE001 - verification only
        print("ERROR:", type(exc).__name__, exc)
        print()
        continue
    print(md)
    print()
    print("--- checks ---")
    print("has employer-heading:", "## About the employer:" in md)
    print("len:", len(md))
    # internal-link scan
    import re
    internal = re.findall(r"https?://[^\s)]*hh\.ru[^\s)]*", md)
    print("remaining hh.ru urls:", internal)
    print()
