#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Ansible module to install and update PIE (PHP Installer for Extensions).

PIE is distributed as a PHAR from the GitHub releases of the C(php/pie)
project. The module resolves the requested release, downloads C(pie.phar),
verifies its SHA-256 digest against the digest published by the GitHub release
API, installs it into a configurable target directory, and keeps a local
checksum cache to avoid unnecessary reinstalls.

Unlike Composer, PIE is not installed via an installer script and does not use
C(COMPOSER_HOME). Source verification via C(gh attestation verify) is available
upstream but intentionally not used here, because it would introduce the GitHub
CLI as an additional runtime dependency. The published SHA-256 digest provides
an integrity guarantee using only the Python standard library.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.bodsch.core.plugins.module_utils.directory import (
    create_directory,
)

DOCUMENTATION = r"""
---
module: pie_installer

short_description: Install and update PIE (PHP Installer for Extensions)

version_added: "1.5.0"

description:
  - Resolve the requested PIE release from the GitHub release API.
  - Download the C(pie.phar) release asset and verify its SHA-256 digest.
  - Install PIE into a configurable target directory as an executable.
  - Keep the managed PIE binary idempotent across repeated runs.
  - Optionally force a refresh of an existing PIE installation.

author:
  - Bodo Schulz

options:
  version:
    description:
      - Requested PIE version, for example C(1.5.0).
      - A leading C(v) is ignored.
      - When omitted, the latest published release is installed.
    required: false
    type: str
    default: ""

  path:
    description:
      - Directory where the PIE binary is installed.
      - The managed executable path is always C(<path>/<filename>).
    required: false
    type: str
    default: /usr/local/bin

  filename:
    description:
      - Name of the managed PIE executable inside O(path).
    required: false
    type: str
    default: pie

  repository:
    description:
      - GitHub repository that publishes the PIE releases.
    required: false
    type: str
    default: php/pie

  api_url:
    description:
      - Base URL of the GitHub REST API used to resolve releases.
    required: false
    type: str
    default: https://api.github.com

  self_update:
    description:
      - Force a PIE reinstall even if the requested state is already satisfied.
      - When enabled, the module is intentionally not idempotent.
    required: false
    type: bool
    default: false

  force:
    description:
      - Remove the cached checksum and the managed PIE binary before installation.
      - When enabled, the module is intentionally not idempotent.
    required: false
    type: bool
    default: false

notes:
  - The module requires a working C(php) binary (PHP 8.1 or newer) on the target host.
  - The downloaded PHAR and its checksum are cached below C(~/.ansible/pie).
"""

EXAMPLES = r"""
- name: Install the latest PIE release into /usr/local/bin
  bodsch.php.pie_installer:
    path: /usr/local/bin

- name: Install a specific PIE version
  bodsch.php.pie_installer:
    version: "1.5.0"
    path: /usr/local/bin

- name: Force a clean reinstall
  bodsch.php.pie_installer:
    force: true
"""

RETURN = r"""
version:
  description:
    - Installed PIE version detected after module execution.
  returned: always
  type: str
  sample: "1.5.0"

changed:
  description:
    - Indicates whether the module installed or refreshed PIE.
  returned: always
  type: bool
  sample: false

failed:
  description:
    - Indicates whether the module execution failed.
  returned: always
  type: bool
  sample: false

msg:
  description:
    - Human-readable status or error message.
  returned: always
  type: str
  sample: "PIE 1.5.0 is already installed."
"""


class PieInstaller:
    """
    Install and update PIE on the managed host.

    The class encapsulates resolving the requested release from the GitHub
    release API, downloading and verifying C(pie.phar), deciding whether an
    installation is required, and installing the executable into a
    deterministic target location.
    """

    CACHE_DIRECTORY_NAME: Final[str] = "pie"
    CHECKSUM_SUFFIX: Final[str] = ".sha256"
    VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?)")
    USER_AGENT: Final[str] = "ansible-bodsch-php-pie-installer/1.0"

    def __init__(self, module: AnsibleModule) -> None:
        """
        Initialize the installer with module parameters and derived paths.

        Args:
            module:
                The active Ansible module instance.
        """
        self.module = module
        self.module.log("PieInstaller::__init__()")

        self.version: str = self._normalize_version(module.params.get("version") or "")
        self.repository: str = module.params.get("repository")
        self.api_url: str = module.params.get("api_url").rstrip("/")
        self.self_update: bool = bool(module.params.get("self_update", False))
        self.force: bool = bool(module.params.get("force", False))

        self.install_directory: Path = Path(module.params.get("path"))
        self.target_pie: Path = self.install_directory / module.params.get("filename")

        self.cache_directory: Path = Path.home() / ".ansible" / self.CACHE_DIRECTORY_NAME
        self.binary_checksum_file: Path = (
            self.cache_directory / f"{self.target_pie.name}{self.CHECKSUM_SUFFIX}"
        )

        self.php_bin: str = module.get_bin_path("php", required=True)

    def run(self) -> dict[str, Any]:
        """
        Execute the full PIE installation workflow.

        Returns:
            A standard Ansible result dictionary.
        """
        self.module.log("PieInstaller::run()")

        try:
            create_directory(str(self.cache_directory))
            create_directory(str(self.install_directory))

            if self.force:
                self._remove_file(self.binary_checksum_file)
                self._remove_file(self.target_pie)

            release_tag, asset_url, expected_sha256 = self._resolve_release()
            installed_version = self._installed_version()

            if not self._needs_install(installed_version, release_tag):
                self._write_binary_checksum()
                return {
                    "failed": False,
                    "changed": False,
                    "version": installed_version,
                    "msg": f"PIE {installed_version} is already installed.",
                }

            if self.module.check_mode:
                return {
                    "failed": False,
                    "changed": True,
                    "version": release_tag,
                    "msg": f"PIE {release_tag} would be installed.",
                }

            self._download_and_install(asset_url, expected_sha256)
            self._write_binary_checksum()

            new_version = self._installed_version() or release_tag

            return {
                "failed": False,
                "changed": True,
                "version": new_version,
                "msg": f"PIE {new_version} has been installed.",
            }

        except Exception as exc:  # noqa: BLE001
            return {
                "failed": True,
                "changed": False,
                "version": "",
                "msg": str(exc),
            }

    def _resolve_release(self) -> tuple[str, str, str]:
        """
        Resolve the requested release to a tag, download URL, and SHA-256 digest.

        Returns:
            A tuple of:
            - resolved release tag (version without a leading ``v``)
            - ``pie.phar`` download URL
            - expected SHA-256 checksum (lower-case hex)

        Raises:
            RuntimeError:
                If the release or the ``pie.phar`` asset cannot be resolved.
        """
        self.module.log(f"PieInstaller::_resolve_release() version={self.version!r}")

        if self.version:
            endpoint = f"{self.api_url}/repos/{self.repository}/releases/tags/{self.version}"
        else:
            endpoint = f"{self.api_url}/repos/{self.repository}/releases/latest"

        payload = self._get_json(endpoint)

        tag = self._normalize_version(str(payload.get("tag_name") or ""))
        if not tag:
            raise RuntimeError(f"Unable to resolve a PIE release from '{endpoint}'.")

        assets = payload.get("assets")
        if not isinstance(assets, list):
            raise RuntimeError(f"Release '{tag}' does not expose any assets.")

        for asset in assets:
            if isinstance(asset, dict) and asset.get("name") == "pie.phar":
                asset_url = str(asset.get("browser_download_url") or "")
                digest = str(asset.get("digest") or "")
                expected_sha256 = digest.split(":", 1)[1] if ":" in digest else ""

                if not asset_url:
                    raise RuntimeError(f"Release '{tag}' has no download URL for 'pie.phar'.")

                return tag, asset_url, expected_sha256.lower()

        raise RuntimeError(f"Release '{tag}' does not contain a 'pie.phar' asset.")

    def _needs_install(self, installed_version: str, release_tag: str) -> bool:
        """
        Decide whether PIE must be installed or refreshed.

        Args:
            installed_version:
                Currently detected PIE version, or an empty string.
            release_tag:
                Resolved release tag that would be installed.

        Returns:
            C(True) when installation is required, otherwise C(False).
        """
        self.module.log(
            f"PieInstaller::_needs_install(installed={installed_version!r}, tag={release_tag!r})"
        )

        if not self.target_pie.exists():
            return True

        if self.force or self.self_update:
            return True

        if not installed_version:
            return True

        if self._binary_checksum_changed():
            return True

        return installed_version != release_tag

    def _download_and_install(self, asset_url: str, expected_sha256: str) -> None:
        """
        Download C(pie.phar), verify its checksum, and install it.

        Args:
            asset_url:
                Download URL of the ``pie.phar`` release asset.
            expected_sha256:
                Expected SHA-256 checksum, or an empty string to skip verification.

        Raises:
            RuntimeError:
                If the download fails or the checksum does not match.
        """
        self.module.log(f"PieInstaller::_download_and_install(url={asset_url})")

        payload = self._get_bytes(asset_url)
        computed_sha256 = hashlib.sha256(payload).hexdigest()

        if expected_sha256 and computed_sha256 != expected_sha256:
            raise RuntimeError(
                "PIE checksum validation failed: "
                f"expected {expected_sha256}, got {computed_sha256}."
            )

        self.target_pie.write_bytes(payload)

        current_mode = self.target_pie.stat().st_mode
        self.target_pie.chmod(
            current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )

    def _installed_version(self) -> str:
        """
        Detect the installed PIE version by invoking the managed binary.

        Returns:
            The detected version string, or an empty string when PIE is not
            installed or the version cannot be determined.
        """
        if not self.target_pie.exists():
            return ""

        rc, out, err = self.module.run_command(
            [self.php_bin, str(self.target_pie), "--version", "--no-ansi"],
            check_rc=False,
        )

        if rc != 0:
            return ""

        match = self.VERSION_PATTERN.search(f"{out}\n{err}")
        if not match:
            return ""

        return match.group("version")

    def _binary_checksum_changed(self) -> bool:
        """
        Compare the managed binary against the cached checksum.

        Returns:
            C(True) when the binary differs from the cached checksum or no cache
            exists, otherwise C(False).
        """
        if not self.binary_checksum_file.exists():
            return False

        cached = self.binary_checksum_file.read_text(encoding="utf-8").strip()
        current = self._checksum_of(self.target_pie)

        return cached != current

    def _write_binary_checksum(self) -> None:
        """
        Persist the checksum of the managed PIE binary to the cache.
        """
        if not self.target_pie.exists():
            return

        self.binary_checksum_file.write_text(
            self._checksum_of(self.target_pie),
            encoding="utf-8",
        )

    def _get_json(self, url: str) -> dict[str, Any]:
        """
        Fetch and decode a JSON document from a URL.

        Args:
            url:
                Source URL.

        Returns:
            The decoded JSON object.

        Raises:
            RuntimeError:
                If the request fails or the response is not valid JSON.
        """
        raw = self._get_bytes(url, accept="application/vnd.github+json")

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Invalid JSON response from '{url}': {exc}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected JSON structure returned from '{url}'.")

        return payload

    def _get_bytes(self, url: str, accept: str = "application/octet-stream") -> bytes:
        """
        Download the raw bytes of a URL, following redirects.

        Args:
            url:
                Source URL.
            accept:
                Value for the HTTP ``Accept`` header.

        Returns:
            The response body as bytes.

        Raises:
            RuntimeError:
                If the resource cannot be downloaded.
        """
        request = Request(
            url=url,
            method="GET",
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": accept,
            },
        )

        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} while requesting '{url}': {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Unable to request '{url}': {exc.reason}") from exc

    @staticmethod
    def _checksum_of(path: Path) -> str:
        """
        Compute the SHA-256 checksum of a file.

        Args:
            path:
                File to hash.

        Returns:
            The lower-case hexadecimal SHA-256 checksum.
        """
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _normalize_version(version: str) -> str:
        """
        Normalize a version string for comparison.

        Args:
            version:
                Raw version string.

        Returns:
            The stripped version string without a leading ``v``.
        """
        return version.strip().lstrip("v")

    def _remove_file(self, path: Path) -> None:
        """
        Remove a file if it exists.

        Args:
            path:
                File to remove.
        """
        if path.exists():
            path.unlink()


def main() -> None:
    """
    Entrypoint for the Ansible module.
    """
    argument_spec = dict(
        version=dict(required=False, default="", type="str"),
        path=dict(required=False, default="/usr/local/bin", type="str"),
        filename=dict(required=False, default="pie", type="str"),
        repository=dict(required=False, default="php/pie", type="str"),
        api_url=dict(required=False, default="https://api.github.com", type="str"),
        self_update=dict(required=False, default=False, type="bool"),
        force=dict(required=False, default=False, type="bool"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    helper = PieInstaller(module)
    result = helper.run()

    module.log(msg=f"result: {result}")

    if result.get("failed"):
        module.fail_json(**result)

    module.exit_json(**result)


if __name__ == "__main__":
    main()
