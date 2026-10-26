"""Translations: complete in the three languages, and option names accepted in any of them."""
import re

import pytest

from aster_view import i18n


def test_every_text_in_three_languages():
    for key, texts in i18n.UI.items():
        assert len(texts) == len(i18n.LANGS) and all(t.strip() for t in texts), key
        fields = {tuple(sorted(re.findall(r"{(\w+)}", t))) for t in texts}
        assert len(fields) == 1, f"{key}: placeholders differ between languages"
    for kind, opts in i18n.CHOICES.items():
        for key, labels in opts.items():
            assert len(labels) == len(i18n.LANGS) and all(labels), (kind, key)


@pytest.mark.parametrize("kind, value, key", [
    ("representation", "Superficie con aristas", "surface_edges"),
    ("representation", "Fil de fer", "wireframe"),
    ("representation", "SURFACE WITH EDGES", "surface_edges"),
    ("clip_mode", "Sección", "slice"),
    ("clip_mode", "Mailles entières", "crinkle"),
    ("cell_reduce", "máx. |valor|", "absmax"),
    ("background", "Degradado claro", "light_gradient"),
    ("background", "#123456", "#123456"),
    ("cmap", "Grises", "Grayscale"),
    ("fig_bar", "ninguna", "none"),
    ("fig_width", "1 columna (3,46 in)", "1col"),
])
def test_canonical(kind, value, key):
    assert i18n.canonical(kind, value) == key


def test_language_choice(monkeypatch):
    monkeypatch.delenv("ASTER_VIEW_LANG", raising=False)
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: ("fr_FR", "UTF-8"))
    assert i18n.resolve_lang() == "fr"
    monkeypatch.setenv("ASTER_VIEW_LANG", "es-419")
    assert i18n.resolve_lang() == "es"
    i18n.save_config(language="en")
    assert i18n.resolve_lang() == "en"            # the one chosen in the viewer wins
    assert i18n.resolve_lang("fr") == "fr"        # --lang wins over everything
    assert i18n.tr("fr", "gauss", lo="1", hi="2") == "Aux points de Gauss : min 1   max 2"
