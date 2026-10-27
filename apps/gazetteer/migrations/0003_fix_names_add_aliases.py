"""Repair geoBoundaries names stored double-encoded ("YaoundÃ©") and add the aliases news
articles use, so area signals can match place names (FR-28): French region names,
"Douala 5e" for the "Douala V" commune, and the city names for Wouri and Mfoundi."""

import re

from django.db import migrations

REGION_ALIASES = {
    "East": ["Est"],
    "Far North": ["Extrême-Nord", "Extreme-Nord", "Extrême Nord"],
    "North": ["Nord"],
    "North-West": ["Nord-Ouest", "Northwest"],
    "South": ["Sud"],
    "South-West": ["Sud-Ouest", "Southwest"],
    "West": ["Ouest"],
}
DEPARTMENT_ALIASES = {"Wouri": ["Douala"], "Mfoundi": ["Yaoundé", "Yaounde"]}
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}


def fix(name):
    if "Ã" not in name and "Â" not in name:
        return name
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def numbered(name):
    """'Douala V' -> 'Douala 5', 'Douala 5e', 'Douala 5ème', 'Douala Ve' (and 1er for I)."""
    match = re.fullmatch(r"(.+) (I|II|III|IV|V|VI|VII)", name)
    if not match:
        return []
    city, roman = match.groups()
    n = ROMAN[roman]
    suffixes = ["er", "ère"] if n == 1 else ["e", "ème"]
    return [f"{city} {n}"] + [f"{city} {n}{s}" for s in suffixes] + [f"{city} {roman}e"]


def forwards(apps, schema_editor):
    Place = apps.get_model("gazetteer", "GazetteerPlace")
    for place in Place.objects.all():
        for field in ("name", "region", "department", "arrondissement", "commune"):
            setattr(place, field, fix(getattr(place, field)))
        extra = []
        if place.place_type == "region":
            extra = REGION_ALIASES.get(place.name, [])
        elif place.place_type == "department":
            extra = DEPARTMENT_ALIASES.get(place.name, [])
        elif place.place_type == "commune":
            extra = numbered(place.name)
        place.aliases = list(dict.fromkeys([*place.aliases, *extra]))
        place.save()


class Migration(migrations.Migration):
    dependencies = [("gazetteer", "0002_alter_gazetteerplace_place_type")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
