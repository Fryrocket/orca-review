import argparse
import os

from .evidence import EvidenceStore
from .control_plane import ControlPlane
from .auth import load_identity_authenticator
from .crucible import current_crucible_acceptance
from .runtime import ModelRuntimeGateway
from .inventory import InventoryProvider
from .web import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="ORCA policy-first control plane")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--database", default="orca-events.db")
    parser.add_argument(
        "--identity-token-file",
        default=os.environ.get("ORCA_IDENTITY_TOKEN_FILE"),
        help="owner-only JSON mapping of registered identities to bootstrap tokens",
    )
    args = parser.parse_args()
    identity_authenticator = (
        load_identity_authenticator(args.identity_token_file)
        if args.identity_token_file else None
    )
    enabled_services = {
        value.strip() for value in os.environ.get(
            "ORCA_ENABLED_MODEL_SERVICES", "").split(",") if value.strip()
    }
    if not current_crucible_acceptance()["activation_ready"]:
        enabled_services.discard("forge_deepseek")
    runtime_gateway = ModelRuntimeGateway(enabled_services) if enabled_services else None
    inventory_key = os.environ.get("ORCA_INVENTORY_SSH_KEY")
    inventory_known_hosts = os.environ.get("ORCA_INVENTORY_KNOWN_HOSTS")
    inventory_provider = (
        InventoryProvider(
            key_file=inventory_key,
            known_hosts_file=inventory_known_hosts,
        )
        if inventory_key and inventory_known_hosts else None
    )
    serve(ControlPlane(EvidenceStore(args.database)), host=args.host, port=args.port,
          operator_token=os.environ.get("ORCA_OPERATOR_TOKEN"),
          identity_tokens=identity_authenticator, runtime_gateway=runtime_gateway,
          inventory_provider=inventory_provider)


if __name__ == "__main__":
    main()
