from __future__ import annotations

from stockidence.service import sub_scores


def test_spec_has_entries_for_known_components():
    for slug in (
        "discount_to_fair_value",
        "price_vs_smas",
        "macd",
        "margin_quality",
        "realized_vol",
        "beta",
    ):
        assert sub_scores.COMPONENT_SPEC[slug]["label"]
        assert sub_scores.COMPONENT_SPEC[slug]["sources"]
        assert sub_scores.COMPONENT_SPEC[slug]["direction"]


def test_unknown_component_falls_back_to_readable_name():
    assert sub_scores.component_label("some_new_component") == "Some New Component"
    assert sub_scores.component_sources("some_new_component") == ""
    assert sub_scores.component_direction("some_new_component") == ""


def test_known_component_label_and_sources():
    assert sub_scores.component_label("price_vs_smas") == "Price vs SMA50/SMA200"
    assert "SMA" in sub_scores.component_sources("price_vs_smas")