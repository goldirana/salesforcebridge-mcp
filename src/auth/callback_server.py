"""
Lightweight HTTP server to handle the OAuth callback from Salesforce.

Runs temporarily on localhost to capture the authorization code
when Salesforce redirects back after user login.
"""

from __future__ import annotations

import asyncio
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from threading import Thread
from typing import Optional

from src.config import settings

logger = logging.getLogger(__name__)


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles the GET /oauth/callback request from Salesforce."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path != "/oauth/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        if error:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            error_desc = params.get("error_description", ["Unknown error"])[0]
            self.wfile.write(
                f"<html><body><h2>Authentication Failed</h2>"
                f"<p>{error}: {error_desc}</p>"
                f"<p>You can close this window.</p></body></html>".encode()
            )
            return

        if not code or not state:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Missing Parameters</h2>"
                b"<p>No authorization code received.</p></body></html>"
            )
            return

        # Store the code and state for retrieval
        self.server.auth_code = code  # type: ignore[attr-defined]
        self.server.auth_state = state  # type: ignore[attr-defined]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body>"
            b"<h2>Authentication Successful!</h2>"
            b"<p>You have been authenticated with Salesforce.</p>"
            b"<p>You can close this window and return to the application.</p>"
            b"</body></html>"
        )

    def log_message(self, format: str, *args) -> None:
        """Suppress default stderr logging; use our logger instead."""
        logger.debug("Callback server: %s", format % args)


class OAuthCallbackServer:
    """
    Manages a temporary HTTP server to capture OAuth callbacks.

    Usage:
        server = OAuthCallbackServer()
        server.start()
        # ... user visits auth URL and gets redirected ...
        code, state = await server.wait_for_callback(timeout=300)
        server.stop()
    """

    def __init__(self, port: Optional[int] = None) -> None:
        self._port = port or settings.server.port
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[Thread] = None

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        """Start the callback server in a background thread."""
        if self._httpd is not None:
            return

        self._httpd = HTTPServer(("127.0.0.1", self._port), _CallbackHandler)
        self._httpd.auth_code = None  # type: ignore[attr-defined]
        self._httpd.auth_state = None  # type: ignore[attr-defined]

        self._thread = Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info("OAuth callback server listening on http://127.0.0.1:%d/oauth/callback", self._port)

    def stop(self) -> None:
        """Shut down the callback server."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
            self._thread = None
            logger.info("OAuth callback server stopped")

    async def wait_for_callback(self, timeout: float = 300) -> tuple[str, str]:
        """
        Wait for the OAuth callback to arrive.

        Returns (code, state) tuple.
        Raises TimeoutError if no callback arrives within timeout seconds.
        """
        elapsed = 0.0
        interval = 0.5

        while elapsed < timeout:
            if self._httpd and self._httpd.auth_code:  # type: ignore[attr-defined]
                code = self._httpd.auth_code  # type: ignore[attr-defined]
                state = self._httpd.auth_state  # type: ignore[attr-defined]
                # Reset for next use
                self._httpd.auth_code = None  # type: ignore[attr-defined]
                self._httpd.auth_state = None  # type: ignore[attr-defined]
                return code, state

            await asyncio.sleep(interval)
            elapsed += interval

        raise TimeoutError("OAuth callback was not received within the timeout period")
