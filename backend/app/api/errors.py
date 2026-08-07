"""Shared translation of service-layer errors into HTTP errors."""

from __future__ import annotations

from fastapi import HTTPException, status


def map_value_error(exc: ValueError) -> HTTPException:
    """Translate a service ``ValueError`` into an ``HTTPException``.

    Convention (shared by every route family): a message containing
    "not found" is a missing / not-owned resource -> 404; anything else is a
    validation or state error -> 400. Routes should ``raise
    map_value_error(exc) from exc`` instead of hand-rolling a status code.
    """
    message = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if "not found" in message.lower()
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=message)
