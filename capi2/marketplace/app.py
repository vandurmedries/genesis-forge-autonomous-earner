"""Marketplace application with the AckMint paid delivery layer installed."""

from . import legacy_app as marketplace
from .legacy_app import app
from capi2.ackmint.integration import install

install(app, marketplace)
