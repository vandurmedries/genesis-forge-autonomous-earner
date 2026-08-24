"""capi2 claim-verdict regression guard and free deterministic sandbox.

Loaded automatically by Python after sitecustomize.  The patch is deliberately
narrow: it only touches the capi2 Claim Verify FastAPI app and leaves all other
services unchanged.
"""
from __future__ import annotations

import functools
import re
from typing import Any

PROTOCOL = "capi2.claim_verify/1.5.0"
_STOPWORDS = {
    "about", "after", "again", "against", "also", "been", "being", "claim",
    "claims", "from", "have", "into", "more", "that", "their", "there",
    "these", "they", "this", "vendor", "with", "would", "states", "state",
    "says", "said",
}
_NEGATORS = {"not", "no", "never", "without", "cannot", "lacks", "lack", "lacking"}


def _normalise(text: str) -> str:
    value = str(text or "").lower()
    replacements = {
        "isn't": "is not", "aren't": "are not", "wasn't": "was not",
        "weren't": "were not", "doesn't": "does not", "don't": "do not",
        "didn't": "did not", "can't": "cannot", "cannot": "cannot",
        "won't": "will not", "hasn't": "has not", "haven't": "have not",
        "hadn't": "had not",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _tokens(text: str) -> list[str]:
    return [token for token in _normalise(text).split() if len(token) >= 3]


def _claim_terms(claim: str) -> set[str]:
    return {token for token in _tokens(claim) if token not in _STOPWORDS}


def _negated_terms(text: str, relevant: set[str], window: int = 4) -> set[str]:
    tokens = _tokens(text)
    out: set[str] = set()
    for index, token in enumerate(tokens):
        if token not in _NEGATORS:
            continue
        for candidate in tokens[index + 1:index + 1 + window]:
            if candidate in relevant:
                out.add(candidate)
    return out


def _classify(claim: str, evidence_text: str, score: float) -> tuple[str, str, str]:
    """Classify using claim-term negation scope, not any stray 'not' in a sentence."""
    terms = _claim_terms(claim)
    if not terms or score < 0.45:
        return "uncertain", "NOT_CONFIRMED_OR_AMBIGUOUS", "insufficient_term_overlap"

    claim_negated = _negated_terms(claim, terms)
    evidence_negated = _negated_terms(evidence_text, terms)
    claim_is_negative = bool(claim_negated)
    evidence_is_negative = bool(evidence_negated)

    if claim_is_negative != evidence_is_negative:
        # A contradiction must negate at least one actual claim term. A stray
        # negator elsewhere in the evidence is never enough.
        opposing_terms = evidence_negated if evidence_is_negative else claim_negated
        if opposing_terms and score >= 0.55:
            return "contradicted", "CONTRADICTED_BY_SUPPLIED_SOURCE", "explicit_claim_term_polarity_mismatch"
        return "uncertain", "NOT_CONFIRMED_OR_AMBIGUOUS", "polarity_mismatch_not_explicit"

    if score >= 0.55:
        return "supported", "SUPPORTED_BY_SUPPLIED_SOURCE", "claim_term_polarity_aligned"
    return "uncertain", "NOT_CONFIRMED_OR_AMBIGUOUS", "insufficient_term_overlap"


def _sentence_chunks(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", str(text or ""))
        if len(part.strip()) >= 15
    ]


def _evaluate_inline(claim: str, source_text: str) -> dict[str, Any]:
    terms = _claim_terms(claim)
    ranked: list[tuple[float, str]] = []
    for chunk in _sentence_chunks(source_text):
        chunk_terms = set(_tokens(chunk))
        overlap = len(terms & chunk_terms)
        if overlap:
            ranked.append((overlap / max(len(terms), 1), chunk[:700]))
    ranked.sort(key=lambda row: row[0], reverse=True)
    top = ranked[:3]
    best = top[0][0] if top else 0.0
    best_text = top[0][1] if top else ""
    status, verdict, basis = _classify(claim, best_text, best)
    confidence = (
        min(0.93, round(0.30 + best * 0.63, 3))
        if status in {"supported", "contradicted"}
        else min(0.55, round(0.20 + best * 0.45, 3))
    )
    return {
        "protocol": PROTOCOL,
        "claim_id": None,
        "vendor_name": None,
        "vendor_url": "sandbox://inline-text",
        "claim": claim,
        "verification_status": status,
        "verification_result": status,
        "verdict": verdict,
        "confidence": confidence,
        "evidence_summary": best_text or "No sufficiently overlapping statement was found in the supplied sandbox text.",
        "evidence_source_urls": [],
        "evidence": [{"text": text, "score": round(score, 3)} for score, text in top],
        "decision_basis": basis,
        "sandbox": True,
        "payments_attempted": False,
        "caveats": [
            "Free deterministic regression sandbox; it accepts inline text and does not fetch a URL.",
            "Production verification still checks only the supplied public source URL.",
            "Consequential decisions require independent review.",
        ],
    }


def _correct_paid_response(result: Any) -> Any:
    """Post-process only the paid route's verdict fields using scoped polarity."""
    try:
        get = result.get if isinstance(result, dict) else lambda key, default=None: getattr(result, key, default)
        claim = str(get("claim", "") or "")
        evidence = get("evidence", []) or []
        first = evidence[0] if evidence else None
        if isinstance(first, dict):
            evidence_text = str(first.get("text", "") or "")
            score = float(first.get("score", 0.0) or 0.0)
        else:
            evidence_text = str(getattr(first, "text", "") or "") if first is not None else ""
            score = float(getattr(first, "score", 0.0) or 0.0) if first is not None else 0.0
        status, verdict, basis = _classify(claim, evidence_text, score)

        def set_value(key: str, value: Any) -> None:
            if isinstance(result, dict):
                result[key] = value
            else:
                setattr(result, key, value)

        set_value("protocol", PROTOCOL)
        set_value("verification_status", status)
        set_value("verification_result", status)
        set_value("verdict", verdict)
        confidence = (
            min(0.93, round(0.30 + score * 0.63, 3))
            if status in {"supported", "contradicted"}
            else min(0.55, round(0.20 + score * 0.45, 3))
        )
        set_value("confidence", confidence)
        caveats = list(get("caveats", []) or [])
        marker = f"Verdict polarity checked against claim-term negation scope ({PROTOCOL}; {basis})."
        if marker not in caveats:
            caveats.append(marker)
        set_value("caveats", caveats)
    except Exception as exc:
        print(f"claim-verdict-guard: postprocess error {type(exc).__name__}: {exc}", flush=True)
    return result


def _install() -> None:
    try:
        from fastapi import FastAPI
        from pydantic import BaseModel, Field
    except Exception:
        return

    original_add = FastAPI.add_api_route
    if not getattr(original_add, "_capi2_claim_guard", False):
        def guarded_add(self, path, endpoint, *args, **kwargs):
            if path == "/v1/claim-verify":
                original_endpoint = endpoint

                @functools.wraps(original_endpoint)
                def corrected_endpoint(*call_args, **call_kwargs):
                    return _correct_paid_response(original_endpoint(*call_args, **call_kwargs))

                endpoint = corrected_endpoint
            return original_add(self, path, endpoint, *args, **kwargs)

        guarded_add._capi2_claim_guard = True
        FastAPI.add_api_route = guarded_add

    original_init = FastAPI.__init__
    if getattr(original_init, "_capi2_claim_sandbox", False):
        return

    class SandboxRequest(BaseModel):
        claim: str = Field(min_length=3, max_length=1200)
        source_text: str = Field(min_length=15, max_length=20000)
        case_id: str | None = Field(default=None, max_length=160)

    cases = [
        {
            "case_id": "payapi-1.3.2-positive-support-inversion-class",
            "claim": "Customer data is encrypted at rest.",
            "source_text": "Customer data is encrypted at rest using AES-256. Backups are not stored unencrypted.",
            "expected": "supported",
        },
        {
            "case_id": "explicit-positive-claim-contradiction",
            "claim": "Customer data is encrypted at rest.",
            "source_text": "Customer data is not encrypted at rest.",
            "expected": "contradicted",
        },
        {
            "case_id": "negative-claim-supported",
            "claim": "Customer data is not stored in plaintext.",
            "source_text": "Customer data is not stored in plaintext.",
            "expected": "supported",
        },
    ]

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if "Claim Verify" not in str(getattr(self, "title", "")):
            return

        async def sandbox(payload: SandboxRequest):
            result = _evaluate_inline(payload.claim, payload.source_text)
            result["case_id"] = payload.case_id
            return result

        async def regression_cases():
            evaluated = []
            for case in cases:
                result = _evaluate_inline(case["claim"], case["source_text"])
                evaluated.append({
                    **case,
                    "actual": result["verification_status"],
                    "pass": result["verification_status"] == case["expected"],
                    "verdict": result["verdict"],
                    "decision_basis": result["decision_basis"],
                })
            return {
                "protocol": PROTOCOL,
                "suite": "claim-polarity-regression",
                "all_pass": all(row["pass"] for row in evaluated),
                "cases": evaluated,
            }

        self.add_api_route(
            "/v1/claim-verify/sandbox",
            sandbox,
            methods=["POST"],
            tags=["sandbox", "regression", "fact checking"],
            summary="Free deterministic claim-verdict sandbox",
            description=(
                "Exercise the production verdict-polarity logic with inline text. "
                "No URL is fetched and no payment is attempted."
            ),
        )
        self.add_api_route(
            "/v1/claim-verify/regression-cases",
            regression_cases,
            methods=["GET"],
            tags=["sandbox", "regression"],
            summary="Named verdict-inversion regression cases",
            description="Returns deterministic support/contradiction regression cases and pass/fail status.",
        )
        print("claim-verdict-guard: installed protocol=1.5.0 sandbox=true", flush=True)

    patched_init._capi2_claim_sandbox = True
    FastAPI.__init__ = patched_init


_install()
