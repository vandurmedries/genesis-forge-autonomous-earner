"""Public website technology, contact, and buyer-signal scanner."""

from __future__ import annotations

import ipaddress
import re
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "capi2-website-buyer-signal-scanner/1.0 (+public-data-only)"
MAX_BYTES = 750_000
MAX_REDIRECTS = 3

TECH_SIGNATURES: dict[str, tuple[str, ...]] = {
    "WordPress": ("wp-content", "wp-includes", "wordpress"),
    "Shopify": ("cdn.shopify.com", "shopify.theme", "myshopify.com"),
    "WooCommerce": ("woocommerce", "wc-block", "wc-ajax"),
    "Wix": ("wixstatic.com", "wix.com/website-builder"),
    "Squarespace": ("static1.squarespace.com", "squarespace-cdn.com"),
    "Webflow": ("webflow.js", "webflow.css", "data-wf-page"),
    "Next.js": ("/_next/", "__next_data__", "next-route-announcer"),
    "React": ("react-root", "data-reactroot", "react-dom"),
    "Vue.js": ("data-v-", "vue.js", "vue.min.js"),
    "Angular": ("ng-version", "angular.min.js", "angular.js"),
    "Google Analytics": ("googletagmanager.com/gtag", "google-analytics.com", "gtag("),
    "Google Tag Manager": ("googletagmanager.com/gtm.js", "gtm-"),
    "Meta Pixel": ("connect.facebook.net/en_us/fbevents.js", "fbq("),
    "HubSpot": ("js.hs-scripts.com", "hubspotutk", "hs-analytics.net"),
    "Intercom": ("widget.intercom.io", "intercomsettings"),
    "Stripe": ("js.stripe.com", "stripe.js"),
    "Cloudflare": ("cdn-cgi/", "cloudflare"),
    "Bootstrap": ("bootstrap.min.css", "bootstrap.min.js", "bootstrap.css"),
    "Tailwind CSS": ("tailwindcss", "tailwind.min.css"),
}

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s()./-]{7,}\d)")
SOCIAL_HOSTS = {
    "linkedin.com": "linkedin",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "x.com": "x",
    "twitter.com": "x",
    "youtube.com": "youtube",
    "tiktok.com": "tiktok",
}


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("empty_url")
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid_public_http_url")
    return value


def validate_public_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid_public_http_url")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError("domain_does_not_resolve") from exc
    for entry in addresses:
        if not ipaddress.ip_address(entry[4][0]).is_global:
            raise ValueError("private_or_reserved_target_blocked")


def fetch_public_html(value: str) -> dict[str, Any]:
    requested_url = normalize_url(value)
    current = requested_url
    for _ in range(MAX_REDIRECTS + 1):
        validate_public_url(current)
        try:
            response = requests.get(
                current,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2"},
                timeout=(5, 15),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise ValueError(f"fetch_failed:{exc.__class__.__name__}") from exc
        if 300 <= response.status_code < 400:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise ValueError("redirect_without_location")
            current = urljoin(current, location)
            continue
        raw = bytearray()
        try:
            for chunk in response.iter_content(65_536):
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    raise ValueError("response_too_large")
        finally:
            response.close()
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and not bytes(raw).lstrip().startswith(b"<"):
            raise ValueError("target_is_not_html")
        return {
            "requested_url": requested_url,
            "final_url": current,
            "status_code": response.status_code,
            "headers": {k.lower(): v for k, v in response.headers.items()},
            "html": bytes(raw).decode(response.encoding or "utf-8", errors="replace"),
        }
    raise ValueError("too_many_redirects")


def _unique(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))[:limit]


def scan_website(value: str, include_contacts: bool = True) -> dict[str, Any]:
    fetched = fetch_public_html(value)
    html = fetched["html"]
    lowered = html.lower()
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    technologies = sorted(name for name, needles in TECH_SIGNATURES.items() if any(n in lowered for n in needles))

    generator = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
    if generator and generator.get("content"):
        technologies.append(str(generator["content"]).strip()[:100])
    server = fetched["headers"].get("server")
    powered_by = fetched["headers"].get("x-powered-by")

    emails: list[str] = []
    phones: list[str] = []
    socials: dict[str, str] = {}
    contact_pages: list[str] = []
    if include_contacts:
        emails.extend(EMAIL_RE.findall(text + " " + html))
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            absolute = urljoin(fetched["final_url"], href)
            if href.lower().startswith("mailto:"):
                emails.append(href[7:].split("?", 1)[0])
            elif href.lower().startswith("tel:"):
                phones.append(href[4:].split("?", 1)[0])
            host = (urlparse(absolute).hostname or "").lower().removeprefix("www.")
            for social_host, label in SOCIAL_HOSTS.items():
                if host == social_host or host.endswith(f".{social_host}"):
                    socials.setdefault(label, absolute)
            anchor_text = anchor.get_text(" ", strip=True).lower()
            if any(term in anchor_text or term in href.lower() for term in ("contact", "about", "support", "get-in-touch")):
                contact_pages.append(absolute)
        phones.extend(PHONE_RE.findall(text))

    headers = fetched["headers"]
    signals: list[dict[str, str]] = []
    if fetched["final_url"].startswith("http://"):
        signals.append({"signal": "no_https", "opportunity": "HTTPS and trust upgrade"})
    if "Google Analytics" not in technologies and "Google Tag Manager" not in technologies:
        signals.append({"signal": "analytics_not_detected", "opportunity": "Analytics implementation"})
    if not headers.get("content-security-policy"):
        signals.append({"signal": "csp_not_detected", "opportunity": "Security-header hardening"})
    if not headers.get("strict-transport-security") and fetched["final_url"].startswith("https://"):
        signals.append({"signal": "hsts_not_detected", "opportunity": "HTTPS policy hardening"})
    if not soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}):
        signals.append({"signal": "mobile_viewport_not_detected", "opportunity": "Mobile usability review"})
    if "WordPress" in technologies:
        signals.append({"signal": "wordpress_detected", "opportunity": "WordPress maintenance or optimization"})

    title = soup.title.get_text(" ", strip=True)[:300] if soup.title else None
    description_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description = str(description_tag.get("content", "")).strip()[:500] if description_tag else None
    return {
        "input": value,
        "url": fetched["final_url"],
        "domain": urlparse(fetched["final_url"]).hostname,
        "status_code": fetched["status_code"],
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "page": {"title": title, "description": description},
        "technologies": _unique(technologies, 50),
        "infrastructure": {"server": server, "powered_by": powered_by},
        "contacts": {
            "emails": _unique([email.lower() for email in emails if not email.lower().endswith((".png", ".jpg", ".svg"))], 20),
            "phones": _unique(phones, 20),
            "socials": socials,
            "contact_pages": _unique(contact_pages, 10),
        },
        "buyer_signals": signals,
        "summary": f"Detected {len(set(technologies))} technologies and {len(signals)} actionable buyer signals.",
        "data_scope": "Public homepage HTML and response headers only",
    }
