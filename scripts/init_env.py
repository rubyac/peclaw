"""Generate local-only credentials. Refuse to overwrite existing configuration."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
content = (root / ".env.example").read_text()
content = content.replace("CHANGE_ME_DB_PASSWORD", secrets.token_hex(24))
content = content.replace("CHANGE_ME_STORAGE_PASSWORD", secrets.token_hex(24))
try:
    with target.open("x") as stream:
        target.chmod(0o600)
        stream.write(content)
except FileExistsError:
    print("Existing .env preserved")
else:
    print("Created local .env with random development credentials")
