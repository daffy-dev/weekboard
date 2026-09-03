"""Pure-logic pieces of art generation: pulling the SVG out of a model reply,
and turning a prompt into a safe filename stem. The actual Chromium
screenshot step (_shoot_svg) is exercised manually, the same way render.py's
equivalent is — see the note at the top of test_render.py's sibling.
"""

from __future__ import annotations

import pytest

from weekboard.artgen import ArtGenError, _extract_svg, _slug


class TestExtractSvg:
    def test_bare_svg(self):
        text = '<svg width="1240" height="940"><rect/></svg>'
        assert _extract_svg(text) == text

    def test_svg_with_surrounding_prose(self):
        text = 'Here you go:\n\n<svg width="1240" height="940"><rect/></svg>\n\nEnjoy!'
        assert _extract_svg(text) == '<svg width="1240" height="940"><rect/></svg>'

    def test_svg_in_a_fenced_code_block(self):
        text = '```svg\n<svg width="1240" height="940"><circle/></svg>\n```'
        assert _extract_svg(text) == '<svg width="1240" height="940"><circle/></svg>'

    def test_multiline_svg(self):
        text = "<svg width=\"1240\" height=\"940\">\n  <rect/>\n  <circle/>\n</svg>"
        assert _extract_svg(text) == text

    def test_no_svg_raises(self):
        with pytest.raises(ArtGenError):
            _extract_svg("Sorry, I can't help with that.")

    def test_empty_reply_raises(self):
        with pytest.raises(ArtGenError):
            _extract_svg("")


class TestSlug:
    def test_lowercases_and_hyphenates(self):
        assert _slug("Rainy Kyoto Street") == "rainy-kyoto-street"

    def test_strips_punctuation(self):
        assert _slug("neon signs, cherry blossoms!!") == "neon-signs-cherry-blossoms"

    def test_truncates_long_prompts(self):
        assert len(_slug("x" * 200)) <= 40

    def test_blank_prompt_falls_back(self):
        assert _slug("   ") == "art"

    def test_no_leading_or_trailing_hyphen(self):
        assert not _slug("  --wow--  ").startswith("-")
        assert not _slug("  --wow--  ").endswith("-")
