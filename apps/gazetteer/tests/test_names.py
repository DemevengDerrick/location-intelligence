"""Place names as news articles write them (area signals, FR-28)."""

import importlib

from apps.gazetteer.management.commands.load_boundaries import fix_mojibake

aliases = importlib.import_module("apps.gazetteer.migrations.0003_fix_names_add_aliases")


def test_double_encoded_geoboundaries_names_are_repaired():
    assert fix_mojibake("YaoundÃ© I") == "Yaoundé I"
    assert fix_mojibake("LimbÃ© II") == "Limbé II"
    assert fix_mojibake("Douala V") == "Douala V"


def test_numbered_communes_get_the_spellings_news_uses():
    assert aliases.numbered("Douala V") == [
        "Douala 5", "Douala 5e", "Douala 5ème", "Douala Ve",
    ]  # fmt: skip
    assert aliases.numbered("Yaoundé I")[:3] == ["Yaoundé 1", "Yaoundé 1er", "Yaoundé 1ère"]
    assert aliases.numbered("Bafia") == []
