#

from typing import Any


def strtobool(val: Any) -> bool:
    """Convert common truthy and falsy representations to bool.

    Args:
        val: Arbitrary value interpreted as a boolean.

    Returns:
        Normalized boolean value.

    Raises:
        ValueError: If the string value is not a known boolean representation.
    """
    if isinstance(val, bool):
        return val

    if isinstance(val, str):
        normalized = val.lower()

        if normalized in ("y", "yes", "t", "true", "on", "1"):
            return True

        if normalized in ("n", "no", "f", "false", "off", "0"):
            return False

        raise ValueError(f"invalid truth value {val}")

    return bool(val)
