# python 3 headers, required if submitting to Ansible

"""
Ansible filter plugins for working with PECL extension definitions.
"""

from __future__ import annotations

from typing import Any

from ansible.utils.display import Display

display = Display()


class FilterModule(object):
    """
    Ansible jinja2 filters for PECL extension definitions.
    """

    def filters(self) -> dict[str, Any]:
        """
        Return the filters exposed by this plugin.

        Returns:
            A mapping of filter name to filter callable.
        """
        return {
            "dependencies": self.dependencies,
        }

    def dependencies(self, data: Any) -> list[Any]:
        """
        Collect and flatten the build dependencies of PECL extensions.

        Args:
            data: A list of extension definitions. Each definition may carry a
                ``dependencies`` list.

        Returns:
            A de-duplicated, flattened list of all declared dependencies.
        """
        dependencies: list[Any] = []

        if isinstance(data, list):
            dep = [x for x in data if isinstance(x, dict) and x.get("dependencies")]

            if dep:
                for d in dep:
                    dependencies.append(d.get("dependencies"))

                dependencies = self.flatten_list(dependencies)
                # remove doubles
                dependencies = list(set(dependencies))

        return dependencies

    def flatten_list(self, data: list[list[Any]]) -> list[Any]:
        """
        Flatten a list of lists into a single list.

        Args:
            data: A list of lists, e.g. ``[[0, 1, 2], [8, 9]]``.

        Returns:
            The flattened list, e.g. ``[0, 1, 2, 8, 9]``.
        """
        return [item for sublist in data for item in sublist]
