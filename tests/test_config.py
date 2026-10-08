"""Tests for configuration objects: RequestConfig, NoisePolicy, factories."""

from __future__ import annotations

import copy
from typing import Mapping

import pytest

from hh_mcp.fetch.config import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_KEEPALIVE,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    DROP_HREF_SUBSTRINGS,
    IMAGE_ELEMENTS,
    MARKDOWN_CONVERT_TAGS,
    MAX_BODY_BYTES_LIMIT,
    MAX_TIMEOUT,
    MIN_TIMEOUT,
    NOISE_DATA_QA,
    NoisePolicy,
    RequestConfig,
    default_config,
    default_noise_policy,
)


class TestNoisePolicy:
    """Spec §3.2 / §5 — noise removal policy."""

    def test_default_removes_script_style(self) -> None:
        policy = default_noise_policy()
        # Script and style are removed via LITERAL_ELEMENTS, not via noise;
        # but they should be in the default set for safety.
        assert "script" in policy.remove_elements
        assert "style" in policy.remove_elements

    def test_is_noise_tag_only(self, default_policy: NoisePolicy) -> None:
        assert default_policy.is_noise("script", {})
        assert default_policy.is_noise("style", {"type": "text/css"})

    def test_is_noise_class(self, default_policy: NoisePolicy) -> None:
        # Elements marked with a noise class are removed even when the tag
        # itself is not in remove_elements.
        assert default_policy.is_noise("div", {"class": "hidden"})
        assert default_policy.is_noise("section", {"class": "ads"})
        assert default_policy.is_noise("span", {"class": "advertisement"})

    def test_is_noise_class_token_and_case(self, default_policy: NoisePolicy) -> None:
        """Class matching is token-based and case-insensitive."""
        assert default_policy.is_noise("div", {"class": "menu HIDDEN"})
        assert not default_policy.is_noise("div", {"class": "menu-footer"})

    def test_is_noise_class_hash_suffix(self, default_policy: NoisePolicy) -> None:
        """Hash-suffixed Magritte classes are caught by prefix matching."""
        assert default_policy.is_noise("div", {"class": "bottom-section--abc123"})
        # match must be token-prefix based: similar names are not noise
        assert not default_policy.is_noise("div", {"class": "bottom-thing--abc123"})

    def test_is_noise_class_prefix_case(self, default_policy: NoisePolicy) -> None:
        """Prefix matching is also case-insensitive."""
        assert default_policy.is_noise("div", {"class": "Bottom-Section--ABC"})

    def test_is_noise_hh_ru_residual_blocks(self, default_policy: NoisePolicy) -> None:
        """hh.ru page-tail widgets are covered by the default policy.

        Regression: ``vacancy-description-print`` must NOT be in the
        token set (on branded-layout pages it wraps the on-screen
        description, not a print-only duplicate).
        """
        assert "vacancy-description-print" not in default_policy.remove_classes
        # vacancy page tail: video block, publication-date line,
        # "ask the employer" question form (token + prefix for
        # the ``..._with-suggest--<hash>`` variant)
        assert "tmpl_hh_footer" in default_policy.remove_classes
        assert "bloko-gap" in default_policy.remove_classes
        assert "vacancy-response-questions" in default_policy.remove_classes
        assert "vacancy-response-questions" in default_policy.remove_class_prefixes
        assert default_policy.is_noise(
            "div", {"class": "vacancy-response-questions_with-suggest--AB12"}
        )
        # "Dream Job / отзывы" widget header (hash-suffixed token)
        assert "title-row" in default_policy.remove_class_prefixes
        assert default_policy.is_noise("div", {"class": "title-row--Zg55iMPk3h"})

    def test_is_noise_attrs_prefix(self, default_policy: NoisePolicy) -> None:
        """Elements with attrib names starting with noise prefixes are noise."""
        assert default_policy.is_noise("div", {"class": "content", "data-ad": "true"})

    def test_chameleon_item_not_noise_prefix(self, default_policy: NoisePolicy) -> None:
        """Regression: ``chameleon-item--<hash>`` wraps content-bearing
        company-info items (address / site) on employer pages and must
        NOT be dropped by prefix matching.
        """
        assert "chameleon-item" not in default_policy.remove_class_prefixes
        assert not default_policy.is_noise(
            "div", {"class": "chameleon-item--q732_IJ2RMDA6xaH"}
        )
        # Related scaffolding stays noise.
        assert default_policy.is_noise(
            "div", {"class": "chameleon-top-element-custom--abc123"}
        )

    def test_is_noise_drop_href_substrings(self, default_policy: NoisePolicy) -> None:
        """Anchors pointing at the CTA response flow are dropped (F2)."""
        assert "applicant/vacancy_response" in DROP_HREF_SUBSTRINGS
        assert default_policy.is_noise(
            "a",
            {
                "class": "magritte-button",
                "href": "https://hh.ru/applicant/vacancy_response?vacancyId=1&employerId=2",
            },
        )
        assert default_policy.is_noise(
            "a", {"href": "/applicant/vacancy_response?vacancyId=3"}
        )
        # Case-insensitive, substring match.
        assert default_policy.is_noise(
            "a", {"href": "https://hh.ru/APPLICANT/vacancy_response"}
        )
        # Ordinary links are not affected.
        assert not default_policy.is_noise("a", {"href": "https://hh.ru/vacancy/123"})

    def test_is_noise_data_qa(self, default_policy: NoisePolicy) -> None:
        """Elements marked with a noise ``data-qa`` value (F5)."""
        assert "employer-page-reviews-badges-separator" in NOISE_DATA_QA
        assert default_policy.is_noise(
            "div", {"data-qa": "employer-page-reviews-badges-separator"}
        )
        # Case-insensitive.
        assert default_policy.is_noise(
            "div", {"data-qa": "Employer-Page-Reviews-Badges-Separator"}
        )
        # Other data-qa values are content-bearing.
        assert not default_policy.is_noise("div", {"data-qa": "company-info-address"})

    def test_is_noise_data_qa_none_value(self, default_policy: NoisePolicy) -> None:
        """Optional attrs may arrive with ``None`` values; no crash."""
        assert not default_policy.is_noise("div", {"data-qa": None, "href": None})

    @pytest.mark.parametrize(
        "data_qa",
        [
            # Right-column fact cards on employer pages ("Город" /
            # "Сферы деятельности" / "Тип регистрации").  The website card
            # ("sidebar-company-site") is content, not noise.
            "employer-page-company-info",
            # "Ещё компании для вас" recommendation widget.
            "competitor-companies-title",
            "competitor-companies-hint-activator",
            "branded-employer-gallery",
        ],
    )
    def test_is_noise_employer_sidebar_noise(self, default_policy: NoisePolicy, data_qa):
        """Employer-page sidebar widgets are noise (case-insensitive)."""
        assert data_qa in NOISE_DATA_QA
        assert default_policy.is_noise("div", {"data-qa": data_qa})
        assert default_policy.is_noise("div", {"data-qa": data_qa.upper()})

    def test_company_description_block_is_not_noise(
        self, default_policy: NoisePolicy
    ) -> None:
        """The description widget and the fact *cells* stay content-bearing
        on their own — only their card containers are noise."""
        assert not default_policy.is_noise(
            "div", {"data-qa": "employer-view-widget-description"}
        )
        assert not default_policy.is_noise(
            "div", {"data-qa": "company-info-address", "class": "chameleon-item--x"}
        )

    def test_non_noise_elements(self, default_policy: NoisePolicy) -> None:
        assert not default_policy.is_noise("p", {"class": "content"})
        assert not default_policy.is_noise("h1", {})
        assert not default_policy.is_noise("article", {"class": "post"})
        assert not default_policy.is_noise("div", {"id": "main-content"})

    def test_is_noise_without_attrs(self, default_policy: NoisePolicy) -> None:
        """Tag-only noise detection (attrs may be empty mapping)."""
        assert default_policy.is_noise("script", {})
        assert default_policy.is_noise("nav", {})

    def test_image_elements_are_noise(self, default_policy: NoisePolicy) -> None:
        """A picture is never content, with or without attributes."""
        assert IMAGE_ELEMENTS == frozenset({"img", "picture", "source"})
        assert IMAGE_ELEMENTS <= default_policy.remove_elements
        assert default_policy.is_noise("img", {})
        assert default_policy.is_noise(
            "img", {"src": "https://hhcdn.ru/i.png", "alt": "Фото"}
        )
        assert default_policy.is_noise("picture", {})
        assert default_policy.is_noise("source", {"srcset": "a.webp"})

    def test_svg_is_noise(self, default_policy: NoisePolicy) -> None:
        """Vector graphics are pictures too."""
        assert default_policy.is_noise("svg", {})
        assert default_policy.is_noise("svg", {"class": "icon"})

    def test_img_not_in_convert_whitelist(self) -> None:
        """The converter must not turn an image into Markdown.

        The Sanitizer removes the tag; whitelisting ``img`` here would let
        markdownify re-create ``![alt](src)`` for markup that survived.
        """
        assert "img" not in MARKDOWN_CONVERT_TAGS
        assert {"h1", "p", "a", "li"} <= MARKDOWN_CONVERT_TAGS

    def test_frozen_and_slotted(self) -> None:
        policy = default_noise_policy()
        with pytest.raises(AttributeError):
            policy.remove_elements = frozenset()  # type: ignore[misc]

    @pytest.fixture
    def default_policy(self) -> NoisePolicy:
        return default_noise_policy()


class TestRequestConfig:
    """Spec §3.2 / §5 — transport configuration (frozen, strict validation)."""

    def test_default_values_match_constants(self) -> None:
        cfg = default_config()
        assert cfg.timeout == DEFAULT_TIMEOUT
        assert cfg.max_body_bytes == DEFAULT_MAX_BODY_BYTES
        assert cfg.max_redirects == DEFAULT_MAX_REDIRECTS
        assert cfg.max_connections == DEFAULT_MAX_CONNECTIONS
        assert cfg.max_keepalive == DEFAULT_MAX_KEEPALIVE
        assert cfg.user_agent == DEFAULT_USER_AGENT
        assert cfg.verify_tls is True
        assert cfg.strict_content_type is False
        assert cfg.noise is not None

    def test_user_agent_contains_package_name(self) -> None:
        assert "Chrome" in DEFAULT_USER_AGENT
        assert "/" in DEFAULT_USER_AGENT or "Safari" in DEFAULT_USER_AGENT

    def test_noise_policy_in_default_config(self) -> None:
        cfg = default_config()
        assert isinstance(cfg.noise, NoisePolicy)
        assert "script" in cfg.noise.remove_elements
        assert "style" in cfg.noise.remove_elements

    # --- __post_init__ validation ---

    @pytest.mark.parametrize(
        "bad_timeout",
        [
            0.0,
            -1.0,
            0.0005,  # below MIN_TIMEOUT
            301.0,  # above MAX_TIMEOUT
            500.0,
        ],
    )
    def test_timeout_clamp_via_post_init(self, bad_timeout) -> None:
        with pytest.raises((ValueError, AssertionError)):
            RequestConfig(timeout=bad_timeout)

    def test_max_timeout_edge_allowed(self) -> None:
        """MAX_TIMEOUT must be accepted."""
        cfg = RequestConfig(timeout=MAX_TIMEOUT)
        assert cfg.timeout == MAX_TIMEOUT

    def test_min_timeout_edge_allowed(self) -> None:
        cfg = RequestConfig(timeout=MIN_TIMEOUT)
        assert cfg.timeout == MIN_TIMEOUT

    def test_max_body_bytes_zero(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            RequestConfig(max_body_bytes=0)

    def test_max_body_bytes_negative(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            RequestConfig(max_body_bytes=-1)

    def test_max_body_bytes_too_large(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            RequestConfig(max_body_bytes=MAX_BODY_BYTES_LIMIT + 1)

    @pytest.mark.parametrize("bad_redirects", [-1, 21, 100])
    def test_max_redirects_out_of_range(self, bad_redirects) -> None:
        with pytest.raises((ValueError, AssertionError)):
            RequestConfig(max_redirects=bad_redirects)

    @pytest.mark.parametrize("bad_keepalive", [0, -1, 51])
    def test_max_keepalive_out_of_range(self, bad_keepalive) -> None:
        with pytest.raises((ValueError, AssertionError)):
            RequestConfig(max_keepalive=bad_keepalive)

    def test_max_keepalive_exceeds_max_connections(self) -> None:
        """max_keepalive must be <= max_connections."""
        with pytest.raises((ValueError, AssertionError)):
            RequestConfig(max_keepalive=50, max_connections=10)

    def test_empty_user_agent(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            RequestConfig(user_agent="")

    # --- Frozen / immutability ---

    def test_frozen(self) -> None:
        cfg = default_config()
        with pytest.raises(AttributeError):
            cfg.timeout = 60.0  # type: ignore[misc]

    def test_slots(self) -> None:
        cfg = default_config()
        with pytest.raises(AttributeError):
            cfg.__dict__  # noqa: B018  # slots dataclass has no __dict__

    # --- Equality (frozen dataclasses are eq) ---

    def test_equality(self) -> None:
        cfg1 = default_config()
        cfg2 = default_config()
        assert cfg1 == cfg2
        assert hash(cfg1) == hash(cfg2)

    def test_inequality(self) -> None:
        cfg1 = default_config()
        cfg2 = RequestConfig(timeout=15.0)
        assert cfg1 != cfg2

    # --- Custom noise policy ---

    def test_custom_noise_policy(self) -> None:
        noise = NoisePolicy(remove_elements=frozenset({"noscript"}))
        cfg = RequestConfig(noise=noise)
        assert cfg.noise.is_noise("noscript", {})
        assert not cfg.noise.is_noise("script", {})

    # --- Constructor keywords ---

    def test_constructor_ignores_noise_default(self) -> None:
        """Caller can omit noise; the default is populated."""
        cfg = RequestConfig(timeout=10.0)
        assert isinstance(cfg.noise, NoisePolicy)