"""Configuration objects for the fetch package."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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
    "IMAGE_ELEMENTS",
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

#: Cap on the embedded employer card, kept compact; the body is demoted to H4.
EMPLOYER_MAX_CHARS = 2_500

#: Cap on the fetched employer page before card cleaning
#: (the card itself is then capped at ``EMPLOYER_MAX_CHARS``).
EMPLOYER_FETCH_MAX_CHARS = 20_000

# ---------------------------------------------------------------------------
# Internal link stripping
# ---------------------------------------------------------------------------

#: Link hosts that count as internal: ``hh.ru`` and its subdomains. Everything
#: else (``*.hhcdn.ru``, third-party) is preserved.
INTERNAL_ROOT_DOMAINS: tuple[str, ...] = ("hh.ru",)

#: Path prefixes that mark a link internal even when the host is not hh.ru.
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

# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

#: Image-bearing elements, removed whole: ``img`` is the picture, ``picture`` /
#: ``source`` are its responsive variants. The *tag* goes, not just ``src``, so
#: the ``alt`` text vanishes with it instead of dangling as a stray word.
IMAGE_ELEMENTS: frozenset[str] = frozenset({"img", "picture", "source"})

#: Query keys dropped as click-tracking / analytics (``utm_*`` by prefix).
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

#: ``href`` substrings marking a boilerplate CTA (the whole element is dropped).
DROP_HREF_SUBSTRINGS: tuple[str, ...] = ("applicant/vacancy_response",)

#: ``data-qa`` of the employer-sidebar fact cells (cards dropped via NOISE_DATA_QA).
FACT_CELL_QA: str = "cell-text-content"

#: Captions of the employer sidebar facts; a caption whose card was removed
#: (the "Сайт" one inside the description widget) would dangle, so orphans go.
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

#: ``data-qa`` values marking layout noise (case-insensitive):
#: ``employer-page-company-info`` — sidebar fact cards (the description itself
#: is a separate ``g-user-content`` block, kept); ``competitor-companies-*`` /
#: ``branded-employer-gallery`` — the "Ещё компании для вас" widget.
#: ``sidebar-company-site`` is NOT noise: the website is content.
NOISE_DATA_QA: frozenset[str] = frozenset(
    {
        "employer-page-reviews-badges-separator",
        "employer-page-company-info",
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
    """Elements/attributes the Sanitizer removes as boilerplate."""

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
        | IMAGE_ELEMENTS
    )
    remove_classes: frozenset[str] = frozenset(NOISE_CLASS_TOKENS)
    remove_class_prefixes: frozenset[str] = frozenset(NOISE_CLASS_PREFIXES)
    remove_attrs_prefix: frozenset[str] = frozenset({"data-ad"})
    drop_href_substrings: tuple[str, ...] = DROP_HREF_SUBSTRINGS
    remove_data_qa: frozenset[str] = frozenset(NOISE_DATA_QA)
    main_extraction: bool = True

    def is_noise(self, tag: str, attrs: Mapping[str, str | None]) -> bool:
        """Return ``True`` if the element is noise per this policy."""
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
    """HTTP transport configuration (immutable)."""

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
        """Validate fields; raise :class:`ValueError` with the field name."""
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
    """Return a fresh :class:`RequestConfig` with default values."""
    return RequestConfig()


def default_noise_policy() -> NoisePolicy:
    """Return a fresh :class:`NoisePolicy` with default values."""
    return NoisePolicy()


# ---------------------------------------------------------------------------
# Markdown convert whitelist
# ---------------------------------------------------------------------------

#: Tags markitdown should format; other tags keep their content as plain text.
#: ``img`` is deliberately absent — the Sanitizer already drops every picture,
#: and whitelisting it would let markdownify emit ``![alt](src)``.
MARKDOWN_CONVERT_TAGS: frozenset[str] = frozenset(
    {
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "br", "hr", "blockquote",
        "ul", "ol", "li",
        "strong", "b", "em", "i", "code", "pre",
        "a",
        "table", "thead", "tbody", "tr", "th", "td",
        "article", "section", "main", "hgroup", "div",
    }
)
