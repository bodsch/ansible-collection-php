#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Ansible module for managing global Composer packages.

The module installs, updates, and removes Composer packages in the global
Composer context of the executing user. It is designed to be idempotent and
returns a per-package result summary.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r"""
---
module: composer_packages

short_description: Manage global Composer packages

version_added: "1.0.0"

description:
  - Install, update, and remove Composer packages in the global Composer context.
  - Supports exact versions as well as Composer version constraints.
  - Uses state-aware package handling to keep module runs idempotent.

author:
  - Bodo Schulz

options:
  packages:
    description:
      - List of Composer packages to manage.
      - Each entry defines the package name, optional release constraint, and desired state.
    required: false
    type: list
    elements: dict
    default: []
    suboptions:
      name:
        description:
          - Composer package name in vendor/package format.
        required: true
        type: str
      release:
        description:
          - Exact version or Composer version constraint.
          - Examples are C(1.2.3), C(^2.0), or C(@stable).
          - When omitted, Composer resolves the latest compatible stable release.
        required: false
        type: str
      state:
        description:
          - Desired package state.
        required: false
        type: str
        choices:
          - present
          - absent
        default: present

  force:
    description:
      - Force package reconciliation even when an installed package already appears to match.
      - This is mainly useful for non-exact version constraints or when dependencies should be re-resolved.
    required: false
    type: bool
    default: false

notes:
  - Composer must already be installed on the managed host.
  - Package operations are executed in the global Composer context of the current remote user.
  - When executed as root, the module enables C(COMPOSER_ALLOW_SUPERUSER=1).
"""

EXAMPLES = r"""
- name: Install two global Composer packages
  composer_packages:
    packages:
      - name: psr/cache
      - name: psr/log

- name: Install a package with an exact version
  composer_packages:
    packages:
      - name: psr/cache
        release: "3.0.0"
        state: present

- name: Install a package with a Composer constraint
  composer_packages:
    packages:
      - name: symfony/console
        release: "^7.0"
        state: present

- name: Remove a global Composer package
  composer_packages:
    packages:
      - name: psr/log
        state: absent

- name: Force reconciliation of managed packages
  composer_packages:
    force: true
    packages:
      - name: symfony/console
        release: "^7.0"
        state: present
"""

RETURN = r"""
changed:
  description:
    - Indicates whether at least one package was installed, updated, or removed.
  returned: always
  type: bool
  sample: true

msg:
  description:
    - Per-package result details.
  returned: always
  type: list
  elements: dict
  sample:
    - psr/cache:
        changed: false
        msg: "Already installed in version 3.0.0."
    - psr/log:
        changed: true
        msg: "Removed version 3.0.2."

failed:
  description:
    - Indicates whether the module execution failed.
  returned: always
  type: bool
  sample: false
"""


@dataclass(frozen=True)
class ComposerPackageSpec:
    """
    Internal package definition used by the module logic.

    Attributes:
        name:
            Composer package name in vendor/package format.
        release:
            Optional exact version or Composer version constraint.
        state:
            Desired package state.
    """

    name: str
    release: Optional[str] = None
    state: str = "present"


class ComposerPackages:
    """
    Manage global Composer packages through the Composer CLI.

    The class provides a small public API used by the Ansible module entrypoint
    and keeps command execution, package normalization, and state comparisons in
    private helper methods.
    """

    EXACT_VERSION_PATTERN = re.compile(r"^v?\d+(?:\.\d+){0,3}(?:[-+._]?[0-9A-Za-z]+)*$")

    def __init__(self, module: AnsibleModule) -> None:
        """
        Initialize the Composer package manager helper.

        Args:
            module:
                Active Ansible module instance.
        """
        self.module = module
        self.module.log("ComposerPackages::__init__()")

        self.packages: list[dict[str, Any]] = module.params.get("packages") or []
        self.force: bool = bool(module.params.get("force", False))

        self.php_bin: str = module.get_bin_path("php", required=True)
        self.composer_bin: str = module.get_bin_path("composer", required=True)

        self._installed_cache: Optional[dict[str, str]] = None

    def run(self) -> dict[str, Any]:
        """
        Execute the requested package operations.

        Returns:
            An Ansible-compatible result dictionary.
        """
        self.module.log("ComposerPackages::run()")

        try:
            return self.package_management()
        except Exception as exc:  # noqa: BLE001
            return {
                "failed": True,
                "changed": False,
                "msg": str(exc),
            }

    def package_management(self) -> dict[str, Any]:
        """
        Reconcile all declared Composer packages.

        Returns:
            An Ansible-compatible result dictionary containing a per-package
            result summary.
        """
        self.module.log("ComposerPackages::package_management()")

        result_state: list[dict[str, dict[str, Any]]] = []
        changed = False

        self._invalidate_installed_cache()

        for index, raw_package in enumerate(self.packages):
            package = self._parse_package_definition(raw_package, index)
            package_result = self._manage_package(package)

            result_state.append({package.name: package_result})
            changed = changed or bool(package_result.get("changed", False))

        return {
            "failed": False,
            "changed": changed,
            "msg": result_state,
        }

    def installed_packages(self) -> dict[str, str]:
        """
        Return all globally installed Composer packages.

        Returns:
            A mapping of package name to installed version.

        Raises:
            RuntimeError:
                If Composer returns an unexpected error or invalid JSON output.
        """
        self.module.log("ComposerPackages::installed_packages()")

        if self._installed_cache is not None:
            return dict(self._installed_cache)

        self._ensure_global_composer_project()

        args = self._composer_base_command() + [
            "global",
            "show",
            "--format",
            "json",
            "--no-interaction",
        ]

        self.module.log(f"  - args: {args}")

        env_vars = self._composer_environment()
        rc, out, err = self._exec(args, env_vars=env_vars)

        if rc != 0:
            combined_output = self._combine_output(out, err)

            if "No dependencies installed" in combined_output:
                self._installed_cache = {}
                return {}

            raise RuntimeError(
                f"Unable to list installed Composer packages: {combined_output}"
            )

        if not out.strip():
            self._installed_cache = {}
            return {}

        try:
            payload = json.loads(out)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Composer returned invalid JSON while listing packages: {exc}"
            ) from exc

        self.module.log(f"  - payload: {payload}")

        installed_entries: list[dict[str, Any]] = []

        if isinstance(payload, dict):
            raw_entries = payload.get("installed") or []
            if isinstance(raw_entries, list):
                installed_entries = [
                    item for item in raw_entries if isinstance(item, dict)
                ]
        elif isinstance(payload, list):
            installed_entries = [item for item in payload if isinstance(item, dict)]
        else:
            raise RuntimeError(
                f"Unexpected JSON structure returned by Composer: {type(payload).__name__}"
            )

        installed = {
            str(item["name"]): str(item.get("version") or item.get("pretty_version"))
            for item in installed_entries
            if item.get("name") and (item.get("version") or item.get("pretty_version"))
        }

        self._installed_cache = installed
        return dict(installed)

    def install_package(
        self, package_name: str, package_release: Optional[str]
    ) -> dict[str, Any]:
        """
        Install or update a Composer package.

        Args:
            package_name:
                Composer package name.
            package_release:
                Optional exact version or Composer version constraint.

        Returns:
            A per-package result dictionary.

        Raises:
            RuntimeError:
                If the Composer command fails or the package cannot be verified
                after a successful command execution.
        """
        self.module.log(
            f"ComposerPackages::install_package(package_name: {package_name}, package_release: {package_name})"
        )

        before = self.installed_packages().get(package_name)
        package_reference = self._build_package_reference(package_name, package_release)

        args = self._composer_base_command() + [
            "global",
            "require",
            package_reference,
            "--no-progress",
            "--no-interaction",
            # "--no-audit",
            "--optimize-autoloader",
        ]

        self.module.log(f"  - args: {args}")

        rc, out, err = self._exec(args, env_vars=self._composer_environment())

        if rc != 0:
            raise RuntimeError(
                self._format_command_error(
                    action="install or update",
                    package_name=package_name,
                    rc=rc,
                    out=out,
                    err=err,
                )
            )

        self._invalidate_installed_cache()
        after = self.installed_packages().get(package_name)

        if after is None:
            raise RuntimeError(
                f"Composer reported success, but package '{package_name}' is not installed afterwards."
            )

        changed = before != after

        if changed:
            if before is None:
                msg = f"Installed version {after}."
            else:
                msg = f"Updated from {before} to {after}."
        else:
            msg = f"Already installed in version {after}."

        return {
            "failed": False,
            "changed": changed,
            "msg": msg,
        }

    def remove_package(self, package_name: str) -> dict[str, Any]:
        """
        Remove a Composer package.

        Args:
            package_name:
                Composer package name.

        Returns:
            A per-package result dictionary.

        Raises:
            RuntimeError:
                If the Composer command fails or the package remains installed.
        """
        self.module.log("ComposerPackages::remove_package()")

        before = self.installed_packages().get(package_name)

        if before is None:
            return {
                "failed": False,
                "changed": False,
                "msg": "Already removed.",
            }

        args = self._composer_base_command() + [
            "global",
            "remove",
            package_name,
            "--no-interaction",
            "--no-audit",
            "--optimize-autoloader",
        ]

        rc, out, err = self._exec(args, env_vars=self._composer_environment())

        if rc != 0:
            raise RuntimeError(
                self._format_command_error(
                    action="remove",
                    package_name=package_name,
                    rc=rc,
                    out=out,
                    err=err,
                )
            )

        self._invalidate_installed_cache()
        after = self.installed_packages().get(package_name)

        if after is not None:
            raise RuntimeError(
                f"Composer reported success, but package '{package_name}' is still installed in version {after}."
            )

        return {
            "failed": False,
            "changed": True,
            "msg": f"Removed version {before}.",
        }

    def _manage_package(self, package: ComposerPackageSpec) -> dict[str, Any]:
        """
        Reconcile a single package declaration.

        Args:
            package:
                Parsed internal package specification.

        Returns:
            A per-package result dictionary.
        """
        self.module.log("ComposerPackages::_manage_package()")

        installed = self.installed_packages()
        installed_version = installed.get(package.name)

        if package.state == "absent":
            if installed_version is None:
                return {
                    "failed": False,
                    "changed": False,
                    "msg": "Already removed.",
                }

            return self.remove_package(package.name)

        if (
            not self.force
            and installed_version is not None
            and self._is_desired_version_already_installed(
                installed_version=installed_version,
                requested_release=package.release,
            )
        ):
            return {
                "failed": False,
                "changed": False,
                "msg": f"Already installed in version {installed_version}.",
            }

        return self.install_package(package.name, package.release)

    def _parse_package_definition(
        self, package: dict[str, Any], index: int
    ) -> ComposerPackageSpec:
        """
        Validate and normalize a raw package definition.

        Args:
            package:
                Raw package definition from module parameters.
            index:
                Zero-based list index used for error reporting.

        Returns:
            A validated internal package specification.

        Raises:
            ValueError:
                If the package definition is invalid.
        """
        self.module.log("ComposerPackages::_parse_package_definition()")

        if not isinstance(package, dict):
            raise ValueError(
                f"Package entry at index {index} must be a dictionary, got {type(package).__name__}."
            )

        name = str(package.get("name", "")).strip()
        release = package.get("release")
        state = str(package.get("state", "present")).strip().lower()

        if not name:
            raise ValueError(
                f"Package entry at index {index} is missing the 'name' field."
            )

        if state not in {"present", "absent"}:
            raise ValueError(
                f"Package '{name}' has unsupported state '{state}'. Supported values are 'present' and 'absent'."
            )

        if release is not None:
            release = str(release).strip() or None

        return ComposerPackageSpec(name=name, release=release, state=state)

    def _composer_base_command(self) -> list[str]:
        """
        Build the base Composer command.

        Returns:
            A command list that can execute Composer reliably.

        Notes:
            When the resolved Composer binary is a PHAR file or not executable,
            the PHP interpreter is used explicitly.
        """
        if self.composer_bin.endswith(".phar") or not os.access(
            self.composer_bin, os.X_OK
        ):
            return [self.php_bin, self.composer_bin]

        return [self.composer_bin]

    def _composer_environment(self) -> dict[str, str]:
        """
        Build environment variables for Composer command execution.

        Returns:
            A dictionary of environment variables used during command execution.
        """
        self.module.log("ComposerPackages::_composer_environment()")

        home = os.environ.get("HOME") or str(Path.home())

        raw_composer_home = os.environ.get("COMPOSER_HOME")
        if raw_composer_home:
            composer_home = Path(
                os.path.expandvars(os.path.expanduser(raw_composer_home))
            ).resolve(strict=False)
        else:
            composer_home = Path(home) / ".composer"

        environment = {
            "COMPOSER_ALLOW_SUPERUSER": "1",
            "HOME": home,
            "COMPOSER_HOME": str(composer_home),
        }

        self.module.log(f"-> environment: {environment}")

        return environment

    def _build_package_reference(
        self, package_name: str, package_release: Optional[str]
    ) -> str:
        """
        Build the Composer package reference string.

        Args:
            package_name:
                Composer package name.
            package_release:
                Optional version or constraint.

        Returns:
            Either C(vendor/package) or C(vendor/package:constraint).
        """
        if package_release:
            return f"{package_name}:{package_release}"

        return package_name

    def _is_desired_version_already_installed(
        self, installed_version: str, requested_release: Optional[str]
    ) -> bool:
        """
        Determine whether the current package version already satisfies the request.

        Args:
            installed_version:
                Currently installed package version.
            requested_release:
                Requested exact version or Composer constraint.

        Returns:
            C(True) when the module can safely skip execution for the package.

        Notes:
            Exact versions are compared directly after normalization. Non-exact
            constraints are intentionally treated as requiring reconciliation,
            because the installed version alone is insufficient to prove that the
            declared constraint is still what the user wants.
        """
        if not requested_release:
            return True

        if not self._is_exact_version(requested_release):
            return False

        return self._normalize_version(installed_version) == self._normalize_version(
            requested_release
        )

    def _is_exact_version(self, release: str) -> bool:
        """
        Check whether a release string represents an exact version.

        Args:
            release:
                Requested Composer release string.

        Returns:
            C(True) for exact versions, otherwise C(False).
        """
        return bool(self.EXACT_VERSION_PATTERN.match(release.strip()))

    @staticmethod
    def _normalize_version(version: str) -> str:
        """
        Normalize version strings for comparison.

        Args:
            version:
                Version string.

        Returns:
            The normalized version without a leading C(v).
        """
        return version.strip().lstrip("v")

    @staticmethod
    def _combine_output(out: str, err: str) -> str:
        """
        Combine stdout and stderr into a single normalized message.

        Args:
            out:
                Command stdout.
            err:
                Command stderr.

        Returns:
            A single stripped message string.
        """
        # self.module.log(f"ComposerPackages::_combine_output(out: {out}, err: {err})")

        return "\n".join(part.strip() for part in [out, err] if part and part.strip())

    def _format_command_error(
        self, action: str, package_name: str, rc: int, out: str, err: str
    ) -> str:
        """
        Format a Composer command failure message.

        Args:
            action:
                Human-readable action name.
            package_name:
                Composer package name.
            rc:
                Command return code.
            out:
                Command stdout.
            err:
                Command stderr.

        Returns:
            A formatted error message string.
        """
        combined_output = self._combine_output(out, err)
        return (
            f"Failed to {action} package '{package_name}' "
            f"(rc={rc}): {combined_output}"
        )

    def _ensure_global_composer_project(self) -> None:
        """
        Ensure that the global Composer home directory and composer.json exist.

        Raises:
            RuntimeError:
                If an existing composer.json is invalid.
        """
        self.module.log("ComposerPackages::_ensure_global_composer_project()")

        env_vars = self._composer_environment()
        composer_home = Path(env_vars["COMPOSER_HOME"])
        composer_home.mkdir(mode=0o755, parents=True, exist_ok=True)

        composer_json = composer_home / "composer.json"

        if not composer_json.exists():
            payload = {"require": {}}
            composer_json.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.module.log(f"  - created missing file: {composer_json}")
            return

        try:
            raw_content = composer_json.read_text(encoding="utf-8").strip()
            if not raw_content:
                payload = {"require": {}}
                composer_json.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                self.module.log(f"  - initialized empty file: {composer_json}")
                return

            parsed = json.loads(raw_content)
            if not isinstance(parsed, dict):
                raise RuntimeError(
                    f"The global composer.json at '{composer_json}' must contain a JSON object."
                )

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"The global composer.json at '{composer_json}' is invalid JSON: {exc}"
            ) from exc

    def _invalidate_installed_cache(self) -> None:
        """
        Invalidate the cached installed package list.
        """
        self._installed_cache = None

    def _exec(
        self,
        args: list[str],
        env_vars: Optional[dict[str, str]] = None,
        check_rc: bool = False,
    ) -> tuple[int, str, str]:
        """
        Execute a command through the Ansible module runtime.

        Args:
            args:
                Command and argument list.
            env_vars:
                Optional environment overrides.
            check_rc:
                When set to C(True), a non-zero return code raises a C(RuntimeError).

        Returns:
            A tuple containing return code, stdout, and stderr.

        Raises:
            RuntimeError:
                If C(check_rc) is enabled and the command exits with a non-zero
                return code.
        """
        self.module.log(
            f"ComposerPackages::_exec(args: {args}, env_vars: {env_vars}, check_rc: {check_rc})"
        )

        rc, out, err = self.module.run_command(
            args,
            environ_update=env_vars,
            check_rc=False,
        )

        if rc != 0:
            self.module.log(f"rc: {rc}")
            self.module.log(f"stdout: {out.strip()}")
            self.module.log(f"stderr: {err.strip()}")

            if check_rc:
                raise RuntimeError(self._combine_output(out, err))

        return rc, out, err


def main() -> None:
    """
    Ansible module entrypoint.
    """
    argument_spec = dict(
        packages=dict(
            default=[],
            type="list",
            elements="dict",
        ),
        force=dict(
            default=False,
            type="bool",
        ),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=False,
    )

    helper = ComposerPackages(module)
    result = helper.run()

    module.log(msg=f"result: {result}")

    if result.get("failed", False):
        module.fail_json(**result)

    module.exit_json(**result)


if __name__ == "__main__":
    main()
