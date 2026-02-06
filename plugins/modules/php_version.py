#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2022-2023, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

"""
Ansible module to discover available PHP package versions for the current Linux distribution.

The module inspects the package metadata of the host OS and returns an "available" version
structure containing:
- version: the discovered PHP version string (major.minor[.patch] depending on repository metadata)
- package_version: numeric package variant without dots (e.g. "82" for "8.2")
- major_version: the major version number (e.g. "8" for "8.2")

Supported platforms:
- Debian/Ubuntu: uses python-apt (python3-apt)
- Arch/Artix: uses pacman via Ansible's run_command

The module is read-only and does not modify system state.
"""

from __future__ import absolute_import, division, print_function

import re
from typing import Any, Dict, List, Optional, Tuple

from ansible.module_utils import distro
from ansible.module_utils.basic import AnsibleModule

# ---------------------------------------------------------------------------------------

DOCUMENTATION = r"""
---
module: php_version
author: "Bodo Schulz (@bodsch) <bodo@boone-schulz.de>"
version_added: "1.0.0"

short_description: Discover the available PHP package version for the current distribution.
description:
  - Reads the system package metadata and determines a suitable PHP version string for the requested package.
  - On Debian/Ubuntu, this module requires C(python3-apt) to query APT metadata.
  - On Arch/Artix, this module calls C(pacman) to search repositories.

options:
  package:
    description:
      - The package name to inspect.
    type: str
    required: false
    default: php
  package_version:
    description:
      - Desired version prefix to match (e.g. C(8.2)).
      - If empty, the module returns the first version found in package metadata (typically the newest).
    type: str
    required: false
    default: ''

notes:
  - On Debian/Ubuntu, querying APT metadata requires a working local APT cache and python-apt.
  - This module does not install or update packages.
"""

EXAMPLES = r"""
- name: Discover default PHP version metadata (package=php)
  php_version:
  register: php_info

- name: Discover PHP 8.2 package version
  php_version:
    package: php
    package_version: "8.2"
  register: php82_info

- name: Discover php7 package on Arch/Artix (example)
  php_version:
    package: php7
    package_version: "7.4"
  register: php74_info

- name: Use results
  debug:
    msg:
      - "Version: {{ php_info.available.version }}"
      - "Major: {{ php_info.available.major_version }}"
      - "PkgVersion: {{ php_info.available.package_version }}"
"""

RETURN = r"""
available:
  description: Parsed version information.
  returned: always
  type: dict
  contains:
    version:
      description: The discovered PHP version string.
      type: str
      returned: always
    package_version:
      description: The version without dots (e.g. "82" for "8.2").
      type: str
      returned: always
    major_version:
      description: The major version (e.g. "8" for "8.2").
      type: str
      returned: always
msg:
  description: Additional information, especially on failure.
  returned: always
  type: str
failed:
  description: Whether the module failed.
  returned: always
  type: bool
"""

# ---------------------------------------------------------------------------------------


class PHPVersion(object):
    """
    Determine the available PHP package version for the current host distribution.

    The module supports:
    - Debian/Ubuntu via python-apt (APT cache inspection)
    - Arch/Artix via pacman search

    Public API stability:
    - __init__(module) keeps signature
    - run() returns a dict compatible with AnsibleModule.exit_json()/fail_json()
    """

    # Distributions grouped by package manager
    _UNSUPPORTED_DISTROS = {
        "redhat",
        "centos",
        "oracle",
        "fedora",
        "rocky",
        "almalinux",
    }
    _APT_DISTROS = {"debian", "ubuntu"}
    _PACMAN_DISTROS = {"arch", "artix"}

    # Debian/Ubuntu: tolerate optional epoch and accept major.minor[.patch...]
    _APT_VERSION_RE = re.compile(r"^(?:\d+:)?(?P<version>\d+(?:\.\d+)+)")

    # Arch/Artix: parse pacman search lines (repository/package version-release)
    # Example lines:
    #   extra/php 8.1.2-1
    #   extra/php7 7.4.27-1
    _PACMAN_LINE_RE = re.compile(
        r"^(?P<repository>extra|world)\/php[0-9 ]+(?P<version>\d+\.\d+).*$",
        re.MULTILINE,
    )

    module: AnsibleModule

    def __init__(self, module: AnsibleModule):
        """
        Initialize the helper with AnsibleModule and compute distro information.

        Args:
            module: The AnsibleModule instance providing parameters and utilities.
        """
        self.module = module
        self.module.log("PHPVersion::__init__()")

        self.package: str = module.params.get("package")
        self.package_version: str = module.params.get("package_version")

        # distro.linux_distribution is provided by Ansible's module_utils.distro wrapper
        self.distribution, self.version, self.codename = distro.linux_distribution(
            full_distribution_name=False
        )

        if self.package:
            self._PACMAN_LINE_RE = re.compile(
                r"^(?P<repository>core|extra|community|world|local)\/{} (?P<version>\d+(\.\d+){{0,2}}(\.\*)?)-.*".format(
                    self.package
                ),
                re.MULTILINE,
            )

        self.pacman_bin: Optional[str] = None

    def run(self) -> Dict[str, Any]:
        """
        Execute the version discovery process.

        Returns:
            A result dictionary consumable by Ansible. Keys:
            - failed: bool
            - available: dict(version, package_version, major_version)
            - msg: str
        """
        self.module.log("PHPVersion::run()")

        distro_lower = (self.distribution or "").lower()

        msg = f"not supported distribution: {self.distribution}."
        error = True
        version = ""

        # Keep original early return behavior for explicitly unsupported RHEL-like distros
        if distro_lower in self._UNSUPPORTED_DISTROS:
            return {"failed": True, "msg": msg}

        if distro_lower in self._APT_DISTROS:
            error, version, msg = self._search_apt()
        elif distro_lower in self._PACMAN_DISTROS:
            self.pacman_bin = self.module.get_bin_path("pacman", required=True)
            error, version, msg = self._search_pacman()

        available = self._build_available(version)

        return {
            "failed": error,
            "available": available,
            "msg": msg,
        }

    def _build_available(self, version: str) -> Dict[str, str]:
        """
        Convert a raw version string into the normalized return structure.

        Args:
            version: Raw discovered version string.

        Returns:
            Dict with keys: version, package_version, major_version.
        """
        self.module.log(f"PHPVersion::_build_available(version: {version})")

        if not version:
            return {"version": "", "package_version": "", "major_version": ""}

        package_version = version.replace(".", "")
        major_version = version.split(".", 1)[0]

        return {
            "version": version,
            "package_version": package_version,
            "major_version": major_version,
        }

    def _search_apt(self) -> Tuple[bool, str, str]:
        """
        Discover a PHP version via APT metadata (Debian/Ubuntu).

        The method inspects available versions from the local APT cache.
        If package_version is set, it tries to find a version starting with that prefix.

        Returns:
            (failed, version, msg)
        """
        self.module.log("PHPVersion::_search_apt()")

        try:
            import apt  # type: ignore
        except Exception:
            return (
                True,
                "",
                "python3-apt is required on Debian/Ubuntu to query APT metadata.",
            )

        try:
            cache = apt.cache.Cache()

            # Updating can fail without privileges or in restricted environments;
            # attempt it but do not hard-fail on update errors.
            try:
                cache.update()
            except Exception:
                pass

            cache.open()
        except Exception as exc:
            return True, "", "unable to open apt cache: {}".format(exc)

        pkg = cache.get(self.package)
        if not pkg:
            return True, "", "package {} not found in apt cache.".format(self.package)

        requested = self.package_version or ""
        discovered: Optional[str] = None

        for pkg_version in pkg.versions:
            raw = getattr(pkg_version, "version", "")
            m = self._APT_VERSION_RE.search(raw)
            if not m:
                continue

            candidate = m.group("version")

            # If no requested prefix, take the first candidate (APT typically lists newest first)
            if not requested:
                discovered = candidate
                break

            if candidate.startswith(requested):
                discovered = candidate
                break

        if not discovered:
            return True, "", "no php version {} found.".format(self.package_version)

        return False, discovered, ""

    def _search_pacman(self) -> Tuple[bool, str, str]:
        """
        Discover a PHP version via pacman search (Arch/Artix).

        Returns:
            (failed, version, msg)
        """
        self.module.log("PHPVersion::_search_pacman()")

        if not self.pacman_bin:
            self.pacman_bin = self.module.get_bin_path("pacman", required=True)

        args: List[str] = []

        args.append(self.pacman_bin)
        args.append("--noconfirm")
        args.append("--sync")
        args.append("--search")
        args.append(self.package)

        rc, out, err = self._exec(args, check_rc=False)

        if rc != 0 and not out:
            return True, "", (err or "pacman search failed.")

        matches = list(self._PACMAN_LINE_RE.finditer(out))

        self.module.log(f"  - matches: {matches}")

        if not matches:
            return True, "", "not found"

        requested = self.package_version or ""
        seen_versions: List[str] = []

        for m in matches:
            v = m.group("version")
            seen_versions.append(v)

            if not requested:
                return False, v, ""

            if v == requested or v.startswith(requested):
                return False, v, ""

        # No match for requested version; provide the seen versions as feedback
        return (
            True,
            "",
            "you want version {}, but i found versions {}.".format(
                requested, seen_versions
            ),
        )

    def _exec(
        self,
        args: List[str],
        environ_update: Optional[Dict[str, str]] = None,
        check_rc: bool = True,
    ) -> Tuple[int, str, str]:
        """
        Execute a prepared command via the Ansible module's `run_command()`.

        Args:
            args: Full argument vector to execute (already includes `occ_base_args`).
            environ_update: Environment variables added/overridden for this process.
                Example: {"OC_PASS": "<secret>"} used together with `--password-from-env`.
            check_rc: If True, Ansible will raise a failure on non-zero return code.

        Returns:
            Tuple of (rc, out, err):
                - rc: return code (int)
                - out: stdout (str)
                - err: stderr (str)

        Security:
            Avoid logging secrets in `environ_update`. If you need debug logging, consider
            redacting sensitive keys before writing to module logs.
        """
        self.module.log(
            msg=f"PHPVersion::_exec(args: {args}, environ_update: {environ_update}, check_rc: {check_rc})"
        )

        rc, out, err = self.module.run_command(
            args, environ_update=environ_update, check_rc=check_rc
        )

        self.module.log(msg=f"  rc : '{rc}'")
        self.module.log(msg=f"  out: '{out}'")
        self.module.log(msg=f"  err: '{err}'")

        return rc, out, err

    # def _exec(self, args: Sequence[str]) -> Tuple[int, str, str]:
    #     """
    #     Execute pacman with the given arguments.
    #
    #     Args:
    #         args: Arguments passed to pacman.
    #
    #     Returns:
    #         (rc, stdout, stderr)
    #     """
    #     self.module.log(f"PHPVersion::_exec(args: {args})")
    #
    #     cmd = [self.pacman_bin] + list(args)
    #     rc, out, err = self.module.run_command(cmd, check_rc=False)
    #
    #     return rc, out, err


def main():
    argument_spec = dict(
        package=dict(
            required=False,
            default="php",
            type="str",
        ),
        package_version=dict(
            required=False,
            default="",
            type="str",
        ),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=False,
    )

    helper = PHPVersion(module)
    result = helper.run()
    module.exit_json(**result)


if __name__ == "__main__":
    main()
