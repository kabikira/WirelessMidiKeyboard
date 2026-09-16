"""Use under config/offline.sb. Does not modify Wi-Fi or system settings."""
import socket
import subprocess
import sys
from app.settings import ROOT, write_json

results = {}
for host, port in [("1.1.1.1", 443), ("8.8.8.8", 53)]:
    with socket.socket() as s:
        s.settimeout(2)
        try:
            s.connect((host, port))
        except PermissionError:
            results[f"blocked_{host}"] = True
        except OSError as exc:
            results[f"blocked_{host}"] = {"inconclusive": str(exc)}
        else:
            raise AssertionError("OS sandbox failed to block internet")
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    s.listen()
    with socket.socket() as client:
        client.connect(s.getsockname())
        server, address = s.accept()
        server.close()
        results["loopback_allowed"] = True
child = subprocess.run(["/usr/bin/curl", "--noproxy", "*", "--connect-timeout", "2", "https://1.1.1.1/"], capture_output=True, text=True)
results["native_child_blocked"] = child.returncode != 0
results["native_child_message"] = child.stderr[-500:]
assert all(v is True for k, v in results.items() if k != "native_child_message"), results
write_json(ROOT / "evaluations/os-offline.json", results)
print(results)
