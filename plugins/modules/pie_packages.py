#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Ansible module for managing PHP extensions through PIE.

PIE (PHP Installer for Extensions) is the designated successor of PECL. This
module installs and removes PHP extensions for a target PHP installation using
the C(pie) command line interface. It is designed to be idempotent and returns
a per-package result summary aggregated through C(bodsch.core).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.bodsch.core.plugins.module_utils.module_results import results

DOCUMENTATION = r"""
---
module: pie_packages

short_description: Manage PHP extensions with PIE

version_added: "1.5.0"

description:
  - Install and remove PHP extensions for a target PHP installation using PIE.
  - Uses C(pie show) to determine the currently installed extensions, keeping
    module runs idempotent.
  - Returns a per-package result summary.

author:
  - Bodo Schulz

options:
  packages:
    description:
      - List of PHP extensions to manage.
      - Each entry defines the Composer package name, an optional version
        constraint, and the desired state.
    required: false
    type: list
    elements: dict
    default: []
    suboptions:
      name:
        description:
          - Composer package name of the extension in C(vendor/package) format.
        required: true
        type: str
      release:
        description:
          - Optional version constraint resolved with Composer semantics,
            for example C(1.2.3) or C(^3.4).
        required: false
        type: str
      state:
        description:
          - Desired extension state.
        required: false
        type: str
        choices:
          - present
          - absent
        default: present

  php_config:
    description:
      - Path to the C(php-config) binary of the target PHP installation.
      - Passed to PIE as C(--with-php-config) to install an extension for a
        specific PHP version.
      - When omitted, PIE targets the PHP version used to run PIE itself.
    required: false
    type: str

  executable:
    description:
      - Path to the C(pie) executable.
      - When omitted, the module resolves C(pie) from the system search path.
    required: false
    type: str

  skip_enable_extension:
    description:
      - Do not let PIE enable the extension in the PHP INI configuration.
    required: false
    type: bool
    default: false

  no_build_tools_check:
    description:
      - Skip the PIE build tools check entirely.
    required: false
    type: bool
    default: false

  auto_install_build_tools:
    description:
      - Allow PIE to install missing build tools non-interactively.
    required: false
    type: bool
    default: false

  no_system_dependencies_check:
    description:
      - Skip the PIE system library dependency check entirely.
    required: false
    type: bool
    default: false

  auto_install_system_dependencies:
    description:
      - Allow PIE to install missing system dependencies non-interactively.
    required: false
    type: bool
    default: false

  force:
    description:
      - Reinstall a package even when it already appears to be installed.
    required: false
    type: bool
    default: false

notes:
  - PIE must already be installed on the target host, see M(bodsch.php.pie_installer).
  - The target PHP installation must provide the build tools required by the
    extensions, unless O(auto_install_build_tools) is enabled.
"""

EXAMPLES = r"""
- name: Install two PHP extensions with PIE
  bodsch.php.pie_packages:
    packages:
      - name: xdebug/xdebug
      - name: asgrim/example-pie-extension

- name: Install an extension with a version constraint
  bodsch.php.pie_packages:
    packages:
      - name: xdebug/xdebug
        release: "^3.4"
        state: present

- name: Remove an extension
  bodsch.php.pie_packages:
    packages:
      - name: xdebug/xdebug
        state: absent

- name: Install an extension for a specific PHP version
  bodsch.php.pie_packages:
    php_config: /usr/bin/php-config8.3
    packages:
      - name: xdebug/xdebug
"""

RETURN = r"""
changed:
  description:
    - Indicates whether at least one extension was installed or removed.
  returned: always
  type: bool
  sample: true

failed:
  description:
    - Indicates whether the module execution failed.
  returned: always
  type: bool
  sample: false

msg:
  description:
    - Per-package result details keyed by package name.
  returned: always
  type: list
  elements: dict
"""


@dataclass(frozen=True)
class PiePackageSpec:
    """
    Internal extension definition used by the module logic.

    Attributes:
        name:
            Composer package name in C(vendor/package) format.
        release:
            Optional version constraint.
        state:
            Desired extension state.
    """

    name: str
    release: str | None = None
    state: str = "present"


class PiePackages:
    """
    Manage PHP extensions through the PIE command line interface.

    The class exposes a small public API used by the module entrypoint and keeps
    command execution, output parsing, and state comparison in private helpers.
    """

    PACKAGE_PATTERN: re.Pattern[str] = re.compile(
        # A composer package reference (vendor/package), not embedded in a
        # filesystem path such as ``/root/.pie/8.3/pie.json``.
        r"(?<![\w./@-])"
        r"(?P<name>[A-Za-z0-9](?:[A-Za-z0-9_.-]*)/[A-Za-z0-9](?:[A-Za-z0-9_.-]*))"
        r"(?:[:\s]+v?(?P<version>\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.\-]+)?))?"
    )

    # Informational lines emitted by ``pie show`` that never describe a package.
    _SKIP_LINE_MARKERS: tuple[str, ...] = ("pie.json", "Using ", "Tip:", "http")

    def __init__(self, module: AnsibleModule) -> None:
        """
        Initialize the PIE package manager helper.

        Args:
            module:
                The active Ansible module instance.
        """
        self.module = module
        self.module.log("PiePackages::__init__()")

        self.packages: list[dict[str, Any]] = module.params.get("packages") or []
        self.php_config: str | None = module.params.get("php_config")
        self.force: bool = bool(module.params.get("force", False))

        self.skip_enable_extension: bool = bool(module.params.get("skip_enable_extension", False))
        self.no_build_tools_check: bool = bool(module.params.get("no_build_tools_check", False))
        self.auto_install_build_tools: bool = bool(module.params.get("auto_install_build_tools", False))
        self.no_system_dependencies_check: bool = bool(module.params.get("no_system_dependencies_check", False))
        self.auto_install_system_dependencies: bool = bool(
            module.params.get("auto_install_system_dependencies", False)
        )

        executable = module.params.get("executable")
        self.pie_bin: str = executable or module.get_bin_path("pie", required=True)

        self._installed_cache: dict[str, str] | None = None

    def run(self) -> dict[str, Any]:
        """
        Reconcile all declared extensions.

        Returns:
            An Ansible-compatible result dictionary containing a per-package
            result summary.
        """
        self.module.log("PiePackages::run()")

        try:
            result_state: list[dict[str, dict[str, Any]]] = []
            self._invalidate_installed_cache()

            for index, raw_package in enumerate(self.packages):
                package = self._parse_package_definition(raw_package, index)
                package_result = self._manage_package(package)
                result_state.append({package.name: package_result})

            _, has_changed, has_failed, _, _, _ = results(self.module, result_state)

            return dict(
                changed=has_changed,
                failed=has_failed,
                msg=result_state,
            )

        except Exception as exc:  # noqa: BLE001
            return dict(
                changed=False,
                failed=True,
                msg=str(exc),
            )

    def installed_packages(self) -> dict[str, str]:
        """
        Return the PIE-managed extensions installed for the target PHP.

        Returns:
            A mapping of Composer package name to installed version. The version
            may be an empty string when PIE does not report one.

        Raises:
            RuntimeError:
                If the ``pie show`` command fails unexpectedly.
        """
        if self._installed_cache is not None:
            return dict(self._installed_cache)

        args = [self.pie_bin, "show", "--no-interaction", "--no-ansi"]
        args = self._with_php_config(args)

        rc, out, err = self._exec(args, check_rc=False)

        if rc != 0:
            combined = f"{out}\n{err}".strip()
            raise RuntimeError(f"Unable to list installed PIE extensions: {combined}")

        installed: dict[str, str] = {}
        for line in out.splitlines():
            if any(marker in line for marker in self._SKIP_LINE_MARKERS):
                continue

            match = self.PACKAGE_PATTERN.search(line)
            if match:
                installed[match.group("name")] = match.group("version") or ""

        self._installed_cache = installed
        return dict(installed)

    def install_package(self, package: PiePackageSpec) -> dict[str, Any]:
        """
        Install or update a single extension.

        Args:
            package:
                Parsed extension specification.

        Returns:
            A per-package result dictionary.

        Raises:
            RuntimeError:
                If the PIE command fails.
        """
        self.module.log(f"PiePackages::install_package(name={package.name})")

        before = self.installed_packages().get(package.name)

        if self.module.check_mode:
            changed = before is None or self.force
            return {
                "failed": False,
                "changed": changed,
                "state": "present",
                "msg": (
                    f"Would install {package.name}."
                    if changed
                    else f"{package.name} is already installed."
                ),
            }

        args = [self.pie_bin, "install", self._package_reference(package)]
        args = self._with_install_options(args)

        rc, out, err = self._exec(args, check_rc=False)

        if rc != 0:
            raise RuntimeError(self._format_error("install", package.name, rc, out, err))

        self._invalidate_installed_cache()
        after = self.installed_packages().get(package.name)

        if after is None:
            raise RuntimeError(
                f"PIE reported success, but extension '{package.name}' is not installed afterwards."
            )

        changed = before is None or before != after or self.force

        if before is None:
            msg = f"Installed {package.name} {after}.".strip()
        elif before != after:
            msg = f"Updated {package.name} from {before} to {after}.".strip()
        else:
            msg = f"{package.name} {after} is already installed.".strip()

        return {
            "failed": False,
            "changed": changed,
            "state": "present",
            "msg": msg,
        }

    def remove_package(self, package: PiePackageSpec) -> dict[str, Any]:
        """
        Remove a single extension.

        Args:
            package:
                Parsed extension specification.

        Returns:
            A per-package result dictionary.

        Raises:
            RuntimeError:
                If the PIE command fails or the extension remains installed.
        """
        self.module.log(f"PiePackages::remove_package(name={package.name})")

        before = self.installed_packages().get(package.name)

        if before is None:
            return {
                "failed": False,
                "changed": False,
                "state": "absent",
                "msg": f"{package.name} is already removed.",
            }

        if self.module.check_mode:
            return {
                "failed": False,
                "changed": True,
                "state": "absent",
                "msg": f"Would remove {package.name}.",
            }

        args = [self.pie_bin, "uninstall", package.name, "--no-interaction", "--no-ansi"]
        args = self._with_php_config(args)

        rc, out, err = self._exec(args, check_rc=False)

        if rc != 0:
            raise RuntimeError(self._format_error("uninstall", package.name, rc, out, err))

        self._invalidate_installed_cache()

        if self.installed_packages().get(package.name) is not None:
            raise RuntimeError(
                f"PIE reported success, but extension '{package.name}' is still installed."
            )

        return {
            "failed": False,
            "changed": True,
            "state": "absent",
            "msg": f"Removed {package.name} {before}.".strip(),
        }

    def _manage_package(self, package: PiePackageSpec) -> dict[str, Any]:
        """
        Reconcile a single extension declaration.

        Args:
            package:
                Parsed extension specification.

        Returns:
            A per-package result dictionary.
        """
        installed = self.installed_packages()
        installed_version = installed.get(package.name)

        if package.state == "absent":
            return self.remove_package(package)

        if (
            not self.force
            and installed_version is not None
            and self._version_satisfied(installed_version, package.release)
        ):
            return {
                "failed": False,
                "changed": False,
                "state": "present",
                "msg": f"{package.name} {installed_version} is already installed.".strip(),
            }

        return self.install_package(package)

    def _parse_package_definition(self, package: dict[str, Any], index: int) -> PiePackageSpec:
        """
        Validate and normalize a raw extension definition.

        Args:
            package:
                Raw extension definition from module parameters.
            index:
                Zero-based list index used for error reporting.

        Returns:
            A parsed :class:`PiePackageSpec`.

        Raises:
            ValueError:
                If the definition is invalid.
        """
        if not isinstance(package, dict):
            raise ValueError(f"Package definition at index {index} is not a mapping.")

        name = str(package.get("name") or "").strip()
        if not name:
            raise ValueError(f"Package definition at index {index} is missing a name.")

        state = str(package.get("state") or "present").strip()
        if state not in ("present", "absent"):
            raise ValueError(f"Invalid state '{state}' for package '{name}'.")

        release = package.get("release")
        release = str(release).strip() if release not in (None, "") else None

        return PiePackageSpec(name=name, release=release, state=state)

    def _package_reference(self, package: PiePackageSpec) -> str:
        """
        Build the PIE package reference, including an optional constraint.

        Args:
            package:
                Parsed extension specification.

        Returns:
            The ``vendor/package`` reference, optionally suffixed with
            ``:constraint``.
        """
        if package.release:
            return f"{package.name}:{package.release}"

        return package.name

    def _with_php_config(self, args: list[str]) -> list[str]:
        """
        Append the ``--with-php-config`` option when configured.

        Args:
            args:
                Command argument list.

        Returns:
            The argument list, possibly extended.
        """
        if self.php_config:
            args = args + [f"--with-php-config={self.php_config}"]

        return args

    def _with_install_options(self, args: list[str]) -> list[str]:
        """
        Append the configured non-interactive install options.

        Args:
            args:
                Base ``pie install`` argument list.

        Returns:
            The argument list extended with the configured options.
        """
        args = self._with_php_config(args)
        args = args + ["--no-interaction", "--no-ansi"]

        if self.skip_enable_extension:
            args.append("--skip-enable-extension")
        if self.no_build_tools_check:
            args.append("--no-build-tools-check")
        elif self.auto_install_build_tools:
            args.append("--auto-install-build-tools")
        if self.no_system_dependencies_check:
            args.append("--no-system-dependencies-check")
        elif self.auto_install_system_dependencies:
            args.append("--auto-install-system-dependencies")

        return args

    @staticmethod
    def _version_satisfied(installed_version: str, requested_release: str | None) -> bool:
        """
        Check whether the installed version satisfies an exact requested version.

        Only exact versions are compared here. Composer-style constraints (for
        example C(^3.4)) are delegated to PIE by reinstalling, because resolving
        them reliably requires PIE itself.

        Args:
            installed_version:
                The detected installed version.
            requested_release:
                The requested version or constraint, or C(None).

        Returns:
            C(True) when no reinstall is required, otherwise C(False).
        """
        if not requested_release:
            return True

        normalized_requested = requested_release.strip().lstrip("v")

        if not re.fullmatch(r"\d+(?:\.\d+){1,3}", normalized_requested):
            # Non-exact constraint: let PIE decide.
            return False

        normalized_installed = installed_version.strip().lstrip("v")

        return normalized_installed == normalized_requested or normalized_installed.startswith(
            f"{normalized_requested}."
        )

    def _exec(self, args: list[str], check_rc: bool = False) -> tuple[int, str, str]:
        """
        Execute a command through the Ansible module runtime.

        Args:
            args:
                Command and argument list.
            check_rc:
                Whether Ansible should fail on a non-zero return code.

        Returns:
            A tuple of return code, stdout, and stderr.
        """
        self.module.log(f"  args: {args}")

        return self.module.run_command(
            args,
            check_rc=check_rc,
            environ_update={"PIE_NO_INTERACTION": "1"},
        )

    @staticmethod
    def _format_error(action: str, package_name: str, rc: int, out: str, err: str) -> str:
        """
        Build a descriptive error message for a failed PIE command.

        Args:
            action:
                The attempted action, for example ``install``.
            package_name:
                The affected package name.
            rc:
                Return code of the command.
            out:
                Captured stdout.
            err:
                Captured stderr.

        Returns:
            A single-line error message.
        """
        detail = f"{out}\n{err}".strip()
        return f"Failed to {action} '{package_name}' (rc={rc}): {detail}"

    def _invalidate_installed_cache(self) -> None:
        """
        Drop the cached list of installed extensions.
        """
        self._installed_cache = None


def main() -> None:
    """
    Entrypoint for the Ansible module.
    """
    argument_spec = dict(
        packages=dict(required=False, default=[], type="list", elements="dict"),
        php_config=dict(required=False, type="str"),
        executable=dict(required=False, type="str"),
        skip_enable_extension=dict(required=False, default=False, type="bool"),
        no_build_tools_check=dict(required=False, default=False, type="bool"),
        auto_install_build_tools=dict(required=False, default=False, type="bool"),
        no_system_dependencies_check=dict(required=False, default=False, type="bool"),
        auto_install_system_dependencies=dict(required=False, default=False, type="bool"),
        force=dict(required=False, default=False, type="bool"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    helper = PiePackages(module)
    result = helper.run()

    module.log(msg=f"result: {result}")

    if result.get("failed"):
        module.fail_json(**result)

    module.exit_json(**result)


if __name__ == "__main__":
    main()
