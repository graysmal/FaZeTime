"""Deterministic name aliasing for downstream matching (P4). Transcript text itself is sent verbatim.

Measured on the P0-B team audio (Pi, tiny.en/base.en, no decoder prompt): the spoken "FaZeGavin" comes
out as "face, Gavin", "phase Gavin", "Faze Gavin", "Please Gavin"; "FaZeNeville" as "face neville" /
"phase neville". Decoder prompts (hotwords/initial_prompt) fixed the spelling but fabricated names and
"1v1" in non-speech chunks, so canonicalisation happens here, after ASR, on untrusted text.
"""
from __future__ import annotations

import re

_PREFIX = r"(?:faze|face|phase|fase|fays|faiz|phrase)"
ALIASES = {
    "FaZeGavin": re.compile(rf"\b(?:{_PREFIX}[\s,.\-]*)?gav[iey]n\b", re.I),
    "FaZeNeville": re.compile(rf"\b(?:{_PREFIX}[\s,.\-]*)?nev(?:i|e)l(?:l|le|e)?\b", re.I),
}


def find_names(text: str) -> dict[str, int]:
    """Count canonical-name hits (a bare first name counts; the FaZe prefix is optional)."""
    return {canon: len(rx.findall(text or "")) for canon, rx in ALIASES.items()}
