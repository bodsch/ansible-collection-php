# python 3 headers, required if submitting to Ansible
from __future__ import absolute_import, division, print_function

from typing import Any, Dict, List, Mapping, Sequence

from ansible.utils.display import Display
from packaging.version import Version

display = Display()


class FilterModule(object):
    """
    Ansible filters. Python string operations.
    """

    def filters(self):
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
        """
        Apply distribution-specific PHP package naming rules to a list of package names.

        Rules:
        - Debian family:
          - Uses the PHP major version as the effective version identifier.
          - For PHP 8, certain packages (e.g. php-opcache) require a versioned prefix (php8-*).
          - If no rule matches, the input list is returned unchanged.
        - Archlinux family:
          - For php-legacy, rewrite packages by replacing the 'php' prefix with 'php-legacy',
            unless the package name already contains 'php-legacy'.
          - If no rule matches, the input list is returned unchanged.

        Args:
            data: Iterable of package names (e.g. ["php-gd", "php-intl"]).
            php_package_name: Target PHP package name (e.g. "php-legacy").
            version: Version metadata dict (expects "major_version" key).
            os_family: OS family string (e.g. "Debian", "Archlinux").

        Returns:
            A list of transformed package names, or the original list if no transformation applies.
        """
        display.v(
            f"add_version(data: {data}, php_package_name: {php_package_name}, version: {version}, os_family: {os_family})"
        )

        family = (os_family or "").strip().lower()
        major = str(version.get("major_version") or "").strip()

        # Default: return input unchanged (prevents unintended empty results)
        packages: List[str] = list(data)

        if family == "debian":
            # In the original code, Debian used the PHP major version as "version"
            effective_version = major

            if effective_version == "8":
                versioned_only = {"php-opcache"}
                packages = [
                    (
                        pkg.replace("php", f"php{effective_version}", 1)
                        if pkg in versioned_only
                        else pkg
                    )
                    for pkg in packages
                ]

        elif family == "archlinux":
            if php_package_name == "php-legacy":
                rewritten: List[str] = []
                for pkg in packages:
                    if "php-legacy" in pkg:
                        rewritten.append(pkg)
                    elif pkg.startswith("php"):
                        rewritten.append(pkg.replace("php", php_package_name, 1))
                    else:
                        rewritten.append(pkg)
                packages = rewritten

        display.v(f"  = {packages}")
        return packages

    def verify_version(
        self, data: Dict, version: str, field: str = "major_version"
    ) -> bool:
        """ """
        display.v(f"verify_version(data: {data}, version: {version}, field: {field})")

        result = False

        php_version = data.get("version", None)
        php_major_version = data.get("major_version", None)

        # display.v(f"    php_version        : {php_version}")
        # display.v(f"    php_major_version  : {php_major_version}")

        if "." in version:
            if not php_version:
                return False
            # display.vv(f"    {version} != {php_version}")
            result = Version(version) == Version(php_version)
        else:
            if not php_major_version:
                return False
            # display.v(f"    {version} != {php_major_version}")
            result = Version(version) == Version(php_major_version)

        display.v(f"  = {result}")

        return result
