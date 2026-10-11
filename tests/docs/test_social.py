"""Shared links carry absolute image URLs and the title of the page being shared."""

import tomllib
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

DOCS = Path(__file__).parents[2] / "docs"
CONFIG = tomllib.loads((DOCS / "zensical.toml").read_text(encoding="utf-8"))["project"]


class Metadata(HTMLParser):
    """Read the attributes as a crawler would, including decoded HTML entities."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attributes = dict(attrs)
        name = attributes.get("property") or attributes.get("name")
        value = attributes.get("content")
        assert name is not None
        assert value is not None
        assert name not in self.values, f"Duplicate metadata: {name}"
        assert len(attributes) == 2, "Text escaped the content attribute"
        self.values[name] = value


def head(page: SimpleNamespace | None, site_url: str = CONFIG["site_url"]) -> Metadata:
    """Render the actual head override with only the parent block stubbed out."""
    jinja2 = pytest.importorskip("jinja2")
    environment = jinja2.Environment(
        loader=jinja2.ChoiceLoader(
            [
                jinja2.FileSystemLoader(DOCS / "overrides"),
                jinja2.DictLoader({"base.html": "{% block extrahead %}{% endblock %}"}),
            ]
        ),
        undefined=jinja2.StrictUndefined,
    )
    html = environment.get_template("main.html").render(
        config={**CONFIG, "site_url": site_url}, page=page
    )
    return Metadata(html)


@pytest.mark.parametrize("suffix", ["", "/"])
def test_share_image_is_absolute_even_on_nested_pages(suffix: str) -> None:
    page = SimpleNamespace(
        meta={},
        title="Rendering and sharing",
        canonical_url="https://manimgx.academa.ai/user-guide/rendering/",
    )
    meta = head(page, f"https://manimgx.academa.ai{suffix}").values
    image = "https://manimgx.academa.ai/images/social-preview.png"
    assert (
        meta["og:image"]
        == meta["og:image:secure_url"]
        == meta["twitter:image"]
        == image
    )
    assert meta["og:url"] == page.canonical_url
    assert (
        meta["og:title"] == meta["twitter:title"] == "Rendering and sharing - ManimGX"
    )
    assert (
        meta["og:description"]
        == meta["twitter:description"]
        == CONFIG["extra"]["social_description"]
    )
    assert meta["twitter:card"] == "summary_large_image"
    assert meta["twitter:site"] == "@AcademaAI"
    assert meta["og:type"] == "website"
    assert meta["og:site_name"] == "ManimGX"
    assert meta["og:locale"] == "en_US"


@pytest.mark.parametrize("homepage", [True, False])
def test_page_metadata_is_preserved_and_escaped(homepage: bool) -> None:
    title = 'Cameras & "views"'
    description = 'Plot x < 3 & y > 2. " onload="bad'
    meta = head(
        SimpleNamespace(
            meta={"title": title, "description": description},
            title="Fallback",
            canonical_url=CONFIG["site_url"]
            if homepage
            else "https://manimgx.academa.ai/cameras/",
        )
    ).values
    expected = "ManimGX" if homepage else f"{title} - ManimGX"
    assert meta["og:title"] == meta["twitter:title"] == expected
    assert meta["og:description"] == meta["twitter:description"] == description


def test_homepage_and_missing_page_use_the_site_identity() -> None:
    homepage = SimpleNamespace(
        meta={"title": "Welcome"},
        title="Welcome",
        canonical_url=CONFIG["site_url"],
    )
    assert head(homepage).values["og:title"] == "ManimGX"
    error = head(None).values
    assert error["og:title"] == "ManimGX"
    assert "og:url" not in error


def test_description_only_front_matter_keeps_the_page_title() -> None:
    meta = head(
        SimpleNamespace(
            meta={"description": "Draw a scene."},
            title="<em>Quickstart</em>",
            canonical_url="https://manimgx.academa.ai/user-guide/quickstart/",
        )
    ).values
    assert meta["og:title"] == "Quickstart - ManimGX"
    assert meta["og:description"] == "Draw a scene."


def test_committed_card_matches_the_advertised_image() -> None:
    meta = head(None).values
    card = CONFIG["extra"]["social_image"]
    with Image.open(DOCS / "content" / card["path"]) as image:
        image.load()
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == (1200, 630)
        assert image.size == (int(meta["og:image:width"]), int(meta["og:image:height"]))
    assert meta["og:image:type"] == "image/png"
    assert meta["og:image:alt"] == meta["twitter:image:alt"] == card["alt"]
    assert 0 < len(meta["twitter:title"]) <= 70
    assert 0 < len(meta["twitter:description"]) <= 200
    assert 0 < len(meta["twitter:image:alt"]) <= 420
    assert (DOCS / "content" / card["path"]).stat().st_size < 1_000_000
