"""Compliance module smoke + scanner tests."""

import pytest


def test_compliance_module_importable():
    """Module package exists and exposes a public surface."""
    from services import compliance  # noqa: F401
