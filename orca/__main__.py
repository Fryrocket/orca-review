import argparse
import os

from .evidence import EvidenceStore
from .control_plane import ControlPlane
from .auth import load_identity_authenticator
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
    serve(ControlPlane(EvidenceStore(args.database)), host=args.host, port=args.port,
          operator_token=os.environ.get("ORCA_OPERATOR_TOKEN"),
          identity_tokens=identity_authenticator)


if __name__ == "__main__":
    main()
