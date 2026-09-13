"""Attribute-value coercion: BeautifulSoup returns ``AttributeValueList``
(list[str]) for multi-valued attributes (``class``, ``rel``, …). Any raw
``.strip()`` on such a value raises ``AttributeError`` and can sink an entire
run. ``attr_text`` always yields a plain ``str`` without ever inventing text."""

from __future__ import annotations


def attr_text(value) -> str:
    """Coerce a BeautifulSoup attribute value to a single clean string.

    Joining the string members of an ``AttributeValueList`` with a single space
    reproduces the attribute's original serialized text exactly; nothing is
    invented and non-string members are never coerced into misleading text.
    """
    if isinstance(value, list):
        return " ".join(item for item in value if isinstance(item, str))
    return value if isinstance(value, str) else ""