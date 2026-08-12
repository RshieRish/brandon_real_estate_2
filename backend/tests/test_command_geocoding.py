import pytest

from services.command_geocoding import extract_coordinates


def test_extract_coordinates_accepts_google_geocoding_result():
    assert extract_coordinates({"status": "OK", "results": [{"geometry": {"location": {"lat": 42.676, "lng": -71.302}}}]}) == ("42.676", "-71.302")


def test_extract_coordinates_rejects_non_ok_response():
    with pytest.raises(ValueError, match="not found"):
        extract_coordinates({"status": "ZERO_RESULTS", "results": []})
