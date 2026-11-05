from fastapi import HTTPException, Request
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.schemas.identity import LoginInput
from app.security.dependencies import digest


def check_login_rate(request: Request, payload: LoginInput) -> None:
    # Account limits also work behind the BFF. Never trust spoofable forwarding headers.
    peer = request.client.host if request.client else "unknown"
    settings = get_settings()
    limits = [
        ("account:" + digest(str(payload.email)), settings.auth_login_attempts),
        ("peer:" + digest(peer), settings.auth_peer_login_attempts),
    ]
    try:
        with Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=2, socket_timeout=2
        ) as client:
            with client.pipeline() as pipe:
                for key, _ in limits:
                    pipe.incr("peclaw:login-rate:" + key).expire(
                        "peclaw:login-rate:" + key, 900, nx=True
                    )
                results = pipe.execute()
    except RedisError:
        raise HTTPException(503) from None
    if any(results[index * 2] > maximum for index, (_, maximum) in enumerate(limits)):
        raise HTTPException(429)
