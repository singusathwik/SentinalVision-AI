"""Request limits are enforced before multipart parsing, including chunked bodies."""

import tempfile

from starlette.responses import JSONResponse

from .config import settings


class RequestBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        limit = (
            (settings.max_upload_mb * 1024 * 1024 + 65536)
            if scope["path"].endswith("/videos/upload")
            else 65536
        )

        async def secured_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"cache-control", b"no-store"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
            await send(message)

        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid content length"}, 400)(scope, receive, secured_send)
        if length < 0 or length > limit:
            return await JSONResponse({"detail": "Request too large"}, 413)(scope, receive, secured_send)
        if scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, secured_send)
        # Buffer to bounded spool before handing bytes to the multipart parser.
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as spool:
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > limit:
                    return await JSONResponse({"detail": "Request too large"}, 413)(
                        scope, receive, secured_send
                    )
                spool.write(chunk)
                if not message.get("more_body", False):
                    break
            spool.seek(0)
            completed = False

            async def replay():
                nonlocal completed
                if completed:
                    return await receive()
                chunk = spool.read(65536)
                more = spool.tell() < size
                completed = not more
                return {"type": "http.request", "body": chunk, "more_body": more}

            return await self.app(scope, replay, secured_send)
