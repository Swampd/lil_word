"""Import session guard – token-based state machine for reentrant import protection.

Extracted from MainWindow to allow direct unit testing of the import
reentrancy and stale-callback logic without Qt dependencies.
"""

from __future__ import annotations

import uuid
from typing import Optional


class ImportSessionGuard:
    """Guards against reentrant media imports and stale worker callbacks.

    Protocol:
        1. Call ``start_import(media_path)`` → returns a token string, or
           ``None`` if an import is already in progress.
        2. When the background worker finishes, call ``accept_done(token)``
           or ``accept_error(token)`` with the token returned by step 1.
        3. Stale callbacks (wrong token) are silently rejected (return False).
        4. After a matching done/error, the guard is cleared and a new
           import can begin.
    """

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._media_path: Optional[str] = None

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """True while an import session is in progress."""
        return self._token is not None

    @property
    def token(self) -> Optional[str]:
        """Current import-session token, or None if idle."""
        return self._token

    @property
    def media_path(self) -> Optional[str]:
        """Media path for the active import, or None if idle."""
        return self._media_path

    # ── State transitions ────────────────────────────────────────────────

    def start_import(self, media_path: str) -> Optional[str]:
        """Begin a new import session.

        Returns
        -------
        str or None
            A unique session token if the import was accepted, or ``None``
            if an import is already in progress.
        """
        if self._token is not None:
            return None
        token = uuid.uuid4().hex
        self._token = token
        self._media_path = media_path
        return token

    def accept_done(self, token: str) -> bool:
        """Handle a successful import-worker completion.

        Returns True if the token matches (accepted), False if stale.
        On acceptance the guard is cleared so a new import can start.
        """
        if token != self._token:
            return False
        self._token = None
        # Intentionally keep _media_path – the project is now loaded.
        return True

    def accept_error(self, token: str) -> bool:
        """Handle an import-worker error.

        Returns True if the token matches (accepted), False if stale.
        On acceptance the guard and media path are both cleared.
        """
        if token != self._token:
            return False
        self._token = None
        self._media_path = None
        return True
