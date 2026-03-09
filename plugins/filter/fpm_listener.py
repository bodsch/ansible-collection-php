# python 3 headers, required if submitting to Ansible
"""Ansible filter plugin for resolving PHP-FPM listen endpoints.

This module provides a small Ansible filter that derives the effective
``listen`` value for a PHP-FPM pool configuration.

The filter supports two modes:

- TCP listen endpoints using ``listen_host`` and ``listen_port``
- Unix socket endpoints using ``listen`` and a target socket directory

The public Ansible filter name and public method signature are intentionally
kept stable for compatibility with existing playbooks.
"""

from __future__ import absolute_import, division, print_function

import os
from typing import Any, Dict, Optional

from ansible.utils.display import Display

display = Display()


class FilterModule(object):
    """Ansible filter plugin for PHP-FPM listen endpoint resolution."""

    def filters(self) -> Dict[str, Any]:
        """Return the filter functions exposed to Ansible.

        Returns:
            A mapping of public Ansible filter names to bound methods.
        """
        return {
            "fpm_listener": self.fpm_listener,
        }

    def fpm_listener(self, data: Dict, socket_directory: str) -> str:
        """Resolve the effective PHP-FPM listen endpoint.

        Resolution rules are applied in the following order:

        1. If ``listen_host`` and ``listen_port`` are defined, return
           ``<listen_host>:<listen_port>``.
        2. If only ``listen_port`` is defined, return
           ``127.0.0.1:<listen_port>``.
        3. If neither ``listen_host`` nor ``listen_port`` is defined, but
           ``listen`` is set, treat it as a Unix socket path and relocate the
           socket file into ``socket_directory`` while preserving the basename.
        4. Otherwise, return an empty string.

        Args:
            data: Pool configuration data.
            socket_directory: Directory used for relocated Unix socket files.

        Returns:
            The resolved listen endpoint as a string. This is either a TCP
            endpoint, a Unix socket path, or an empty string if the input does
            not provide enough information.
        """
        display.vv(
            f"bodsch.php.fpm_listener(data: {data}, socket_directory: {socket_directory})"
        )

        listen_host = self._as_clean_string(data.get("listen_host"))
        listen_port = self._as_clean_string(data.get("listen_port"))
        listen = self._as_clean_string(data.get("listen"))

        result = self._resolve_listen_value(
            listen_host=listen_host,
            listen_port=listen_port,
            listen=listen,
            socket_directory=socket_directory,
        )

        display.vv(f"  = {result}")
        return result

    def _resolve_listen_value(
        self,
        listen_host: Optional[str],
        listen_port: Optional[str],
        listen: Optional[str],
        socket_directory: str,
    ) -> str:
        """Resolve the final listen value from normalized input fields.

        Args:
            listen_host: Host part for a TCP listen endpoint.
            listen_port: Port part for a TCP listen endpoint.
            listen: Existing Unix socket path from the pool configuration.
            socket_directory: Directory used for relocated Unix socket files.

        Returns:
            The resolved listen endpoint string.
        """
        if listen_host and listen_port:
            return f"{listen_host}:{listen_port}"

        if listen_port:
            return f"127.0.0.1:{listen_port}"

        if listen:
            return self._build_socket_path(listen, socket_directory)

        return ""

    def _build_socket_path(self, listen: str, socket_directory: str) -> str:
        """Build the relocated Unix socket path.

        Args:
            listen: Original listen path from the PHP-FPM pool configuration.
            socket_directory: Target directory for the socket file.

        Returns:
            The normalized socket path inside the target directory.
        """
        basename = os.path.basename(listen)
        return os.path.join(socket_directory, basename)

    def _as_clean_string(self, value: Any) -> Optional[str]:
        """Normalize an arbitrary value to a stripped string.

        Args:
            value: Input value to normalize.

        Returns:
            A stripped string if the value is usable, otherwise ``None``.
        """
        if value is None:
            return None

        normalized = str(value).strip()
        return normalized or None
