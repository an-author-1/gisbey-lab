"""Legibility: every text colour token is >= 4.5:1 against every surface it is used on,
in the light AND the dark scheme, and no rule bypasses the tokens with a literal colour."""
import re

from gibsey_lab.reader import server as reader_server

CSS = (reader_server.STATIC_DIR / "style.css").read_text()

# text token -> the surface tokens it is drawn on
PAIRS = {
    "--text": ["--bg", "--surface", "--surface-inset", "--surface-passage", "--control-bg", "--control-hover"],
    "--text-secondary": ["--bg", "--surface", "--surface-inset", "--surface-passage", "--control-bg"],
    "--accent-text": ["--accent"],
    "--accent-soft-text": ["--accent-soft-bg"],
    "--link": ["--bg", "--surface"],
    "--tag-text": ["--tag-bg"],
    "--good": ["--surface", "--good-bg"],
    "--warn": ["--surface", "--warn-bg"],
    "--info": ["--surface"],
    "--bad": ["--surface", "--bad-bg"],
    "--neutral": ["--surface"],
    "--stale": ["--surface", "--surface-passage", "--banner-bg"],
}


def _tokens(block: str) -> dict:
    return dict(re.findall(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{6})", block))


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _schemes():
    light_block = CSS[CSS.index(":root {"):CSS.index("@media (prefers-color-scheme: dark)")]
    dark_block = CSS[CSS.index("@media (prefers-color-scheme: dark)"):CSS.index("* { box-sizing")]
    return {"light": _tokens(light_block), "dark": _tokens(dark_block)}


def test_every_text_token_is_at_least_4_5_to_1_on_every_surface_in_both_schemes():
    failures = []
    for scheme, tokens in _schemes().items():
        for text, surfaces in PAIRS.items():
            for surface in surfaces:
                ratio = contrast(tokens[text], tokens[surface])
                if ratio < 4.5:
                    failures.append(f"{scheme}: {text} {tokens[text]} on {surface} {tokens[surface]} = {ratio:.2f}:1")
    assert not failures, failures


def test_both_schemes_define_the_same_tokens_and_rules_use_only_tokens():
    schemes = _schemes()
    assert set(schemes["light"]) == set(schemes["dark"])
    rules = CSS[CSS.index("* { box-sizing"):]
    assert not re.findall(r"#[0-9a-fA-F]{3,6}\b", rules), "a rule uses a literal colour instead of a theme token"
    assert "!important" not in rules.replace("[hidden] { display: none !important; }", "")


def test_the_active_operator_button_is_filled_not_just_bold():
    active = re.search(r"\.operator-row button\.active[^{]*\{([^}]*)\}", CSS).group(1)
    assert "background: var(--accent)" in active and "color: var(--accent-text)" in active
    for scheme, tokens in _schemes().items():
        assert contrast(tokens["--accent"], tokens["--control-bg"]) >= 3, scheme  # distinct from an inactive button
