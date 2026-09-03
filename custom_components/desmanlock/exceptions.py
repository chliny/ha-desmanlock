"""Exceptions raised by the Desman Lock integration."""

from __future__ import annotations


class DesmanLockError(Exception):
    """Base error for the integration."""


class DesmanLockApiError(DesmanLockError):
    """An API request or response failed."""


class DesmanLockAuthError(DesmanLockApiError):
    """The Desman account authentication is invalid or expired."""
