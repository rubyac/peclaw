"""GitHub Codespaces lifecycle. Uses its forwarded HTTPS URL, not a fabricated public IP."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def public_origin(environment: dict[str, str]) -> str:
    name = environment.get("CODESPACE_NAME", "")
    domain = environment.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,54}[a-z0-9])?", name):
        raise ValueError("Run this startup command inside GitHub Codespaces (CODESPACE_NAME missing)")
    if not re.fullmatch(r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}", domain):
        raise ValueError("Invalid Codespaces forwarding domain")
    return f"https://{name}-3000.{domain}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--print-origin", action="store_true")
    args = parser.parse_args()
    try:
        origin = public_origin(dict(os.environ))
    except ValueError as error:
        parser.error(str(error))
    if args.print_origin:
        print(origin)
        return
    subprocess.run([sys.executable, "scripts/init_env.py"], cwd=ROOT, check=True)
    environment = dict(os.environ, APP_ENV="production", AUTH_COOKIE_SECURE="true",
                       AUTH_ALLOWED_ORIGINS=json.dumps([origin]))
    for attempt in range(60):
        result = subprocess.run(["docker", "info"], cwd=ROOT, env=environment,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            break
        if attempt == 59:
            raise SystemExit("Docker is not ready. Inspect the Docker-in-Docker feature startup.")
        time.sleep(1)
    if args.build_only:
        subprocess.run(["docker", "compose", "build", "api", "web"], cwd=ROOT,
                       env=environment, check=True)
        return
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "180"],
                   cwd=ROOT, env=environment, check=True)
    print(f"PEClaw is ready: {origin}/login")
    print("Use the Ports tab to open port 3000; keep its visibility private for personal trials.")


if __name__ == "__main__":
    main()
