"""Translation seam.

The mockup is bilingual English/বাংলা. Only English ships now: the Bengali
strings in the mockup cover accounting terms that a native speaker should
check before they reach a partner's desk, and a wrong translation of
"reconciliation variance" is worse than an untranslated one.

Everything user-facing still goes through :func:`t`, so adding a catalogue
later is a data change rather than a sweep through every widget. Keys are the
English source text, which keeps the call sites readable and means a missing
translation degrades to correct English rather than to a key name.
"""

from __future__ import annotations

from typing import Final

#: Language the interface is currently rendering.
_active: str = "en"

#: Catalogues are keyed by language, then by English source string. The Bengali
#: catalogue is intentionally empty rather than absent, so the lookup path is
#: exercised by the tests today and populating it changes nothing else.
_CATALOGUES: Final[dict[str, dict[str, str]]] = {
    "en": {},
    "bn": {},
}

AVAILABLE: Final[tuple[str, ...]] = ("en",)


def set_language(code: str) -> None:
    global _active
    if code not in _CATALOGUES:
        raise ValueError(f"unknown language {code!r}; known: {sorted(_CATALOGUES)}")
    _active = code


def language() -> str:
    return _active


def t(text: str, **fields: object) -> str:
    """Translate and interpolate one user-facing string.

    ``t("Needs review {n}", n=3)`` keeps the placeholder names meaningful in
    the source, which matters when a translator eventually sees them out of
    context.
    """
    translated = _CATALOGUES.get(_active, {}).get(text, text)
    return translated.format(**fields) if fields else translated
