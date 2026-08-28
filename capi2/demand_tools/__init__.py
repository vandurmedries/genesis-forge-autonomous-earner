"""Runtime bootstrap for capi2 demand tools.

The demand-tools service imports this package before ``app``. Load the scoped
x402 runtime patch here so conversion metadata and official settlement hooks are
installed only for this service, without changing other capi2 applications.
"""
from importlib import import_module

_runtime_patch = import_module("capi2.demand_tools.runtime_patch.usercustomize")
