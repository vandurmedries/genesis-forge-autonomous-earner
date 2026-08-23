import os
import re
from typing import List

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, Field

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

PAY_TO = os.getenv("CAPI2_PAY_TO", "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a")
NETWORK = os.getenv("CAPI2_X402_NETWORK", "eip155:8453")
FACILITATOR_URL = os.getenv("CAPI2_X402_FACILITATOR", "https://facilitator.payai.network")
PRICE = os.getenv("CAPI2_CLAIM_VERIFY_PRICE", "$0.01")

app = FastAPI(
    title="capi2 Claim Verify",
    version="1.0.0",
    description="Public-evidence vendor claim verification with x402 payment on Base USDC.",
)

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())

routes = {
    "POST /v1/claim-verify": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=PAY_TO,
                price=PRICE,
                network=NETWORK,
            )
        ],
        mime_type="application/json",
        description="Verify one public vendor claim against the supplied public source URL and return machine-readable evidence.",
    )
}

app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


class ClaimVerifyRequest(BaseModel):
    vendor_url: HttpUrl
    claim: str = Field(min_length=3, max_length=1200)


class EvidenceSnippet(BaseModel):
    text: str
    score: float


class ClaimVerifyResponse(BaseModel):
    protocol: str = "capi2.claim_verify/1.0"
    vendor_url: str
    claim: str
    verdict: str
    confidence: float
    evidence: List[EvidenceSnippet]
    caveats: List[str]


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 4
    }


def _sentence_chunks(text: str) -> List[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [re.sub(r"\s+", " ", c).strip() for c in chunks if len(c.strip()) >= 25]


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "capi2-claim-verify",
        "network": NETWORK,
        "price": PRICE,
        "settlement": "USDC on Base",
        "pay_to": PAY_TO,
    }


@app.post("/v1/claim-verify", response_model=ClaimVerifyResponse)
async def claim_verify(payload: ClaimVerifyRequest):
    url = str(payload.vendor_url)
    try:
        response = requests.get(
            url,
            timeout=12,
            allow_redirects=True,
            headers={"User-Agent": "capi2-claim-verify/1.0 (+public-evidence-check)"},
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=422, detail=f"source_fetch_failed: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=422, detail=f"source_http_status:{response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    page_text = soup.get_text(" ", strip=True)
    if len(page_text) < 50:
        raise HTTPException(status_code=422, detail="source_has_insufficient_public_text")

    claim_tokens = _tokens(payload.claim)
    if not claim_tokens:
        raise HTTPException(status_code=422, detail="claim_has_insufficient_terms")

    ranked = []
    for chunk in _sentence_chunks(page_text):
        chunk_tokens = _tokens(chunk)
        if not chunk_tokens:
            continue
        overlap = len(claim_tokens & chunk_tokens)
        score = overlap / max(len(claim_tokens), 1)
        if overlap:
            ranked.append((score, chunk[:420]))

    ranked.sort(key=lambda x: x[0], reverse=True)
    top = ranked[:3]
    best = top[0][0] if top else 0.0

    if best >= 0.60:
        verdict = "SUPPORTED_BY_SUPPLIED_SOURCE"
    elif best >= 0.30:
        verdict = "PARTIALLY_SUPPORTED_OR_AMBIGUOUS"
    else:
        verdict = "NOT_CONFIRMED_BY_SUPPLIED_SOURCE"

    evidence = [EvidenceSnippet(text=text, score=round(score, 3)) for score, text in top]
    confidence = min(0.95, round(0.25 + best * 0.70, 3))

    return ClaimVerifyResponse(
        vendor_url=url,
        claim=payload.claim,
        verdict=verdict,
        confidence=confidence,
        evidence=evidence,
        caveats=[
            "This checks only the supplied public URL and does not certify the vendor.",
            "Absence of evidence on the supplied page is not proof that a claim is false.",
            "Regulated or high-impact decisions require independent review by an appropriately authorized party.",
        ],
    )
