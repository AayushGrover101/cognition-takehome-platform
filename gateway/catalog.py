"""Export what apps may use, for the apps repo's publish checks and for Devin.

    python3 -m gateway.catalog > ../cognition-takehome-apps/platform/catalog.json
"""
import json

from . import config, connectors


def catalog():
    return {
        "roles": dict(config.ROLES),
        "admin_roles": config.admin_roles(),
        "audit_retention_days": dict(zip(("minimum", "default"), config.retention_policy())),
        "connectors": {name: {"group": config.connector_group(name)} for name in connectors.connectors()},
        "tools": {t.name: {"connector": t.connector, "kind": t.kind, "description": t.description,
                           "inputs": t.inputs, "returns": t.returns} for t in connectors.TOOLS.values()},
    }


if __name__ == "__main__":
    print(json.dumps(catalog(), indent=2, sort_keys=True))
