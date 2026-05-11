from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_generate_text_flash_lite_uses_flash_model():
    from services.gemini import generate_text_flash_lite

    mock_model = MagicMock()
    mock_response = MagicMock(text="rewritten text")
    mock_model.generate_content_async = AsyncMock(return_value=mock_response)

    with patch("services.gemini.genai.GenerativeModel", return_value=mock_model) as ctor:
        out = await generate_text_flash_lite("hello")

    assert out == "rewritten text"
    ctor.assert_called_once()
    called_with = ctor.call_args.args[0] if ctor.call_args.args else ctor.call_args.kwargs.get("model_name")
    assert "flash" in called_with.lower()
