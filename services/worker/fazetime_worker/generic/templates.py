"""GENERIC_BINARY_V1 catalogue (CONTRACTS §9.19): four kinds, every market term rendered by code.

The model only picks a kind and fills slots; this module validates the slots against the §9.19 table and renders
the question, the side-keyed predicates and the cancellation conditions. Labels are always ``Yes``/``No``.
The SAY_PHRASE question states its own window (coordinator ruling 2026-11-15: viewers see only the question).
"""
from __future__ import annotations

import math
import re
import uuid

TEMPLATE_ID = "GENERIC_BINARY_V1"
SPEC_VERSION = "gen-1"
PROPOSER_PROMPT_VERSION = "generic-proposer-1.0"
RESOLVER_PROMPT_VERSION = "generic-resolver-1.0"
KINDS = ("EPISODE_OUTCOME", "END_VALUE_AT_LEAST", "SAY_PHRASE", "DURATION_OVER")
VISUAL_KINDS = ("EPISODE_OUTCOME", "END_VALUE_AT_LEAST")
WIN_VERBS = {"win": "wins", "clear": "clears", "complete": "completes", "beat": "beats", "survive": "survives",
             "finish": "finishes"}
PARAM_KEYS = {"EPISODE_OUTCOME": {"win_verb"}, "END_VALUE_AT_LEAST": {"label", "threshold"},
              "SAY_PHRASE": {"phrase"}, "DURATION_OVER": {"duration_s"}}
TEXT_MAX = 200  # question and predicates (API Text200)
CUE_MAX = 160
PHRASE_MAX_CHARS = 32
_PHRASE = re.compile(r"[a-z']+(?: [a-z']+){0,2}")
# phrases nobody can bet on fairly (always or never said, or too short to match reliably)
_FUNCTION_WORDS = {"a", "an", "the", "and", "or", "but", "so", "to", "of", "in", "on", "at", "it", "is", "i", "you",
                   "we", "he", "she", "they", "me", "my", "uh", "um", "oh", "yeah", "yes", "no", "okay", "ok", "like",
                   "just", "that", "this", "what", "go", "get", "got", "do", "be", "was", "are", "im", "i'm"}


def clean_phrase(raw) -> str:
    return " ".join(re.findall(r"[a-z']+", str(raw or "").lower()))


def fmt_number(x: float) -> str:
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.2f}".rstrip("0").rstrip(".")


def fmt_duration(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def validate_params(kind: str, params: dict) -> str | None:
    """§9.19 table: exactly the keys of ``kind`` with valid values. Returns a local reject code or None."""
    if kind not in KINDS:
        return "BAD_KIND"
    if not isinstance(params, dict) or set(params) != PARAM_KEYS[kind]:
        return "BAD_PARAMS"
    if kind == "EPISODE_OUTCOME":
        return None if params["win_verb"] in WIN_VERBS else "BAD_WIN_VERB"
    if kind == "END_VALUE_AT_LEAST":
        lab, thr = params["label"], params["threshold"]
        if not isinstance(lab, str) or not 1 <= len(lab) <= 40 or lab != lab.strip():
            return "BAD_LABEL"
        if isinstance(thr, bool) or not isinstance(thr, (int, float)) or not math.isfinite(thr) or thr == 0:
            return "BAD_THRESHOLD"
        return None
    if kind == "SAY_PHRASE":
        ph = params["phrase"]
        if not isinstance(ph, str) or not _PHRASE.fullmatch(ph) or len(ph) > PHRASE_MAX_CHARS:
            return "BAD_PHRASE"
        if not any(len(w.strip("'")) >= 3 and w not in _FUNCTION_WORDS for w in ph.split()):
            return "BAD_PHRASE"
        return None
    d = params["duration_s"]
    if isinstance(d, bool) or not isinstance(d, int) or not 30 <= d <= 3600:
        return "BAD_DURATION"
    return None


def render(kind: str, unit: str, params: dict) -> tuple[str, str, str]:
    """(question, YES predicate, NO predicate), from the kind and validated params only."""
    if kind == "EPISODE_OUTCOME":
        verb = params["win_verb"]
        return (f"Will the streamer {verb} this {unit}?",
                f"YES if the {unit} in progress when betting opened ends with a visible result showing the "
                f"streamer {WIN_VERBS[verb]} it.",
                "NO if it ends with a visible result showing the streamer does not.")
    if kind == "END_VALUE_AT_LEAST":
        lab, thr = params["label"], fmt_number(params["threshold"])
        return (f"Will {lab} be at least {thr} when this {unit} ends?",
                f"YES if the last clear on-screen reading of '{lab}' when the {unit} ends is {thr} or more.",
                f"NO if that reading is below {thr}.")
    if kind == "SAY_PHRASE":
        ph = params["phrase"]
        return (f'Will "{ph}" be heard on stream after betting closes, before this {unit} ends?',
                f'YES if "{ph}" (plural or possessive forms count) is heard on stream, in any voice, after betting '
                f"closes and before the {unit} ends. The streamer can influence this bet.",
                f"NO if the {unit} ends without it, with the stream audio covered throughout.")
    if kind == "DURATION_OVER":
        d = int(params["duration_s"])
        return (f"Will this {unit} last longer than {fmt_duration(d)}?",
                f"YES if the {unit} ends more than {d} s after it started on stream.",
                "NO if it ends sooner.")
    raise ValueError(kind)


def cancellation(kind: str, unit: str, margin_s: int, band_s: int) -> list[str]:
    out = [f"The {unit} is abandoned or restarted, or its result is not clearly shown",
           "No clear result on stream before the resolve deadline",
           f"The deciding moment comes before betting closes or within {margin_s} s after",
           "The evidence is unclear, or the two independent reads disagree",
           "Stream gap or source epoch change before the result (SOURCE_GAP)"]
    if kind == "END_VALUE_AT_LEAST":
        out.append("The final value is within one display unit of the line")
    if kind == "DURATION_OVER":
        out.append(f"The {unit} ends within {band_s} s of the line, or its end is not shown as a result")
    if kind == "SAY_PHRASE":
        out.append("The transcript has a gap or the phrase is heard right at the window's edge")
    return out


def fingerprint(source_epoch: str, episode_start_media_ms: int, kind: str) -> str:
    return f"gen:{source_epoch}:{int(episode_start_media_ms)}:{kind.lower()}"


def generic_object(kind: str, unit: str, params: dict, episode_start_media_ms: int, success_cue: str,
                   failure_cue: str) -> dict:
    return {"spec_version": SPEC_VERSION, "kind": kind, "unit": unit[:20], "params": dict(params),
            "episode_start_media_ms": int(episode_start_media_ms), "success_cue": sanitize(success_cue, CUE_MAX),
            "failure_cue": sanitize(failure_cue, CUE_MAX)}


def sanitize(text, limit: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or "")).strip()[:limit]


def make_candidate(*, source_epoch: str, kind: str, unit: str, params: dict, episode_start_media_ms: int,
                   success_cue: str, failure_cue: str, evidence_ids: list, announced_at_media_ms: int,
                   close_in_s: int, resolve_in_s: int, margin_s: int, band_s: int, rationale: str,
                   model: str) -> tuple[str | None, dict | None]:
    """(reject code, None) or (None, candidate) in the exact §9.19 shape."""
    code = validate_params(kind, params)
    if code:
        return code, None
    if not 1 <= len(unit) <= 20:
        return "BAD_UNIT", None
    question, yes_p, no_p = render(kind, unit, params)
    if max(len(question), len(yes_p), len(no_p)) > TEXT_MAX or yes_p.lower() == no_p.lower():
        return "TERMS_TOO_LONG", None
    if not 1 <= len(evidence_ids) <= 20:
        return "NO_FRESH_EVIDENCE", None
    return None, {
        "candidate_id": str(uuid.uuid4()), "template_id": TEMPLATE_ID,
        "episode_fingerprint": fingerprint(source_epoch, episode_start_media_ms, kind),
        "question": question, "yes": {"label": "Yes", "predicate": yes_p}, "no": {"label": "No", "predicate": no_p},
        "subjects": [], "evidence_ids": list(evidence_ids), "announced_at_media_ms": int(announced_at_media_ms),
        "suggested_close_in_s": int(close_in_s), "suggested_resolve_in_s": int(resolve_in_s),
        "cancellation_conditions": cancellation(kind, unit, margin_s, band_s),
        "rationale": sanitize(rationale, 300), "model": model[:64], "prompt_version": PROPOSER_PROMPT_VERSION,
        "generic": generic_object(kind, unit, params, episode_start_media_ms, success_cue, failure_cue),
    }


def parse_generic(g) -> tuple[str | None, dict | None]:
    """Validate a stored ``generic`` object from the worker market view (untrusted transport data)."""
    if not isinstance(g, dict) or g.get("spec_version") != SPEC_VERSION:
        return "BAD_SPEC", None
    kind, params = g.get("kind"), g.get("params")
    code = validate_params(kind, params)
    start = g.get("episode_start_media_ms")
    if code or isinstance(start, bool) or not isinstance(start, int) or start < 0:
        return code or "BAD_SPEC", None
    unit = g.get("unit") if isinstance(g.get("unit"), str) and 1 <= len(g.get("unit")) <= 20 else "game"
    return None, {"kind": kind, "params": params, "unit": unit, "episode_start_media_ms": start,
                  "success_cue": sanitize(g.get("success_cue"), CUE_MAX),
                  "failure_cue": sanitize(g.get("failure_cue"), CUE_MAX)}
