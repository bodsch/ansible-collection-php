#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Ansible module to install and update Composer in a deterministic way.

The module downloads the official Composer installer and signature, validates the
installer checksum, installs Composer into the requested target directory, and
keeps a local checksum cache to avoid unnecessary reinstalls.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.bodsch.core.plugins.module_utils.cache.cache_valid import (
    cache_valid,
)
from ansible_collections.bodsch.core.plugins.module_utils.checksum import Checksum
from ansible_collections.bodsch.core.plugins.module_utils.directory import (
    create_directory,
)

DOCUMENTATION = r"""
---
module: composer_installer

short_description: Install and update Composer

version_added: "1.0.0"

description:
  - Download the official Composer installer and signature.
  - Validate the installer checksum before execution.
  - Install Composer into a configurable target directory.
  - Keep the managed Composer binary idempotent across repeated runs.
  - Optionally force a refresh of an existing Composer installation.

author:
  - Bodo Schulz

options:
  signature:
    description:
      - URL to the Composer installer signature file.
    required: false
    type: str
    default: https://composer.github.io/installer.sig

  installer:
    description:
      - URL to the Composer installer script.
    required: false
    type: str
    default: https://getcomposer.org/installer

  version:
    description:
      - Requested Composer version.
      - Exact versions such as C(2.8.6) are compared exactly.
      - Prefix versions such as C(2) or C(2.8) are matched against the installed version.
      - When omitted, O(version_branch) is used.
    required: false
    type: str
    default: ""

  version_branch:
    description:
      - Requested Composer major branch when O(version) is not set.
      - Common values are C(--1) and C(--2).
    required: false
    type: str
    default: --2

  self_update:
    description:
      - Force a Composer reinstall even if the requested state is already satisfied.
      - When enabled, the module is intentionally not idempotent.
    required: false
    type: bool
    default: false

  path:
    description:
      - Directory where the Composer binary will be installed.
      - The managed executable path is always C(<path>/composer).
    required: false
    type: str
    default: /usr/local/bin

  force:
    description:
      - Remove cached installer data and the managed Composer binary before installation.
      - When enabled, the module is intentionally not idempotent.
    required: false
    type: bool
    default: false

notes:
  - The module requires a working C(php) binary on the target host.
  - The Composer installer and its checksum are cached below C(~/.ansible/composer).
"""

EXAMPLES = r"""
- name: Install latest Composer v2 into /usr/local/bin
  composer_installer:
    path: /usr/local/bin

- name: Install a specific Composer version
  composer_installer:
    version: "2.8.6"
    path: /usr/local/bin

- name: Force a clean reinstall
  composer_installer:
    force: true
    path: /usr/local/bin

- name: Refresh an existing managed Composer binary
  composer_installer:
    self_update: true
    path: /usr/local/bin

- name: Install Composer v1 branch
  composer_installer:
    version_branch: --1
    path: /opt/bin
"""

RETURN = r"""
version:
  description:
    - Installed Composer version detected after module execution.
  returned: always
  type: str
  sample: "2.8.6"

changed:
  description:
    - Indicates whether the module installed or refreshed Composer.
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
    - Error message returned when the module fails.
  returned: on failure
  type: str
  sample: "Composer installer checksum validation failed."
"""


class ComposerInstaller:
    """
    Install and update Composer on the managed host.

    The class encapsulates downloading and validating the official Composer
    installer, deciding whether installation is required, and installing the
    final executable into a deterministic target location.
    """

    CACHE_MINUTES: Final[int] = 120
    INSTALLER_FILENAME: Final[str] = "composer-installer.php"
    SIGNATURE_FILENAME: Final[str] = "composer-installer.sha384"
    CHECKSUM_FILENAME: Final[str] = "composer.sha256"
    VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
        r"^Composer version (?P<version>[0-9][0-9A-Za-z.\-+]*)\s*(?P<date>.*)$"
    )

    def __init__(self, module: AnsibleModule) -> None:
        """
        Initialize the installer with module parameters and derived paths.

        Args:
            module:
                The Ansible module instance.
        """
        self.module = module
        self.module.log("ComposerInstaller::__init__()")

        self.signature: str = module.params.get("signature")
        self.installer: str = module.params.get("installer")
        self.version: str = module.params.get("version")
        self.version_branch: str = module.params.get("version_branch")
        self.self_update: bool = bool(module.params.get("self_update", False))
        self.path: str = module.params.get("path")
        self.force: bool = bool(module.params.get("force", False))

        self.cache_directory: Path = Path.home() / ".ansible" / "composer"
        self.composer_installer: Path = self.cache_directory / self.INSTALLER_FILENAME
        self.composer_signature: Path = self.cache_directory / self.SIGNATURE_FILENAME

        self.install_directory: Path = Path(self.path)
        self.target_composer: Path = self.install_directory / "composer"
        self.composer_bin_checksum: Path = self._checksum_cache_file(
            self.target_composer
        )

        self.php_bin: str = module.get_bin_path("php", required=True)
        self.checksum = Checksum(self.module)

    def run(self) -> dict[str, Any]:
        """
        Execute the full Composer installation workflow.

        Returns:
            A standard Ansible result dictionary.
        """
        self.module.log("ComposerInstaller::run()")

        result: dict[str, Any] = {
            "failed": True,
            "changed": False,
            "msg": "Unable to install Composer.",
        }

        try:
            create_directory(str(self.cache_directory))
            create_directory(str(self.install_directory))

            if self.force:
                self._purge_cached_files()
                self.remove_file(self.target_composer)

            self._ensure_valid_installer_cache()
            result = self.run_installer()

        except Exception as exc:  # noqa: BLE001
            result = {
                "failed": True,
                "changed": False,
                "msg": str(exc),
            }

        return result

    def download_installer_files(self) -> None:
        """
        Download the Composer installer script and its signature.

        Raises:
            RuntimeError:
                If one of the remote resources cannot be downloaded.
        """
        self.module.log("ComposerInstaller::download_installer_files()")

        self._download_to_file(self.installer, self.composer_installer)
        self._download_to_file(self.signature, self.composer_signature)

    def validate_checksum(self, remove_changed: bool = False) -> tuple[bool, str, str]:
        """
        Validate the downloaded installer against the published signature.

        Args:
            remove_changed:
                Remove cached installer files when the checksum does not match.

        Returns:
            A tuple containing:
            - checksum mismatch state
            - computed checksum
            - expected checksum from signature file
        """
        self.module.log(
            f"ComposerInstaller::validate_checksum(remove_changed: {remove_changed})"
        )

        expected_checksum = self._read_first_line(self.composer_signature)
        computed_checksum = ""

        if self.composer_installer.exists():
            computed_checksum = self.checksum.checksum_from_file(
                path=str(self.composer_installer),
                algorithm="sha384",
            )

        changed = expected_checksum != computed_checksum

        if remove_changed and changed:
            self.remove_file(self.composer_signature)
            self.remove_file(self.composer_installer)

        return changed, computed_checksum, expected_checksum

    def composer_version(self) -> tuple[str, str]:
        """
        Detect the installed Composer version and version date string.

        Returns:
            A tuple of:
            - Composer version
            - Composer date string
        """
        self.module.log("ComposerInstaller::composer_version()")

        if not self.target_composer.exists():
            return "", ""

        args = [self.php_bin, str(self.target_composer), "--version", "--no-ansi"]
        rc, out, _ = self._exec(args)

        if rc != 0:
            return "", ""

        match = self.VERSION_PATTERN.search(out.strip())
        if not match:
            return "", ""

        return match.group("version"), match.group("date").strip()

    def remove_file(self, filename: str | Path | None) -> None:
        """
        Remove a file if it exists.

        Args:
            filename:
                File path to remove.
        """
        self.module.log(f"ComposerInstaller::remove_file(filename: {filename})")

        if filename is None:
            return

        file_path = Path(filename)
        self.module.log(msg=f"remove_file({file_path})")

        if file_path.exists():
            file_path.unlink()

    def run_installer(self) -> dict[str, Any]:
        """
        Install or refresh the managed Composer binary.

        Returns:
            A standard Ansible result dictionary.

        Raises:
            RuntimeError:
                If Composer installation does not produce the expected target file.
        """
        self.module.log("ComposerInstaller::run_installer()")

        installed_version, _ = self.composer_version()
        before_exists = self.target_composer.exists()
        before_checksum = self._binary_checksum()
        before_version = installed_version

        if not self._needs_install(installed_version):
            self._write_binary_checksum()
            return {
                "failed": False,
                "changed": False,
                "version": installed_version,
            }

        args = [self.php_bin, str(self.composer_installer), "--no-ansi"]

        if self.version:
            args.extend(["--version", self.version])
        elif self.version_branch:
            args.append(self.version_branch)

        args.extend(
            [
                "--install-dir",
                str(self.install_directory),
                "--filename",
                "composer",
            ]
        )

        self._exec(args)

        if not self.target_composer.exists():
            raise RuntimeError(
                f"Composer installation did not create '{self.target_composer}'."
            )

        after_checksum = self._binary_checksum()
        self._write_binary_checksum()

        installed_version, _ = self.composer_version()

        changed = (not before_exists) or (before_checksum != after_checksum)
        if not changed and before_version != installed_version:
            changed = True

        return {
            "failed": False,
            "changed": changed,
            "version": installed_version,
        }

    def call_url(
        self,
        url: Optional[str] = None,
        method: str = "GET",
        data: Optional[bytes] = None,
    ) -> tuple[int, str]:
        """
        Fetch textual content from a URL.

        Args:
            url:
                Source URL.
            method:
                HTTP method. Only C(GET) is supported.
            data:
                Optional request body. Currently unused.

        Returns:
            A tuple of HTTP status code and response text.
        """
        if not url:
            return 400, "Missing URL."

        if method.upper() != "GET":
            return 405, f"Unsupported HTTP method: {method}"

        request = Request(
            url=url,
            method="GET",
            headers={
                "User-Agent": "ansible-composer-installer/1.0",
                "Accept": "text/plain, application/octet-stream, */*",
            },
            data=data,
        )

        try:
            with urlopen(request, timeout=30) as response:
                content = response.read().decode("utf-8", errors="replace")
                return int(response.status), content

        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            self.module.log(msg=f"HTTP error while requesting '{url}': {exc}")
            return int(exc.code), body

        except URLError as exc:
            message = str(exc.reason)
            self.module.log(msg=f"URL error while requesting '{url}': {message}")
            return 500, message

        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            self.module.log(msg=f"Unexpected error while requesting '{url}': {message}")
            return 500, message

    def _exec(self, args: list[str]) -> tuple[int, str, str]:
        """
        Execute a command through the Ansible module runtime.

        Args:
            args:
                Command and argument list.

        Returns:
            A tuple of return code, stdout, and stderr.
        """
        rc, out, err = self.module.run_command(args, check_rc=True)
        return rc, out, err

    def _download_to_file(self, url: str, destination: Path) -> None:
        """
        Download a remote file and write it to disk.

        Args:
            url:
                Source URL.
            destination:
                Destination path.

        Raises:
            RuntimeError:
                If the download does not return HTTP 200.
        """
        self.module.log(
            f"ComposerInstaller::_download_to_file(url: {url}, destination: {destination})"
        )

        status_code, output = self.call_url(url=url)

        if status_code != 200:
            raise RuntimeError(
                f"Unable to download '{url}'. HTTP {status_code}: {output}"
            )

        destination.write_text(output, encoding="utf-8")

    def _ensure_valid_installer_cache(self) -> None:
        """
        Ensure that the cached installer and signature are present and valid.

        Raises:
            RuntimeError:
                If checksum validation still fails after a cache refresh.
        """
        self.module.log("ComposerInstaller::_ensure_valid_installer_cache()")

        if not self._is_installer_cache_valid():
            self.download_installer_files()

        changed, _, _ = self.validate_checksum(remove_changed=True)
        if not changed:
            return

        self.download_installer_files()
        changed, _, _ = self.validate_checksum(remove_changed=False)

        if changed:
            raise RuntimeError("Composer installer checksum validation failed.")

    def _is_installer_cache_valid(self) -> bool:
        """
        Check whether the cached installer data is present and still fresh.

        Returns:
            C(True) when the cache can be reused, otherwise C(False).
        """
        self.module.log("ComposerInstaller::_is_installer_cache_valid()")

        if not self.composer_signature.exists() or not self.composer_installer.exists():
            return False

        return bool(
            cache_valid(
                self.module,
                cache_file_name=str(self.composer_signature),
                cache_minutes=self.CACHE_MINUTES,
            )
        )

    def _needs_install(self, installed_version: str) -> bool:
        """
        Decide whether Composer must be installed or refreshed.

        Args:
            installed_version:
                Currently detected Composer version.

        Returns:
            C(True) when installation is required, otherwise C(False).
        """
        self.module.log(
            f"ComposerInstaller::_needs_install(installed_version: {installed_version})"
        )

        if not self.target_composer.exists():
            return True

        if self.force or self.self_update:
            return True

        if self.composer_bin_checksum.exists():
            changed, _, _ = self.checksum.validate_from_file(
                checksum_file=str(self.composer_bin_checksum),
                data_file=str(self.target_composer),
            )
            if changed:
                return True

        if not installed_version:
            return False

        return not self._version_matches_request(installed_version)

    def _normalized_branch_major(self) -> str:
        """
        Extract the major version number from C(version_branch).

        Returns:
            The normalized major version string, or an empty string.
        """
        self.module.log("ComposerInstaller::_normalized_branch_major()")

        return self.version_branch.lstrip("-").strip()

    def _purge_cached_files(self) -> None:
        """
        Remove cached installer and checksum files.
        """
        self.remove_file(self.composer_signature)
        self.remove_file(self.composer_installer)
        self.remove_file(self.composer_bin_checksum)

    @staticmethod
    def _read_first_line(filename: Path) -> str:
        """
        Read the first line of a text file.

        Args:
            filename:
                File path to read.

        Returns:
            The stripped first line, or an empty string when the file is missing.
        """
        if not filename.exists():
            return ""

        with filename.open("r", encoding="utf-8") as file_handle:
            return file_handle.readline().strip()

    def _binary_checksum(self) -> str:
        """
        Return the checksum of the managed Composer binary.

        Returns:
            The checksum string, or an empty string if the binary does not exist.
        """
        if not self.target_composer.exists():
            return ""

        return self.checksum.checksum_from_file(path=str(self.target_composer))

    def _checksum_cache_file(self, target: Path) -> Path:
        """
        Build a target-specific checksum cache filename.

        Args:
            target:
                Managed Composer target path.

        Returns:
            A path to the checksum cache file for the given target.
        """
        self.module.log(
            f"ComposerInstaller::_checksum_cache_file(target: {str(target)})"
        )
        # self.module.log(f"  {str(target.name)}")
        # safe_target = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(target))
        target_path: Path = self.cache_directory / f"{target.name}.sha256"
        self.module.log(str(target_path))
        return target_path

    @staticmethod
    def _normalize_version(version: str) -> str:
        """
        Normalize a Composer version string for comparison.

        Args:
            version:
                Raw version string.

        Returns:
            The normalized version string without a leading C(v).
        """
        return version.strip().lstrip("v")

    def _write_binary_checksum(self) -> None:
        """
        Write the checksum file for the managed Composer binary.
        """
        self.module.log("ComposerInstaller::_write_binary_checksum()")

        if not self.target_composer.exists():
            return

        checksum = self.checksum.checksum_from_file(path=str(self.target_composer))
        self.checksum.write_checksum(str(self.composer_bin_checksum), checksum)

    def _version_matches_request(self, installed_version: str) -> bool:
        """
        Check whether the installed Composer version satisfies the requested version.

        Args:
            installed_version:
                The detected installed Composer version.

        Returns:
            C(True) when the installed version matches the requested state,
            otherwise C(False).
        """
        normalized_installed = self._normalize_version(installed_version)

        if self.version:
            normalized_requested = self._normalize_version(self.version)

            if re.fullmatch(r"\d+", normalized_requested):
                installed_major = normalized_installed.split(".", maxsplit=1)[0]
                return installed_major == normalized_requested

            if re.fullmatch(r"\d+\.\d+", normalized_requested):
                installed_parts = normalized_installed.split(".")
                installed_minor = ".".join(installed_parts[:2])
                return installed_minor == normalized_requested

            return normalized_installed == normalized_requested

        branch_major = self._normalized_branch_major()
        if branch_major:
            installed_major = normalized_installed.split(".", maxsplit=1)[0]
            return installed_major == branch_major

        return True


def main() -> None:
    """
    Entrypoint for the Ansible module.
    """
    argument_spec = dict(
        signature=dict(
            required=False,
            default="https://composer.github.io/installer.sig",
            type="str",
        ),
        installer=dict(
            required=False,
            default="https://getcomposer.org/installer",
            type="str",
        ),
        version=dict(required=False, default="", type="str"),
        version_branch=dict(required=False, default="--2", type="str"),
        self_update=dict(required=False, default=False, type="bool"),
        path=dict(required=False, default="/usr/local/bin", type="str"),
        force=dict(required=False, default=False, type="bool"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=False,
    )

    helper = ComposerInstaller(module)
    result = helper.run()

    module.log(msg=f"result: {result}")
    module.exit_json(**result)


if __name__ == "__main__":
    main()
