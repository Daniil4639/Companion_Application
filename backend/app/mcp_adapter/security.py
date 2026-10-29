"""Local-only access policy, scoped to the MCP ASGI endpoint."""
from ipaddress import ip_address
from urllib.parse import urlsplit
from starlette.datastructures import Headers
from starlette.responses import JSONResponse


def is_loopback(value):
    try:
        address = ip_address(value)
        if getattr(address, "ipv4_mapped", None):
            address = address.ipv4_mapped
        return address.is_loopback
    except ValueError:
        return False


def local_authority(value):
    try:
        parsed = urlsplit("//" + value)
        return (parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                and parsed.username is None and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment
                and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


def local_request_allowed(scope):
    headers = Headers(scope=scope)
    peer = scope.get("client")
    allowed = bool(peer and is_loopback(peer[0]))
    allowed = allowed and len(headers.getlist("host")) == 1 and local_authority(headers.get("host", ""))
    # A local reverse proxy must not turn remote requests into trusted local ones.
    if any(name.lower() == b"forwarded" or name.lower().startswith(b"x-forwarded-")
           or name.lower() == b"x-real-ip" for name, _ in scope.get("headers", [])):
        allowed = False
    origins = headers.getlist("origin")
    if origins:
        try:
            origin = urlsplit(origins[0])
            allowed = (allowed and len(origins) == 1 and origin.scheme == "http"
                       and local_authority(origin.netloc) and not origin.path
                       and not origin.query and not origin.fragment)
        except ValueError:
            allowed = False
    return allowed


class LocalOnlyMCP:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        allowed = local_request_allowed(scope)
        if not allowed:
            await JSONResponse({"detail": "MCP accepts direct localhost connections only"},
                               status_code=403)(scope, receive, send)
            return
        # Serve the optional trailing slash without redirects or a second protocol path.
        if scope["path"].endswith("/"):
            scope = {**scope, "path": scope["path"].rstrip("/"),
                     "raw_path": scope["path"].rstrip("/").encode("ascii")}
        await self.app(scope, receive, send)