"""utils/limiter.py — slowapi 공용 Limiter (라우터 데코레이터와 main 이 같은 객체를 쓰도록 분리)."""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def client_ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or get_remote_address(request))


limiter = Limiter(key_func=client_ip, default_limits=["120/minute"])
