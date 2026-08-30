"""Small CAPI2 AckMint client.

Paid delivery requires an x402-capable session. The ``paid_session`` context
manager follows the current x402 Python client pattern and never logs the key.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Protocol

import requests


DEFAULT_ORIGIN = "https://capi2-agent-marketplace-router.onrender.com"


class SessionLike(Protocol):
    def get(self, url: str, **kwargs: Any) -> requests.Response: ...

    def post(self, url: str, **kwargs: Any) -> requests.Response: ...


@dataclass(slots=True)
class AckMintClient:
    integration_token: str | None = None
    origin: str = DEFAULT_ORIGIN
    session: SessionLike | None = None
    timeout: float = 30.0

    def __post_init__(self) -> None:
        self.origin = self.origin.rstrip("/")
        if not self.origin.startswith("https://"):
            raise ValueError("AckMint origin must use HTTPS")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.session is None:
            self.session = requests.Session()

    def challenge(
        self,
        callback_url: str,
        service_name: str,
        integration_ttl_days: int = 365,
    ) -> dict[str, Any]:
        response = self.session.post(
            f"{self.origin}/v1/ackmint/integrations/challenge",
            json={
                "callback_url": callback_url,
                "service_name": service_name,
                "integration_ttl_days": integration_ttl_days,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def verify_integration(self, challenge_token: str) -> dict[str, Any]:
        response = self.session.post(
            f"{self.origin}/v1/ackmint/integrations/verify",
            json={"challenge_token": challenge_token},
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json()
        token = result.get("integration_token")
        if isinstance(token, str):
            self.integration_token = token
        return result

    def emit(
        self,
        *,
        event_id: str,
        event_type: str,
        payload: Any,
        tier: str = "standard",
        source: str = "urn:capi2:external",
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        if tier not in {"standard", "assured", "critical"}:
            raise ValueError("tier must be standard, assured, or critical")
        if not self.integration_token:
            raise ValueError("integration_token is required for delivery")
        body: dict[str, Any] = {
            "integration_token": self.integration_token,
            "event_id": event_id,
            "event_type": event_type,
            "source": source,
            "payload": payload,
        }
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        response = self.session.post(
            f"{self.origin}/v1/ackmint/relay/{tier}",
            json=body,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json(), response.headers.get("Payment-Response")

    def status(
        self,
        *,
        event_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.integration_token:
            raise ValueError("integration_token is required")
        body: dict[str, Any] = {
            "integration_token": self.integration_token,
            "event_id": event_id,
        }
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        response = self.session.post(
            f"{self.origin}/v1/ackmint/relay/status",
            json=body,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def verify_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.origin}/v1/ackmint/receipts/verify",
            json={"receipt": receipt},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


@contextmanager
def paid_session(
    evm_private_key: str,
    *,
    max_amount_per_payment: str = "$0.25",
) -> Iterator[SessionLike]:
    """Yield a requests-compatible session with automatic x402 payment.

    Install dependencies with:
    ``pip install requests eth-account 'x402[evm]>=2.17,<3'``.
    Keep the private key outside source control and use a low-balance wallet.
    """

    if not evm_private_key:
        raise ValueError("evm_private_key is required")

    from eth_account import Account
    from x402 import x402ClientSync
    from x402.http.clients import x402_requests
    from x402.mechanisms.evm import EthAccountSigner
    from x402.mechanisms.evm.exact.register import (
        register_exact_evm_client,
    )

    account = Account.from_key(evm_private_key)
    payment_client = x402ClientSync().set_spend_controls(
        {"max_amount_per_payment": max_amount_per_payment}
    )
    register_exact_evm_client(
        payment_client,
        EthAccountSigner(account),
    )
    with x402_requests(payment_client) as session:
        yield session
