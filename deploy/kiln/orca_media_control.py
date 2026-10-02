#!/usr/bin/env python3
"""Tiny privileged controller for fixed ORCA GPU service transitions."""

from __future__ import annotations

import argparse
import os
import pwd
import socket
import struct
import subprocess
from pathlib import Path


ALLOWED = {
    "start-image": (("start", "orca-comfyui.service"),),
    "stop-image": (
        ("stop", "orca-comfyui.service"),
        ("start", "quench-inference.service"),
    ),
}


def run(socket_path: Path, allowed_user: str) -> None:
    allowed_uid = pwd.getpwnam(allowed_user).pw_uid
    socket_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(socket_path))
        os.chown(socket_path, 0, pwd.getpwnam(allowed_user).pw_gid)
        os.chmod(socket_path, 0o660)
        server.listen(4)
        while True:
            connection, _ = server.accept()
            with connection:
                credentials = connection.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                _pid, uid, _gid = struct.unpack("3i", credentials)
                request = connection.recv(33)
                if uid != allowed_uid or len(request) > 32 or not request.endswith(b"\n"):
                    connection.sendall(b"denied\n")
                    continue
                try:
                    operation = request[:-1].decode("ascii")
                except UnicodeDecodeError:
                    connection.sendall(b"denied\n")
                    continue
                commands = ALLOWED.get(operation)
                if commands is None:
                    connection.sendall(b"denied\n")
                    continue
                try:
                    for verb, unit in commands:
                        subprocess.run(
                            ["/usr/bin/systemctl", verb, unit], check=True,
                            timeout=180)
                except (OSError, subprocess.SubprocessError):
                    connection.sendall(b"failed\n")
                else:
                    connection.sendall(b"ok\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/run/orca-media-control/control.sock")
    parser.add_argument("--allowed-user", default="orca-media")
    args = parser.parse_args()
    run(Path(args.socket), args.allowed_user)


if __name__ == "__main__":
    main()
