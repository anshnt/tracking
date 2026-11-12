"""Which connectors are enabled and the live instances the worker polls.

register_configured() reads env (<NAME>_ENABLED=1 and friends, see each module), builds the enabled
connectors and fills base.EVENT_SOURCES / base.REVOCATION_ADAPTERS. The worker calls it at start;
any process that needs REVOCATION_ADAPTERS (the offboarding API) must call it too.
"""

import httpx

from portal.connectors import base
from portal.connectors.fleet import FleetAdapter
from portal.connectors.gitea import GiteaAdapter
from portal.connectors.guacamole import GuacamoleAdapter
from portal.connectors.http import Cfg
from portal.connectors.keycloak import KeycloakAdapter
from portal.connectors.kimai import KimaiAdapter
from portal.connectors.wazuh import WazuhSource
from portal.connectors.xrdp import XrdpAdapter

FACTORIES = {
    "wazuh": WazuhSource,
    "keycloak": KeycloakAdapter,
    "guacamole": GuacamoleAdapter,
    "gitea": GiteaAdapter,
    "fleet": FleetAdapter,
    "kimai": KimaiAdapter,
    "xrdp": lambda cfg, transport=None: XrdpAdapter(),
}
CONNECTOR_NAMES = tuple(FACTORIES)
NOT_POLLED = frozenset({"xrdp"})  # nothing upstream to poll: operator task only

LIVE: dict[str, object] = {}  # name -> instance (every enabled connector)


def is_enabled(name: str, env: dict | None = None) -> bool:
    return Cfg(name, env).enabled


def register_configured(
    env: dict | None = None, transports: dict[str, httpx.BaseTransport] | None = None
) -> dict[str, object]:
    """(Re)build enabled connectors. `transports` maps name -> httpx transport (tests)."""
    LIVE.clear()
    for name, factory in FACTORIES.items():
        cfg = Cfg(name, env)
        if not cfg.enabled:
            continue
        obj = factory(cfg, transport=(transports or {}).get(name))
        LIVE[name] = obj
        if isinstance(obj, base.EventSource):
            base.register_event_source(obj)
        if isinstance(obj, base.RevocationAdapter):
            base.register_revocation_adapter(obj)
    return LIVE
