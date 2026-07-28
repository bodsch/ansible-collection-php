# python 3 headers, required if submitting to Ansible

"""
Ansible filter plugins for rendering and cleaning php.ini values.
"""

from __future__ import annotations

from typing import Any

from ansible.utils.display import Display

display = Display()


class FilterModule(object):
    """
    Ansible jinja2 filters for php.ini handling.
    """

    def filters(self) -> dict[str, Any]:
        """
        Return the filters exposed by this plugin.

        Returns:
            A mapping of filter name to filter callable.
        """
        return {
            "ini_values": self.ini_values,
            "remove_empty_values": self.remove_empty_values,
        }

    def ini_values(
        self,
        data: Any,
        join_list: bool = False,
        default: Any = None,
        valid_values: Any = None,
    ) -> str | int:
        """
        Render a Python value as a php.ini compatible value.

        Booleans become ``On``/``Off``, integers are returned unchanged, and
        strings are wrapped in double quotes. Empty strings become ``""``.

        Args:
            data: The value to render.
            join_list: Reserved for backward compatibility, currently unused.
            default: Reserved for backward compatibility, currently unused.
            valid_values: Reserved for backward compatibility, currently unused.

        Returns:
            The rendered php.ini value.
        """
        # display.v(f"ini_values(self, {data}, {join_list}, {default}, {valid_values})")
        result = ""

        if isinstance(data, bool):
            return "On" if data else "Off"
        if isinstance(data, int):
            return data
        if isinstance(data, str) and len(data) == 0:
            return '""'
        if isinstance(data, str):
            return f'"{data}"'

        return result

    def remove_empty_values(self, data: Any) -> Any:
        """
        Recursively remove empty values from dictionaries and lists.

        Boolean values and the integer ``0`` are preserved; ``None``, empty
        strings, empty dictionaries, empty lists, and ``False`` are removed.

        Args:
            data: The structure to clean.

        Returns:
            The cleaned structure of the same type as the input.
        """
        # display.v(f"remove_empty_values(self, {data})")

        def is_empty(value: Any) -> bool:
            """Return True if the value should be considered empty (keep booleans)."""
            if isinstance(value, bool):
                return False  # keep boolean values
            if value == 0:
                return False  # keep the integer 0

            return value in [None, "", {}, [], False]

        if isinstance(data, dict):
            # iterate over all key/value pairs
            return {
                key: self.remove_empty_values(value)
                for key, value in data.items()
                if not is_empty(value)
            }
        elif isinstance(data, list):
            # drop empty lists and empty elements
            return [
                self.remove_empty_values(item) for item in data if not is_empty(item)
            ]
        else:
            # return any other type unchanged (including booleans)
            return data
