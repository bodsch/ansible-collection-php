# python 3 headers, required if submitting to Ansible
"""Ansible filter plugin for PHP package name and version handling.

This module provides helper filters for:

- applying distribution-specific PHP package naming rules
- validating requested PHP versions against discovered version metadata

The public filter names are intentionally kept stable for Ansible compatibility.
"""

from __future__ import absolute_import, division, print_function

from typing import Any, Dict, List, Mapping, Sequence

from ansible.utils.display import Display
from packaging.version import InvalidVersion, Version

display = Display()


class FilterModule(object):
    """Ansible filter plugin for PHP-related package and version helpers."""

    _DEBIAN_VERSIONED_PACKAGES = frozenset({"php-opcache"})

    def filters(self) -> Dict[str, Any]:
        """Return the public Ansible filter mapping.

        Returns:
            A mapping between filter names exposed to Ansible and their
            corresponding bound methods.
        """
        return {
            "add_php_version": self.add_version,
            "verify_version": self.verify_version,
        }

    def add_version(
        self,
        data: Sequence[str],
        php_package_name: str,
        version: Mapping[str, Any],
        os_family: str,
    ) -> List[str]:
        """Apply distribution-specific PHP package naming rules.

        The public signature and return type are kept stable.

        Supported rules:
            - Debian:
              - Uses the PHP major version as the effective version marker.
              - For selected packages, the ``php`` prefix is rewritten to
                ``php<major>`` when the major version is ``8``.
            - Archlinux:
              - When ``php_package_name`` is ``php-legacy``, package names
                starting with ``php`` are rewritten to use ``php-legacy``.
              - Existing ``php-legacy`` package names are preserved unchanged.

        Args:
            data: Sequence of package names.
            php_package_name: Target PHP package name such as ``php`` or
                ``php-legacy``.
            version: Version metadata mapping. The implementation expects
                ``major_version`` to be present when version-specific rewriting
                is required.
            os_family: OS family string such as ``Debian`` or ``Archlinux``.

        Returns:
            A list of package names after applying the relevant rewrite rules.
            If no rule matches, the original package list is returned unchanged.
        """
        display.vv(
            "bodsch.php.add_version("
            f"data: {data}, "
            f"php_package_name: {php_package_name}, "
            f"version: {version}, "
            f"os_family: {os_family})"
        )

        packages: List[str] = list(data)
        family = self._normalize_os_family(os_family)
        major_version = self._safe_get_str(version, "major_version")

        if family == "debian":
            packages = self._rewrite_debian_packages(
                packages=packages,
                major_version=major_version,
            )
        elif family == "archlinux":
            packages = self._rewrite_archlinux_packages(
                packages=packages,
                php_package_name=php_package_name,
            )

        display.vv(f"  = {packages}")
        return packages

    def verify_version(
        self,
        data: Dict,
        version: str,
        field: str = "major_version",
    ) -> bool:
        """Verify whether a requested version matches the discovered metadata.

        Matching behavior:
            - If the requested version contains a dot, the comparison is made
              against ``full_version``.
            - Otherwise, the comparison is made against the requested ``field``.
              By default this is ``major_version``.

        Invalid or missing version values result in ``False``.

        Args:
            data: Version metadata mapping.
            version: Requested version string such as ``8`` or ``8.3.30``.
            field: Metadata field used for non-full version checks.
                Defaults to ``major_version``.

        Returns:
            ``True`` if the requested version matches the selected metadata
            value, otherwise ``False``.
        """
        display.vv(f"bodsch.php.verify_version(data: {data}, version: {version}, field: {field})")

        requested_version = (version or "").strip()

        if not requested_version:
            return False

        compare_field = self._select_compare_field(
            requested_version=requested_version,
            default_field=field,
        )
        current_version = self._safe_get_str(data, compare_field)

        if not current_version:
            return False

        result = self._versions_equal(requested_version, current_version)
        display.vv(f"  = {result}")
        return result

    def _normalize_os_family(self, os_family: str) -> str:
        """Normalize an OS family value for internal comparisons.

        Args:
            os_family: Raw OS family string.

        Returns:
            A normalized lowercase OS family string.
        """
        return (os_family or "").strip().lower()

    def _safe_get_str(self, data: Mapping[str, Any], key: str) -> str:
        """Read and normalize a mapping value as a string.

        Args:
            data: Source mapping.
            key: Key to read from the mapping.

        Returns:
            The stripped string value, or an empty string if the key is missing
            or contains ``None``.
        """
        value = data.get(key)
        return str(value).strip() if value is not None else ""

    def _rewrite_debian_packages(
        self,
        packages: Sequence[str],
        major_version: str,
    ) -> List[str]:
        """Apply Debian-specific package name rewriting rules.

        Args:
            packages: Original package names.
            major_version: PHP major version string.

        Returns:
            A rewritten package list according to Debian naming rules.
        """
        if major_version != "8":
            return list(packages)

        return [
            (
                self._replace_php_prefix(pkg, f"php{major_version}")
                if pkg in self._DEBIAN_VERSIONED_PACKAGES
                else pkg
            )
            for pkg in packages
        ]

    def _rewrite_archlinux_packages(
        self,
        packages: Sequence[str],
        php_package_name: str,
    ) -> List[str]:
        """Apply Archlinux-specific package name rewriting rules.

        Args:
            packages: Original package names.
            php_package_name: Target PHP package base name.

        Returns:
            A rewritten package list according to Archlinux naming rules.
        """
        if php_package_name != "php-legacy":
            return list(packages)

        rewritten: List[str] = []
        for package_name in packages:
            if "php-legacy" in package_name:
                rewritten.append(package_name)
            elif package_name.startswith("php"):
                rewritten.append(
                    self._replace_php_prefix(package_name, php_package_name)
                )
            else:
                rewritten.append(package_name)

        return rewritten

    def _replace_php_prefix(self, package_name: str, replacement: str) -> str:
        """Replace the leading ``php`` prefix of a package name.

        Args:
            package_name: Original package name.
            replacement: Replacement prefix.

        Returns:
            The rewritten package name if it starts with ``php``, otherwise the
            original package name.
        """
        if not package_name.startswith("php"):
            return package_name
        return package_name.replace("php", replacement, 1)

    def _select_compare_field(
        self,
        requested_version: str,
        default_field: str,
    ) -> str:
        """Determine which metadata field should be used for version comparison.

        Args:
            requested_version: Requested version string.
            default_field: Default field for non-full version comparisons.

        Returns:
            ``full_version`` for dotted version strings, otherwise the provided
            default field.
        """
        return "full_version" if "." in requested_version else default_field

    def _versions_equal(self, requested_version: str, current_version: str) -> bool:
        """Safely compare two version strings using packaging.version.

        Args:
            requested_version: Requested version value.
            current_version: Current version value from metadata.

        Returns:
            ``True`` if both versions are equal, otherwise ``False``.
            Invalid version strings are treated as non-matching.
        """
        try:
            return Version(requested_version) == Version(current_version)
        except InvalidVersion:
            return False
