"""Projector models, their command specification, and what each one supports.

The model (``MD`` reply, e.g. ``ILAFPJ -- B8A2``) identifies a model family, and each
family follows one of JVC's external command specifications. Which settings a
family supports, and the codes some of them use, come from pyjvcprojector's
per-specification command table (github.com/SteveEasley/pyjvcprojector,
``jvcprojector/command/command.py``).

An unknown model gets every entity: a query it doesn't answer is backed off by the
coordinator, so trying costs little.
"""

from __future__ import annotations

import re

from .jvcprojector import const

CS20241 = "CS20241"  # 2024: NZ800 / NZ900 family
CS20242 = "CS20242"  # 2024: NZ500 / NZ700 family
CS20221 = "CS20221"  # 2022: NZ7 / NZ8 / NZ9 family
CS20191 = "CS20191"  # 2019: NX5 / NX7 / NX9 family

# Model code -> (product name, other names for the same family, specification).
MODELS: dict[str, tuple[str, str, str]] = {
    "B8A1": ("DLA-NZ900", "RS4200, N1188, V900R", CS20241),
    "B8A2": ("DLA-NZ800", "RS3200, N988, V800R", CS20241),
    "D8A1": ("DLA-NZ700", "RS2200, N899, N888, N800, Z7", CS20242),
    "D8A2": ("DLA-NZ500", "RS1200, N799, N788, N700, Z5", CS20242),
    "B5A1": ("DLA-NZ9", "RS4100, N11, V90R", CS20221),
    "B5A2": ("DLA-NZ8", "RS3100, N98, V80R", CS20221),
    "B5A3": ("DLA-NZ7", "RS2100, N88, V70R", CS20221),
    "B5B1": ("DLA-NP5", "RS1100, N78, V50", CS20221),
    "B2A1": ("DLA-NX9", "RS3000, NX11, V9R", CS20191),
    "B2A2": ("DLA-NX7", "RS2000, N7, N8, V7", CS20191),
    "B2A3": ("DLA-NX5", "RS1000, N5, N6, V5", CS20191),
    "A2B1": ("DLA-NX9", "RS3000, NX11, V9R", CS20191),
    "A2B2": ("DLA-NX7", "RS2000, N7, N8, V7", CS20191),
    "A2B3": ("DLA-NX5", "RS1000, N5, N6, V5", CS20191),
}

# Commands a specification does NOT support (everything else is supported).
UNSUPPORTED: dict[str, frozenset[str]] = {
    const.PMLL: frozenset({CS20242}),  # Low Latency
    const.PMNM: frozenset({CS20242}),  # Theater Optimizer
    const.PMME: frozenset({CS20242}),  # Motion Enhance
    const.PMUS: frozenset({CS20242, CS20221, CS20191}),  # 8K e-shift: NZ800/900 only
    const.PMCV: frozenset({CS20221, CS20191}),  # Laser power (LD current)
    const.PMDC: frozenset({CS20221, CS20191}),  # Dynamic control
}

# Clear Motion Drive option -> code, per specification.
CMD_CODES_CS20242 = {"off": "0", "low": "7", "high": "6"}
CMD_CODES_DEFAULT = {"off": "0", "low": "3", "high": "4", "inverse_telecine": "5"}

_CODE_RE = re.compile(r"([A-Z0-9]{4})\s*$")


def model_code(raw: str | None) -> str | None:
    """Return the four-character family code: 'ILAFPJ -- B8A2' -> 'B8A2'."""
    if not raw:
        return None
    m = _CODE_RE.search(raw.strip())
    return m[1] if m else None


def spec_for(raw: str | None) -> str | None:
    """Return the command specification for a model, or None if unknown.

    Like pyjvcprojector: an exact match first, then the first three characters
    (so a new variant such as B8A3 is treated like B8A2).
    """
    code = model_code(raw)
    if code is None:
        return None
    if code in MODELS:
        return MODELS[code][2]
    for known, (_, _, spec) in MODELS.items():
        if known[:3] == code[:3]:
            return spec
    return None


def model_name(raw: str | None) -> str | None:
    """Return the product name ('DLA-NZ800'), or the raw value if unknown."""
    if not raw:
        return None
    code = model_code(raw)
    if code in MODELS:
        return MODELS[code][0]
    return raw.strip()


def supports(raw: str | None, command: str) -> bool:
    """Return whether this model supports a command (True for an unknown model)."""
    spec = spec_for(raw)
    if spec is None:
        return True
    return spec not in UNSUPPORTED.get(command, frozenset())


def cmd_codes(raw: str | None) -> dict[str, str]:
    """Return the Clear Motion Drive option -> code map for this model."""
    if spec_for(raw) == CS20242:
        return CMD_CODES_CS20242
    return CMD_CODES_DEFAULT
