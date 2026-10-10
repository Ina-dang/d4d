"""Local access and authenticated, same-origin access through an HTTPS reverse proxy."""

import base64
import binascii
import secrets
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import PlainTextResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware


def authenticated(authorization, settings):
    if not settings.access_user:
        return True
    try:
        scheme, encoded = authorization.split(' ', 1)
        if scheme.lower() != 'basic':
            return False
        supplied = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return False
    expected = f'{settings.access_user}:{settings.access_password}'.encode()
    return secrets.compare_digest(supplied, expected)


def configure_security(app, settings):
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware('http')
    async def protect(request: Request, call_next):
        if not authenticated(request.headers.get('authorization', ''), settings):
            return PlainTextResponse('접속 계정이 필요합니다.', status_code=401, headers={
                'WWW-Authenticate': 'Basic realm="Gyeopnun", charset="UTF-8"',
                'Cache-Control': 'no-store',
            })
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            origin = request.headers.get('origin')
            expected = urlsplit(str(request.base_url))
            # Proxy-supplied Host/Origin values never extend the configured allowlist.
            allowed = set(settings.public_origins)
            allowed.add(f'{expected.scheme}://{expected.netloc}')
            if origin and origin not in allowed:
                return PlainTextResponse('다른 출처에서의 변경 요청은 허용하지 않습니다.', status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        if request.url.path.startswith('/storyboard/'):
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "font-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'self'; base-uri 'none'"
            )
        response.headers['Cache-Control'] = 'no-store'
        return response
