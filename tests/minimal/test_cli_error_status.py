import pytest

from babeldoc.main import TranslationEventError
from babeldoc.main import _raise_for_error_event


def test_error_event_fails_cli() -> None:
    with pytest.raises(TranslationEventError, match="sentinel failure"):
        _raise_for_error_event(
            {
                "type": "error",
                "error": "sentinel failure",
            }
        )
