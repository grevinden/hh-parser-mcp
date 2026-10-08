"""Configuration objects for the fetch package.

Immutable configuration (``frozen=True, slots=True``) with strict validation
in ``__post_init__``. Defaults live in module-level constants — the single
source of truth; dataclass field initializers reference those constants.

No mutable state, no singletons: the factories below are plain functions
that return freshly allocated instances.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .. import __version__

__all__ = [
    "DEFAULT_USER_AGENT",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_KEEPALIVE",
    "PUBLIC_MIN_TIMEOUT",
    "PUBLIC_MAX_TIMEOUT",
    "PUBLIC_DEFAULT_MAX_CHARS",
    "MIN_TIMEOUT",
    "MAX_TIMEOUT",
    "MAX_BODY_BYTES_LIMIT",
    "MARKDOWN_CONVERT_TAGS",
    "TRACKING_QUERY_KEYS",
    "NOISE_CLASS_TOKENS",
    "NOISE_CLASS_PREFIXES",
    "NOISE_DATA_QA",
    "FACT_CELL_QA",
    "ORPHAN_FACT_LABELS",
    "DROP_HREF_SUBSTRINGS",
    "EMPLOYER_MAX_CHARS",
    "EMPLOYER_FETCH_MAX_CHARS",
    "INTERNAL_ROOT_DOMAINS",
    "INTERNAL_PATH_MARKERS",
    "NoisePolicy",
    "RequestConfig",
    "default_config",
    "default_noise_policy",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0"
)
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_BODY_BYTES = 4 * 1024 * 1024  # 4 MiB
DEFAULT_MAX_REDIRECTS = 10
DEFAULT_MAX_CONNECTIONS = 10
DEFAULT_MAX_KEEPALIVE = 5

#: Public API timeout clamp range (spec OQ3: [1.0, 120.0]).
PUBLIC_MIN_TIMEOUT = 1.0
PUBLIC_MAX_TIMEOUT = 120.0
PUBLIC_DEFAULT_MAX_CHARS = 120_000

# ---------------------------------------------------------------------------
# Employer card enrichment
# ---------------------------------------------------------------------------

#: The employer embedded card is capped in characters (kept compact so the
#: vacancy output stays readable); the card body is demoted to H4 under
#: the ``## About the employer: <name>`` section.
EMPLOYER_MAX_CHARS = 2_500

#: Maximum Markdown characters of the fetched employer page before the
#: card cleaning step (the card itself is then capped at
#: ``EMPLOYER_MAX_CHARS``).
EMPLOYER_FETCH_MAX_CHARS = 20_000

# ---------------------------------------------------------------------------
# Internal link stripping
# ---------------------------------------------------------------------------

#: Root domains that mark a link as internal (everything else, including
#: ``*.hhcdn.ru`` CDN and arbitrary third-party hosts, is preserved).  The
#: check compares the registered host suffix: ``hh.ru`` and any subdomain
#: of it (e.g. ``kolomna.hh.ru``) are internal.
INTERNAL_ROOT_DOMAINS: tuple[str, ...] = ("hh.ru",)

#: Job-URL path markers: the registered host is *not* hh.ru, but the path
#: starts with one of these (e.g. ``vacancy11620617.hh.ru``).
INTERNAL_PATH_MARKERS: tuple[str, ...] = ("/vacancy/", "/employer/", "/company/")

#: Substrings that mark a Markdown heading as the *start of the employer
#: page's job list* (everything below is noise and cut from the card).
_VACANCIES_HEADING_MARKERS: tuple[str, ...] = ("vacancies", "ваканси")

#: Substrings that mark a Markdown heading as the *SEO title* of an
#: employer page (the first H1 on such pages, always cut).
_SEO_TITLE_HEADING_MARKERS: tuple[str, ...] = (
    "work at",
    "job at",
    "работа в",
    "актуальные",
    "current vacancies",
)

#: Internal ``RequestConfig`` validation bounds.
MIN_TIMEOUT = 0.001
MAX_TIMEOUT = 300.0
MAX_BODY_BYTES_LIMIT = 64 * 1024 * 1024  # 64 MiB

#: Query-string keys dropped from URLs as click-tracking / analytics
#: parameters (``utm_*`` is matched by prefix, see
#: :func:`hh_mcp.fetch.links.clean_query_params`).
TRACKING_QUERY_KEYS: frozenset[str] = frozenset(
    {
        "hhtmfrom",
        "hhtmfromlabel",
        "backurl",
        "from",
        "ref",
        "refsrc",
        "referrer",
        "aff",
        "affil",
    }
)

#: Tracking keys matched by prefix (compared case-insensitively).
TRACKING_QUERY_KEY_PREFIXES: tuple[str, ...] = ("utm_",)

#: ``href`` substrings that mark an anchor as a boilerplate CTA
#: (e.g. the "Откликнуться" button on employer/vacancy listing pages);
#: the entire element is dropped by the Sanitizer.
DROP_HREF_SUBSTRINGS: tuple[str, ...] = ("applicant/vacancy_response",)

#: ``data-qa`` value of the fact cells in the employer sidebar.  hh.ru
#: renders each cell as value + caption in sibling ``cell-text-content``
#: spans; the cards that hold them are dropped via :data:`NOISE_DATA_QA`.
FACT_CELL_QA: str = "cell-text-content"

#: Captions of the employer sidebar facts ("Город", "Сферы деятельности",
#: "Тип регистрации", "Сайт").  A caption that survives the removal of its
#: card (e.g. the "Сайт" caption rendered inside the description widget)
#: is left dangling in the output, so such orphans are dropped.
ORPHAN_FACT_LABELS: frozenset[str] = frozenset(
    {
        "сайт",
        "город",
        "сферы деятельности",
        "тип регистрации",
        "адрес",
        "сайт компании",
    }
)

#: ``data-qa`` attribute values that mark an element as noise
#: (matched case-insensitively). These are layout artifacts (separator
#: glyphs, widget scaffolding) that survive class-based filtering.
#:
#: ``employer-page-company-info`` / ``sidebar-company-site``: the
#: employer-page fact cards in the right column — "Город" / "Сферы
#: деятельности" / "Тип регистрации" (``data-qa="company-info-*"`` cells)
#: and the separate website card ("Сайт").  The description proper lives
#: in a separate ``div.g-user-content`` block, which is kept.
#:
#: ``competitor-companies-*`` / ``branded-employer-gallery``: the
#: "Ещё компании для вас" recommendation widget on employer pages — its
#: heading, its tooltip activator and the horizontally scrollable card
#: strip (logo, name, "N активных вакансий", "Посмотреть").  Without the
#: strip being dropped, sanitisation leaves it as bare text: the internal
#: "Посмотреть" links are stripped later by
#: :func:`~hh_mcp.fetch.enrich.remove_internal_links`, which keeps the label
#: and yields "ПосмотретьN активных вакансий" noise in the Markdown.
NOISE_DATA_QA: frozenset[str] = frozenset(
    {
        "employer-page-reviews-badges-separator",
        "employer-page-company-info",
        "sidebar-company-site",
        "competitor-companies-title",
        "competitor-companies-hint-activator",
        "branded-employer-gallery",
    }
)


#: Stable noise tokens for hh.ru (exact, case-insensitive class matching).
NOISE_CLASS_TOKENS: frozenset[str] = frozenset(
    {
        "hidden",
        "ads",
        "advertisement",
        "noprint",
        "vacancy-action",
        "vacancy-actions",
        "vacancy-address-map",
        "vacancy-address-map-wrapper",
        # NOTE: "vacancy-response-questions" is kept as an exact token for the
        # bare class; the hashed variant (``..._with-suggest--<hash>``) is
        # also caught by NOISE_CLASS_PREFIXES below.
        "vacancy-response-questions",
        # NOTE: "vacancy-description-print" is NOT noise: on branded-layout
        # hh.ru pages it wraps the on-screen vacancy description
        # (vacancy-branded-user-content), not a print-only duplicate.
        "policy-informer",
        "vacancy-card-footer",
        "action-bar",
        "empty-element",
        # Branded-layout footer: wraps the "Видео о нас" VK video block.
        "tmpl_hh_footer",
        # Wrapper around the "Вакансия опубликована <date>" line.
        "bloko-gap",
    }
)

#: Prefixes of hash-suffixed Magritte classes (``bottom-section--<hash>``)
#: that must be treated as noise on hh.ru pages.
NOISE_CLASS_PREFIXES: frozenset[str] = frozenset(
    {
        "bottom-section",
        "noindex",
        "top-element",
        "vacancy-action-bar",
        "vacancy-contact",
        "vacancy-downloader",
        "vacancy-similar",
        "vacancy-feedback",
        "magritte-bottom",
        # NOTE: "chameleon-item" is NOT noise — on employer pages the
        # ``chameleon-item--<hash>`` class wraps content-bearing items such
        # as ``data-qa="company-info-address"`` / ``company-info-site``.
        "chameleon-top-element-custom",
        "hh-containerformicrofrontend-employerreviews",
        "employer-reviews",
        "recommendation-row",
        # Hash-suffixed variant: ``vacancy-response-questions_with-suggest--<hash>``
        # wraps the "Задайте вопрос работодателю" block on vacancy pages.
        # On employer pages this widget is absent; on some layouts the bare
        # class is also caught by NOISE_CLASS_TOKENS above.
        "vacancy-response-questions",
        # ``tmpl_hh_footer__<part>``: sub-elements of the branded-layout
        # "Видео о нас" footer (the outer div is a token, this is a
        # belt-and-suspenders for templates that render children separately).
        "tmpl_hh_footer",
        # ``title-row--<hash>``: the "Dream Job / Отзывы о компании" widget
        # header. On employer pages it is nested inside ``noprint`` (already
        # suppressed); on vacancy pages it sits in a plain ``bloko-text``
        # wrapper, so the prefix is required to drop it.
        "title-row",
    }
)


# ---------------------------------------------------------------------------
# NoisePolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NoisePolicy:
    """Elements/attributes the Sanitizer removes as boilerplate.

    Attributes:
        remove_elements:
            Tag names (lowercase) whose entire subtree is removed.
        remove_classes:
            ``class`` tokens (e.g. ``"hidden"``) that mark an element as
            noise; matching is case-insensitive, exact token only.
        remove_class_prefixes:
            ``class``-token prefixes (e.g. ``"bottom-section"``) that mark
            an element as noise; used for build-generated classes with
            hash suffixes (``bottom-section--abc123``). Case-insensitive.
        remove_attrs_prefix:
            Attribute-name prefixes (e.g. ``"data-ad"``) that mark an
            element as noise.
        drop_href_substrings:
            Substrings of the ``href`` attribute (compared
            case-insensitively) that mark an element as a drop target —
            the entire subtree is removed (boilerplate CTAs such as the
            "Откликнуться" response buttons).
        remove_data_qa:
            ``data-qa`` attribute values (compared case-insensitively)
            that mark an element as noise (layout artifacts left over
            after class-based filtering).
        main_extraction:
            When ``True`` the Sanitizer keeps only the content of the
            first ``<main>`` element (main-block extraction): content
            before ``<main>`` (header / nav / cookie banners) and after
            it (footer) is dropped.  A document without ``<main>``
            passes through unchanged (lenient).  When ``False`` the
            whole document is kept.
    """

    remove_elements: frozenset[str] = frozenset(
        {
            "nav",
            "aside",
            "footer",
            "header",
            "form",
            "script",
            "style",
            "iframe",
            "noscript",
            "svg",
            "template",
            "button",
            "input",
            "select",
            "textarea",
            "noindex",
        }
    )
    remove_classes: frozenset[str] = frozenset(NOISE_CLASS_TOKENS)
    remove_class_prefixes: frozenset[str] = frozenset(NOISE_CLASS_PREFIXES)
    remove_attrs_prefix: frozenset[str] = frozenset({"data-ad"})
    drop_href_substrings: tuple[str, ...] = DROP_HREF_SUBSTRINGS
    remove_data_qa: frozenset[str] = frozenset(NOISE_DATA_QA)
    main_extraction: bool = True

    def is_noise(self, tag: str, attrs: Mapping[str, str | None]) -> bool:
        """Return ``True`` if the element is noise per this policy.

        Args:
            tag:
                Element tag name (any case).
            attrs:
                Attribute mapping as produced by
                :class:`html.parser.HTMLParser` (value may be ``None``).

        Returns:
            bool
                ``True`` when the element must be removed.
        """
        tag_lower = tag.lower()
        if tag_lower in self.remove_elements:
            return True

        classes = (attrs.get("class") or "").split()
        prefixes = self.remove_class_prefixes
        for token in classes:
            if token.casefold() in self.remove_classes:
                return True
            if prefixes and any(token.casefold().startswith(p) for p in prefixes):
                return True

        for name in attrs:
            if name.lower().startswith(tuple(self.remove_attrs_prefix)):
                return True

        data_qa = (attrs.get("data-qa") or "").casefold()
        if data_qa and data_qa in self.remove_data_qa:
            return True

        href = (attrs.get("href") or "").casefold()
        if href and any(s.casefold() in href for s in self.drop_href_substrings):
            return True

        return False


# ---------------------------------------------------------------------------
# RequestConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequestConfig:
    """HTTP transport configuration (immutable).

    Attributes:
        user_agent:
            ``User-Agent`` header value; must be non-empty.
        timeout:
            HTTP timeout in seconds; ``MIN_TIMEOUT`` <= value <=
            ``MAX_TIMEOUT``.
        max_body_bytes:
            Maximum response body size in bytes.
        max_redirects:
            Maximum number of redirects to follow (0 disables following).
        max_connections:
            Maximum open connections in the client pool.
        max_keepalive:
            Max keep-alive connections; must not exceed ``max_connections``.
        verify_tls:
            Whether TLS certificates are verified.
        strict_content_type:
            When ``True``, a non-HTML response Content-Type raises
            :class:`~hh_mcp.fetch.errors.UnsupportedContentTypeError`;
            when ``False`` (default, back-compat) it only logs a
            WARNING and the conversion proceeds.
        noise:
            Noise policy used by the HTML sanitizer.
    """

    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = DEFAULT_TIMEOUT
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    max_connections: int = DEFAULT_MAX_CONNECTIONS
    max_keepalive: int = DEFAULT_MAX_KEEPALIVE
    verify_tls: bool = True
    strict_content_type: bool = False
    noise: NoisePolicy = NoisePolicy()

    def __post_init__(self) -> None:
        """Validate fields; raise :class:`ValueError` with the field name.

        Raises:
            ValueError:
                On any constraint violation. The message always starts with
                the offending field name (``"<field>: <reason>"``).
        """
        if not isinstance(self.user_agent, str) or not self.user_agent:
            raise ValueError("user_agent: must be a non-empty string")

        if not isinstance(self.timeout, (int, float)) or isinstance(
            self.timeout, bool
        ):
            raise ValueError("timeout: must be a number")
        if not (MIN_TIMEOUT <= self.timeout <= MAX_TIMEOUT):
            raise ValueError(
                f"timeout: must be within [{MIN_TIMEOUT}, {MAX_TIMEOUT}]"
            )

        if not isinstance(self.max_body_bytes, int) or isinstance(
            self.max_body_bytes, bool
        ):
            raise ValueError("max_body_bytes: must be an int")
        if not (0 < self.max_body_bytes <= MAX_BODY_BYTES_LIMIT):
            raise ValueError(
                f"max_body_bytes: must be within (0, {MAX_BODY_BYTES_LIMIT}]"
            )

        if not isinstance(self.max_redirects, int) or isinstance(
            self.max_redirects, bool
        ):
            raise ValueError("max_redirects: must be an int")
        if not (0 <= self.max_redirects <= 20):
            raise ValueError("max_redirects: must be within [0, 20]")

        if not isinstance(self.max_connections, int) or isinstance(
            self.max_connections, bool
        ):
            raise ValueError("max_connections: must be an int")
        if self.max_connections <= 0:
            raise ValueError("max_connections: must be > 0")

        if not isinstance(self.max_keepalive, int) or isinstance(
            self.max_keepalive, bool
        ):
            raise ValueError("max_keepalive: must be an int")
        if self.max_keepalive <= 0:
            raise ValueError("max_keepalive: must be > 0")
        if self.max_keepalive > self.max_connections:
            raise ValueError(
                "max_keepalive: must not exceed max_connections"
            )


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def default_config() -> RequestConfig:
    """Return a fresh :class:`RequestConfig` with default values.

    Returns:
        RequestConfig
            A new instance; no shared/global state.
    """
    return RequestConfig()


def default_noise_policy() -> NoisePolicy:
    """Return a fresh :class:`NoisePolicy` with default values.

    Returns:
        NoisePolicy
            A new instance; no shared/global state.
    """
    return NoisePolicy()


# ---------------------------------------------------------------------------
# Markdown convert whitelist
# ---------------------------------------------------------------------------

#: Tags that ``markitdown`` (via markdownify) should convert/format.
#: Tags NOT in this set still have their content preserved as plain text
#: (markdownify 1.x does **not** strip non-whitelisted content).
#: Actual noise removal (``<template>``, ``<nav>``, etc.) is the
#: responsibility of :class:`NoisePolicy` / the Sanitizer.
MARKDOWN_CONVERT_TAGS: frozenset[str] = frozenset(
    {
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "br", "hr", "blockquote",
        "ul", "ol", "li",
        "strong", "b", "em", "i", "code", "pre",
        "a", "img",
        "table", "thead", "tbody", "tr", "th", "td",
        "article", "section", "main", "hgroup",
    }
)
