"""Minimal Mustache-like template renderer.

Supports:
  {{variable}}              — string substitution
  {{#section}}...{{/section}}  — include block if variable is truthy/non-empty
  {{^section}}...{{/section}}  — include block if variable is falsy/empty

No loops, no partials, no escaping.
"""
from __future__ import annotations
import re
from typing import Any

_SECTION_RE = re.compile(
    r"\{\{([#^])(\w+)\}\}(.*?)\{\{/\2\}\}",
    re.DOTALL,
)
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def render_template(template: str, variables: dict[str, Any]) -> str:
    """Render template with the given variables dict."""

    def replace_section(m: re.Match) -> str:
        polarity, name, body = m.group(1), m.group(2), m.group(3)
        value = variables.get(name)
        truthy = bool(value)
        include = truthy if polarity == "#" else not truthy
        return render_template(body, variables) if include else ""

    result = _SECTION_RE.sub(replace_section, template)
    result = _VAR_RE.sub(lambda m: str(variables.get(m.group(1), "")), result)
    return result
