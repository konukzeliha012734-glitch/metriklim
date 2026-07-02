"""Climate Engine connection configuration.

Live retrieval is deliberately gated behind a user-provided API key. Endpoint
payloads will be added product-by-product so scientific variable names, units
and reductions remain explicit and auditable.
"""

from __future__ import annotations

import os


def api_key_available() -> bool:
    return bool(os.getenv("CLIMATE_ENGINE_API_KEY"))


def connection_label() -> str:
    return "Bağlı" if api_key_available() else "API anahtarı bekleniyor"

