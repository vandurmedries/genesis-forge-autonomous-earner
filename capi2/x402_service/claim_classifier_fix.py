"""Deterministic classifier hardening for clear paraphrased contradictions.

Installed by bootstrap.py or package initialization after the canonical app module
is imported. This changes only capi2's own claim classification function and
dry-run regression fixtures; it does not patch x402 or settlement internals.
"""
from __future__ import annotations

import re
from typing import Any

CLASSIFIER_REVISION = "paraphrase-contradiction-v1"

MATCH_STOPWORDS = {
    "about", "against", "claim", "claims", "public", "source", "states", "state",
    "that", "their", "there", "these", "this", "vendor", "with", "the", "and",
    "for", "from", "into", "onto", "than", "then", "they", "them", "its", "our",
    "your", "you", "are", "was", "were", "will", "would", "could", "should",
    "have", "has", "had", "being", "been",
}
NEGATORS = {
    "not", "no", "never", "without", "cannot", "cant", "isnt", "doesnt",
    "lacks", "lacking",
}
GENERIC_ENTITY_TERMS = {"api", "service", "vendor", "customer", "account"}
GENERIC_PREDICATES = {
    "support", "allow", "offer", "provide", "enable", "include", "available",
    "require", "encrypt", "store", "use",
}
POSITIVE_CUES = {
    "support", "allow", "offer", "provide", "enable", "include", "available",
    "encrypt", "require", "public", "free", "active",
}
NEGATIVE_CUES = {
    "unavailable", "unsupported", "disabled", "blocked", "prohibited", "forbidden",
    "excluded", "missing", "absent", "plaintext", "unencrypted", "private",
    "internal", "optional", "restricted", "denied",
}
CANONICAL = {
    "supports": "support", "supported": "support", "supporting": "support",
    "allows": "allow", "allowed": "allow", "allowing": "allow",
    "offers": "offer", "offered": "offer", "offering": "offer",
    "provides": "provide", "provided": "provide", "providing": "provide",
    "enables": "enable", "enabled": "enable", "enabling": "enable",
    "includes": "include", "included": "include", "including": "include",
    "availability": "available",
    "requires": "require", "required": "require", "requiring": "require",
    "mandatory": "require",
    "encrypts": "encrypt", "encrypted": "encrypt", "encryption": "encrypt",
    "encrypting": "encrypt",
    "stores": "store", "stored": "store", "storing": "store",
    "exports": "export", "exported": "export", "exporting": "export",
    "accounts": "account", "customers": "customer", "services": "service",
    "reports": "report", "policies": "policy",
    "uses": "use", "used": "use", "using": "use",
}


def _words(text: str) -> list[str]:
    return [
        CANONICAL.get(token.lower(), token.lower())
        for token in re.findall(r"[A-Za-z0-9]+", text)
    ]


def _semantic_tokens(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z0-9]+", text)
    acronyms = {token.lower() for token in raw if len(token) >= 2 and token.isupper()}
    return {
        token
        for token in _words(text)
        if (len(token) >= 4 or token in acronyms)
        and token not in MATCH_STOPWORDS
        and token not in NEGATORS
    }


def _focus_tokens(text: str) -> set[str]:
    tokens = _semantic_tokens(text)
    focus = tokens - GENERIC_ENTITY_TERMS - GENERIC_PREDICATES
    return focus or tokens


def _sentence_chunks(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [
        re.sub(r"\s+", " ", chunk).strip()
        for chunk in chunks
        if len(chunk.strip()) >= 8
    ]


def _rank(claim: str, evidence_text: str) -> tuple[set[str], list[tuple[float, str]]]:
    focus = _focus_tokens(claim)
    if not focus:
        return set(), []
    ranked: list[tuple[float, str]] = []
    for chunk in _sentence_chunks(evidence_text):
        tokens = _semantic_tokens(chunk)
        overlap = len(focus & tokens)
        if overlap:
            ranked.append((overlap / max(len(focus), 1), chunk[:420]))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return focus, ranked


def _semantic_polarity(text: str, focus: set[str]) -> int:
    """Return +1 positive, -1 negative, 0 unknown/ambiguous near claim focus."""
    if not focus:
        return 0
    words = _words(text)
    focus_indexes = [index for index, word in enumerate(words) if word in focus]
    if not focus_indexes:
        return 0

    def near_focus(index: int, radius: int = 6) -> bool:
        return any(abs(index - focus_index) <= radius for focus_index in focus_indexes)

    negative = False
    positive = False

    for index, word in enumerate(words):
        if word in NEGATIVE_CUES and near_focus(index):
            # A double-negative lexical construction is ambiguous; do not force polarity.
            if not any(token in NEGATORS for token in words[max(0, index - 3):index]):
                negative = True

        if word in POSITIVE_CUES and near_focus(index):
            if any(token in NEGATORS for token in words[max(0, index - 3):index]):
                negative = True
            else:
                positive = True

    for focus_index in focus_indexes:
        if any(token in NEGATORS for token in words[max(0, focus_index - 3):focus_index]):
            negative = True

    if negative and not positive:
        return -1
    if positive and not negative:
        return 1
    return 0


def install(app_module: Any) -> None:
    """Install the hardened classifier and deterministic public regression fixtures."""
    app_module.DRY_RUN_FIXTURES.update(
        {
            "paraphrased_unavailable_contradiction": {
                "claim": "The API supports single sign-on (SSO).",
                "evidence_text": (
                    "Single sign-on (SSO) is unavailable for this API; "
                    "customers must use password authentication instead."
                ),
                "expected_verification_status": "contradicted",
                "purpose": (
                    "Regression for a clear paraphrased capability contradiction where "
                    "the evidence uses unavailable instead of explicit 'does not support'."
                ),
            },
            "paraphrased_disabled_contradiction": {
                "claim": "Enterprise accounts allow data exports.",
                "evidence_text": "Data exports are disabled for enterprise accounts.",
                "expected_verification_status": "contradicted",
                "purpose": (
                    "Regression for a capability contradiction expressed as disabled "
                    "rather than explicit negation."
                ),
            },
            "paraphrased_plaintext_contradiction": {
                "claim": "Customer data is encrypted at rest.",
                "evidence_text": "Customer data at rest is stored in plaintext.",
                "expected_verification_status": "contradicted",
                "purpose": (
                    "Regression for a security contradiction expressed through an "
                    "opposite state instead of the word 'not'."
                ),
            },
        }
    )

    def _classify_claim(claim: str, evidence_text: str) -> dict:
        focus, ranked = _rank(claim, evidence_text)
        top = ranked[:3]
        best = top[0][0] if top else 0.0
        best_text = top[0][1] if top else ""

        claim_terms = app_module._tokens(claim)
        best_terms = app_module._tokens(best_text) if best_text else set()
        shared_terms = claim_terms & best_terms
        claim_direct_negated = app_module._relevant_negation(claim, claim_terms)
        evidence_direct_negated = (
            app_module._relevant_negation(best_text, shared_terms) if best_text else False
        )

        claim_polarity = _semantic_polarity(claim, focus)
        evidence_polarity = _semantic_polarity(best_text, focus) if best_text else 0

        if best >= 0.55 and claim_polarity and evidence_polarity:
            if claim_polarity == evidence_polarity:
                verification_status = "supported"
                verdict = "SUPPORTED_BY_SUPPLIED_SOURCE"
            else:
                verification_status = "contradicted"
                verdict = "CONTRADICTED_BY_SUPPLIED_SOURCE"
        elif best >= 0.55 and claim_direct_negated != evidence_direct_negated:
            verification_status = "contradicted"
            verdict = "CONTRADICTED_BY_SUPPLIED_SOURCE"
        elif best >= 0.60 and claim_direct_negated == evidence_direct_negated:
            verification_status = "supported"
            verdict = "SUPPORTED_BY_SUPPLIED_SOURCE"
        else:
            verification_status = "uncertain"
            verdict = "NOT_CONFIRMED_OR_AMBIGUOUS"

        if verification_status == "contradicted":
            confidence = min(0.92, round(0.34 + best * 0.58, 3))
        else:
            confidence = min(0.95, round(0.25 + best * 0.70, 3))

        evidence = [{"text": text, "score": round(score, 3)} for score, text in top]
        return {
            "verification_status": verification_status,
            "verification_result": verification_status,
            "verdict": verdict,
            "confidence": confidence,
            "evidence_summary": (
                best_text
                or "No sufficiently overlapping public statement was found on the supplied source."
            ),
            "evidence": evidence,
            "debug": {
                "best_overlap": round(best, 3),
                "claim_negated_near_relevant_terms": claim_direct_negated,
                "evidence_negated_near_relevant_terms": evidence_direct_negated,
                "shared_terms": sorted(shared_terms),
                "semantic_focus_terms": sorted(focus),
                "claim_semantic_polarity": claim_polarity,
                "evidence_semantic_polarity": evidence_polarity,
                "classifier_revision": CLASSIFIER_REVISION,
            },
        }

    app_module._classify_claim = _classify_claim

    # Fail startup if a regression fixture drifts. This protects both the free
    # sandbox and the paid route because they share the same classifier.
    failures = []
    for fixture_id, fixture in app_module.DRY_RUN_FIXTURES.items():
        expected = fixture.get("expected_verification_status")
        if not expected:
            continue
        result = _classify_claim(fixture["claim"], fixture["evidence_text"])
        if result["verification_status"] != expected:
            failures.append(
                f"{fixture_id}:{result['verification_status']}!=expected:{expected}"
            )
    if failures:
        raise RuntimeError("claim_classifier_regression_failed:" + ",".join(failures))
