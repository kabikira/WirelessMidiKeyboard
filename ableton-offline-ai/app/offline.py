"""Fail closed for Python's internet sockets; OS-level testing also covers native children."""
import ipaddress
import os
import sys

_installed = False


def local_host(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def enable():
    global _installed
    os.environ.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      TRANSFORMERS_OFFLINE="1", DO_NOT_TRACK="1",
                      STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    if _installed:
        return

    def audit(event, args):
        if event == "socket.getaddrinfo" and args[0] and not local_host(args[0]):
            raise PermissionError(f"外部DNSは禁止されています: {args[0]}")
        if event in ("socket.connect", "socket.bind"):
            address = args[1]
            if isinstance(address, tuple) and not local_host(address[0]):
                raise PermissionError(f"外部通信は禁止されています: {address[0]}")
        if event == "socket.sendto":
            address = args[-1]
            if isinstance(address, tuple) and not local_host(address[0]):
                raise PermissionError(f"外部送信は禁止されています: {address[0]}")

    sys.addaudithook(audit)
    _installed = True
