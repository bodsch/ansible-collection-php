#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2022-2023, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

"""
Ansible module to manage PHP extensions through PECL/PEAR.

The module installs, checks, and removes PHP extensions via ``pecl``, writes the
extension activation ``.ini`` files, and manages the corresponding activation
symlinks. It keeps a per-extension checksum cache to detect already installed
extensions and returns a per-package result summary.
"""

from __future__ import annotations

import os
import re
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.bodsch.core.plugins.module_utils.checksum import Checksum
from ansible_collections.bodsch.core.plugins.module_utils.directory import (
    create_directory,
)
from ansible_collections.bodsch.core.plugins.module_utils.module_results import results
from ansible_collections.bodsch.php.plugins.module_utils.atomic_file import (
    AtomicFileWriter,
)

DOCUMENTATION = r"""
---
module: pecl

short_description: Manage PHP extensions with PECL

version_added: "1.0.0"

description:
  - Install, check, and remove PHP extensions through PECL/PEAR.
  - Write the extension activation INI files and manage the activation symlinks.
  - Keep a per-extension checksum cache to stay idempotent.

author:
  - Bodo Schulz

options:
  state:
    description:
      - The PECL operation to perform.
      - V(install) and V(check) evaluate O(packages).
    required: false
    type: str
    choices:
      - check
      - clear-cache
      - install
      - list
      - list-channels
      - list-upgrades
      - channel-update
      - upgrade
    default: list

  packages:
    description:
      - List of PHP extensions to manage.
    required: false
    type: list
    elements: dict
    default: []
    suboptions:
      name:
        description:
          - PECL package name of the extension.
        required: true
        type: str
      version:
        description:
          - Exact version to install.
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
      priority:
        description:
          - Numeric activation priority used in the symlink name.
        required: false
        type: int
        default: 80
      enabled:
        description:
          - Whether the extension should be activated.
        required: false
        type: bool
        default: true
      configure_options:
        description:
          - Answers to the extension's interactive C(pecl install) configure prompts.
          - The list entries are provided to PECL in prompt order; an empty entry
            keeps the default for that prompt.
          - Only used when the extension is actually built.
        required: false
        type: list
        elements: str

  php_config:
    description:
      - Locations used to write and link the extension activation files.
    required: false
    type: dict
    default: {}
    suboptions:
      module_dir:
        description:
          - Directory the C(<extension>.ini) activation file is written to.
        required: false
        type: str
      config_dirs:
        description:
          - Directories the activation symlinks are created in.
        required: false
        type: list
        elements: str

notes:
  - The module requires the C(pecl) and C(pear) binaries on the target host.
"""

EXAMPLES = r"""
- name: Update the PECL channel
  bodsch.php.pecl:
    state: channel-update

- name: Check which extensions are missing
  bodsch.php.pecl:
    state: check
    packages:
      - name: redis
      - name: xdebug

- name: Install extensions
  bodsch.php.pecl:
    state: install
    packages:
      - name: redis
        state: present
        enabled: true
    php_config:
      module_dir: /etc/php/8.2/mods-available
      config_dirs:
        - /etc/php/8.2/cli/conf.d
        - /etc/php/8.2/fpm/conf.d

- name: Install an extension with custom configure options
  bodsch.php.pecl:
    state: install
    packages:
      - name: memcached
        # answers to the interactive configure prompts, in order:
        # libmemcached dir, zlib dir, ...
        configure_options:
          - ""
          - "/usr"
    php_config:
      module_dir: /etc/php/8.2/mods-available
      config_dirs:
        - /etc/php/8.2/cli/conf.d
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

result:
  description:
    - Per-package result details, or the raw command output for simple states.
  returned: always
  type: raw

missing:
  description:
    - Extensions that are not installed yet.
  returned: when O(state=check)
  type: list
  elements: dict
"""


class PhpPecl:
    """
    Manage PHP PECL extensions on the target host.
    """

    def __init__(self, module: AnsibleModule) -> None:
        """
        Initialize the helper with module parameters and derived state.

        Args:
            module: The active Ansible module instance.
        """
        self.module = module
        self.module.log("PhpPecl::__init__()")

        self.check_mode: bool = module.check_mode

        self.state: str = module.params.get("state")
        self.packages: list[dict[str, Any]] = module.params.get("packages") or []
        php_config = module.params.get("php_config") or {}

        self.php_module_dir: str | None = php_config.get("module_dir")
        self.php_config_dirs: list[str] = php_config.get("config_dirs") or []

        self.pecl_bin: str = self.module.get_bin_path("pecl", True)
        self.pear_bin: str = self.module.get_bin_path("pear", True)

        self.cache_directory: str = "/var/cache/ansible/php_pecl"

        self.checksum = Checksum(self.module)
        self.php_extension_dir: str = ""

    def run(self) -> dict[str, Any]:
        """
        Dispatch the requested PECL operation.

        Returns:
            A standard Ansible result dictionary.
        """
        self.module.log("PhpPecl::run()")

        create_directory(self.cache_directory)

        result_state: list[dict[str, Any]] = []

        _, self.php_extension_dir, _ = self.php_information("extension_dir")
        self.module.log(f"  - extension dir '{self.php_extension_dir}'")

        if self.state == "channel-update":
            _, out, _ = self.__simple_pecl_command(["channel-update", "pecl.php.net"])
            return dict(changed=False, failed=False, result=out)

        if self.state == "install":
            result_state = self.__install()
            _, has_changed, has_failed, _, _, _ = results(self.module, result_state)
            return dict(changed=has_changed, failed=has_failed, result=result_state)

        if self.state == "check":
            result_state, packages = self.__check()
            _, has_changed, has_failed, _, _, _ = results(self.module, result_state)
            return dict(
                changed=has_changed,
                failed=has_failed,
                result=result_state,
                missing=packages,
            )

        if self.state == "clear-cache":
            _pecl_config = self.pecl_config()
            _pecl_dirs = self.filter_dir_keys(items=_pecl_config or [])
            self.module.log(f"  - dirs {_pecl_dirs}")

            cache_dir = [x for x in _pecl_dirs if x.get("key") == "cache_dir"][0]
            create_directory(cache_dir.get("value"))

            _, out, _ = self.__clear_cache()
            return dict(changed=False, failed=False, result=out)

        _, out, _ = self.__simple_pecl_command(self.state)
        return dict(changed=False, failed=False, result=out)

    def php_information(self, command: str | None = None) -> tuple[int, str, str]:
        """
        Query a PHP ini value through the ``php`` binary.

        Args:
            command: The ini setting to read, for example C(extension_dir).

        Returns:
            A tuple of return code, value, and stderr.
        """
        self.module.log(f"PhpPecl::php_information(command: {command})")

        php_bin = self.module.get_bin_path("php", True)
        args = [php_bin]

        if command:
            args.append("-r")
            args.append(f'echo ini_get("{command}");')

        self.module.log(f"  - args '{args}'")

        rc, out, err = self.__exec(args)

        return (rc, out.strip(), err)

    def pecl_information(self, package: str) -> tuple[str, str | None]:
        """
        Read the name and installed version of a PECL package.

        Args:
            package: The PECL package name.

        Returns:
            A tuple of package name and installed version (or C(None)).
        """
        self.module.log(f"PhpPecl::pecl_information(package: {package})")

        _name = package.lower()
        _version: str | None = None

        args = [self.pecl_bin, "info", package]

        self.module.log(f"  - args {args}")

        rc, out, err = self.__exec(args, check_rc=False)

        if rc == 0:
            regex_name = re.compile(r".*Name.* (?P<pecl_name>.*).*")
            regex_version = re.compile(r".*Release Version.* (?P<pecl_release>.*) \(.*\)")

            pecl_name = re.search(regex_name, out)
            pecl_version = re.search(regex_version, out)

            if pecl_name:
                _name = pecl_name.group("pecl_name")
            if pecl_version:
                _version = pecl_version.group("pecl_release")

        return _name, _version

    def pecl_config(self) -> list[dict[str, str]] | None:
        """
        Parse the output of ``pecl config-show``.

        Returns:
            A list of ``{"key": ..., "value": ...}`` dictionaries, or C(None) on error.
        """
        self.module.log("PhpPecl::pecl_config()")

        args = [self.pecl_bin, "config-show"]

        self.module.log(f"  - args {args}")

        rc, out, _ = self.__exec(args, check_rc=False)

        if rc != 0:
            return None

        parsed_data = self.parse_pecl_config(out)
        self.module.log(f"final: {parsed_data}")
        return parsed_data

    def parse_pecl_config(self, text: str) -> list[dict[str, str]]:
        """
        Parse the tabular output of ``pecl config-show`` into key/value pairs.

        Args:
            text: The raw command output.

        Returns:
            A list of ``{"key": ..., "value": ...}`` dictionaries.
        """
        self.module.log("PhpPecl::parse_pecl_config()")

        parsed: list[dict[str, str]] = []

        KEY = r"(?P<key>[A-Za-z][A-Za-z0-9_]*)"
        VAL = r"(?P<value>\S.*)"

        line_res = [
            # 1) label  (2+ spaces)  key  (2+ spaces)  value
            re.compile(rf"^\s*.*?\S\s{{2,}}{KEY}\s{{2,}}{VAL}\s*$"),
            # 2) label  (2+ spaces)  key  (1+ spaces)  value
            #    (fix for "preferred_mirror pecl.php.net")
            re.compile(rf"^\s*.*?\S\s{{2,}}{KEY}\s+{VAL}\s*$"),
            # 3) label  (1+ spaces)  key  (2+ spaces)  value
            #    (fix for "... directory cache_dir        /tmp/...")
            re.compile(rf"^\s*.*?\S\s+{KEY}\s{{2,}}{VAL}\s*$"),
        ]

        for line in text.splitlines():
            line = line.rstrip("\n")

            for rx in line_res:
                match = rx.match(line)
                if match:
                    parsed.append(
                        {
                            "key": match.group("key"),
                            "value": match.group("value").strip(),
                        }
                    )
                    break

        return parsed

    def filter_dir_keys(self, items: list[dict[str, str]]) -> list[dict[str, str]]:
        """
        Keep only the entries whose key denotes a directory.

        Args:
            items: Parsed PECL config entries.

        Returns:
            The subset of entries whose key ends with ``dir``.
        """
        self.module.log("PhpPecl::filter_dir_keys()")

        return [d for d in items if d["key"].endswith("_dir") or d["key"].endswith("dir")]

    def __simple_pecl_command(self, command: str | list[str]) -> tuple[int, str, str]:
        """
        Run a simple ``pecl`` command.

        Args:
            command: A single sub-command or a list of arguments.

        Returns:
            A tuple of return code, stdout, and stderr.
        """
        self.module.log(f"PhpPecl::__simple_pecl_command({command})")

        args = [self.pecl_bin]

        if isinstance(command, str):
            args.append(command)
        if isinstance(command, list):
            args += command

        self.module.log(f"  - args {args}")

        if self.check_mode:
            return (0, "", "")

        return self.__exec(args)

    def __install(self) -> list[dict[str, Any]]:
        """
        Install or remove all configured extensions.

        Returns:
            A per-package result list.
        """
        self.module.log("PhpPecl::__install()")

        result_state: list[dict[str, Any]] = []

        # Fix the temp_dir issue: pear config-set temp_dir <cache_directory>
        if not self.check_mode:
            self.__exec(
                [self.pear_bin, "config-set", "temp_dir", self.cache_directory]
            )

        for p in self.packages:
            res: dict[str, Any] = {}
            package_name = p.get("name")
            package_state = p.get("state", "present")
            package_priority = p.get("priority", 80)
            package_enabled = p.get("enabled", True)

            if package_name:
                _enabled = "enabled" if package_enabled else "disabled"
                self.module.log(
                    msg=f"- package {package_name} should be {package_state} and {_enabled}"
                )

                _name, _version = self.pecl_information(package_name)
                checksum = self.__check_pecl_package(_name)

                self.module.log(
                    f" - pecl {package_name} : {_name} / {_version} / {checksum}"
                )

                extension_present = False

                if package_state == "present":
                    if not checksum:
                        # extension is available but not installed yet
                        install_result = self.__install_pecl_package(p)
                        res[package_name] = install_result
                        extension_present = not install_result.get("failed", False)
                    else:
                        res[package_name] = dict(
                            changed=False, msg=f"{package_name} is already installed."
                        )
                        extension_present = True
                else:
                    res[package_name] = self.__uninstall_pecl_package(p)

                # Only activate an extension that is actually present. Enabling a
                # failed or removed extension would write an activation file for a
                # missing shared object, which makes PHP emit load warnings.
                if package_enabled and extension_present:
                    self.__enable_pecl_module(package_name, package_priority)
                elif not package_enabled:
                    self.__disable_pecl_module(package_name, package_priority)

            result_state.append(res)

        return result_state

    def __check(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Determine which of the configured extensions are missing.

        Returns:
            A tuple of the per-package result list and the list of missing packages.
        """
        self.module.log("PhpPecl::__check()")

        result_state: list[dict[str, Any]] = []

        pac = self.packages.copy()
        self.module.log(f"  - packages: {pac}")

        for p in self.packages:
            res: dict[str, Any] = {}
            self.module.log(f"    - {p}")

            package_name = p.get("name")
            package_state = p.get("state", "present")

            self.module.log(f"      package '{package_name}' should be {package_state}")

            if package_name:
                _name, _version = self.pecl_information(package_name)
                checksum = self.__check_pecl_package(_name)

                self.module.log(
                    f"      name: {_name}, version: {_version}, checksum: '{checksum}'"
                )

                if not _version and not checksum:
                    res[package_name] = dict(
                        installed=False,
                        changed=False,
                        msg=f"{package_name} is not installed.",
                    )
                elif _version and not checksum:
                    res[package_name] = dict(
                        installed=False,
                        changed=False,
                        msg=f"{package_name} is not installed.",
                    )
                elif not _version and checksum:
                    res[package_name] = dict(
                        installed=True,
                        changed=False,
                        failed=True,
                        msg=f"{package_name} is already installed, but not via pear.",
                    )
                    pac.remove(p)
                else:
                    res[package_name] = dict(
                        installed=True,
                        changed=False,
                        msg=f"{package_name} is already with version {_version} installed.",
                    )
                    pac.remove(p)

            result_state.append(res)

        return result_state, pac

    def __clear_cache(self) -> tuple[int, str, str]:
        """
        Clear the PECL download cache.

        Returns:
            A tuple of return code, stdout, and stderr.
        """
        self.module.log("PhpPecl::__clear_cache()")

        _, out, err = self.__simple_pecl_command("clear-cache")

        return (0, out.strip(), err.strip())

    def __check_pecl_package(self, package: str) -> str | None:
        """
        Return the checksum of an installed extension shared object.

        Args:
            package: The extension name.

        Returns:
            The checksum, or C(None) when the extension is not installed.
        """
        self.module.log(f"PhpPecl::__check_pecl_package(package: {package})")

        package_so_name = os.path.join(self.php_extension_dir, f"{package}.so")
        self.module.log(f"  - package_so_name: {package_so_name}")

        if os.path.isfile(package_so_name):
            checksum = self.checksum.checksum_from_file(package_so_name)
            self.module.log(f"    checksum {checksum}")
            return checksum

        return None

    @staticmethod
    def __configure_options_stdin(configure_options: Any) -> str | None:
        """
        Build the standard input for ``pecl install`` from configure options.

        ``pecl install`` asks for a package's configure options interactively,
        one prompt at a time, in the order the package defines them. To install
        non-interactively, the answers are written to standard input in that same
        order. An empty value lets PECL use the default for that prompt.

        Args:
            configure_options: A list of answers (one per prompt, in order) or a
                pre-formatted newline-separated string. C(None) or an empty value
                keeps the previous behaviour (all defaults).

        Returns:
            The newline-terminated standard input string, or C(None) when no
            configure options are provided.
        """
        if not configure_options:
            return None

        if isinstance(configure_options, (list, tuple)):
            answers = [str(option) for option in configure_options]
            return "\n".join(answers) + "\n"

        return str(configure_options).rstrip("\n") + "\n"

    def __install_pecl_package(self, package: dict[str, Any]) -> dict[str, Any]:
        """
        Install a single PECL extension.

        Args:
            package: The extension definition.

        Returns:
            A per-package result dictionary.
        """
        self.module.log(f"PhpPecl::__install_pecl_package(package: {package})")

        package_name = package.get("name")
        package_version = package.get("version")
        msg = f"installation of {package_name} failed."

        if package_version:
            package_name += f"-{package_version}"

        checksum_file = os.path.join(self.cache_directory, f"{package_name}.checksum")

        stdin_data = self.__configure_options_stdin(package.get("configure_options"))

        args = [self.pecl_bin, "install", package_name]
        self.module.log(f"  - args {args}")

        if self.check_mode:
            return dict(
                args=" ".join(args),
                failed=False,
                changed=True,
                msg=f"{package_name} would be installed.",
            )

        rc, out, err = self.__exec(args, data=stdin_data)

        if rc == 0:
            # build successful: store the checksum of the created shared object
            msg = f"{package_name} successful installed."

            _name, _version = self.pecl_information(package_name)
            checksum = self.__check_pecl_package(_name)

            self.checksum.write_checksum(checksum_file=checksum_file, checksum=checksum)
        else:
            detail = (err or out or "").strip()
            if detail:
                msg = f"installation of {package_name} failed: {detail}"

        return dict(
            rc=rc,
            args=" ".join(args),
            failed=rc != 0,
            changed=rc == 0,
            msg=msg,
        )

    def __uninstall_pecl_package(self, package: dict[str, Any]) -> dict[str, Any]:
        """
        Remove a PECL extension together with its checksum and config files.

        Args:
            package: The extension definition.

        Returns:
            A per-package result dictionary.
        """
        self.module.log(f"PhpPecl::__uninstall_pecl_package(package: {package})")

        package_name = package.get("name")
        package_priority = package.get("priority", 80)

        _changed = False
        _msg = f"{package_name} is not installed."

        checksum_file = os.path.join(
            self.cache_directory, f"{package_name.lower()}.checksum"
        )

        _name, _version = self.pecl_information(package_name)

        if _name and _version:
            args = [self.pecl_bin, "uninstall", package_name]
            self.module.log(f"  - args {args}")

            if self.check_mode:
                _changed = True
                _msg = f"{package_name} would be removed."
            else:
                rc, _, _ = self.__exec(args)
                if rc == 0:
                    _changed = True
                    _msg = f"{package_name} successful removed."

        self.__disable_pecl_module(package_name, package_priority, checksum_file)

        return dict(changed=_changed, msg=_msg)

    def __enable_pecl_module(self, package_name: str, package_priority: int) -> None:
        """
        Write the activation INI file and create the activation symlinks.

        Args:
            package_name: The extension name.
            package_priority: The numeric activation priority.
        """
        self.module.log(
            f"PhpPecl::__enable_pecl_module(package_name: {package_name}, package_priority: {package_priority})"
        )

        if not self.php_module_dir:
            self.module.log("  - no php_config.module_dir configured, skip enabling")
            return

        if not os.path.isdir(self.php_module_dir):
            # the target PHP installation does not provide a mods-available
            # directory (e.g. the SAPI is not installed); nothing to enable.
            self.module.log(
                f"  - module directory '{self.php_module_dir}' does not exist, skip enabling"
            )
            return

        if self.check_mode:
            return

        config_file = os.path.join(self.php_module_dir, f"{package_name.lower()}.ini")

        with AtomicFileWriter(destination=config_file, mode="w", encoding="utf-8") as fh:
            fh.write(f"extension={package_name.lower()}\n")

        for d in self.php_config_dirs:
            if not os.path.isdir(d):
                # the corresponding SAPI (e.g. fpm) is not installed on this
                # host, so its conf.d directory is absent; skip the activation link.
                self.module.log(
                    f"  - config directory '{d}' does not exist, skip activation link"
                )
                continue

            destination = os.path.join(d, f"{package_priority}-{package_name.lower()}.ini")
            self.__create_link(source=config_file, destination=destination)

    def __disable_pecl_module(
        self,
        package_name: str,
        package_priority: int,
        checksum_file: str | None = None,
    ) -> None:
        """
        Remove the activation INI file, symlinks, and optional checksum file.

        Args:
            package_name: The extension name.
            package_priority: The numeric activation priority.
            checksum_file: Optional checksum file to remove as well.
        """
        _files: list[str] = []

        if checksum_file:
            _files.append(checksum_file)

        if self.php_module_dir:
            _files.append(
                os.path.join(self.php_module_dir, f"{package_name.lower()}.ini")
            )

        for d in self.php_config_dirs:
            _files.append(
                os.path.join(d, f"{package_priority}-{package_name.lower()}.ini")
            )

        self.module.log(f"  - {_files}")

        if self.check_mode:
            return

        for f in _files:
            if os.path.isfile(f):
                os.remove(f)

    def __create_link(self, source: str, destination: str, force: bool = False) -> None:
        """
        Create an activation symlink idempotently.

        An existing non-symlink destination is preserved by renaming it to
        C(<destination>.DIST). An existing symlink is left untouched. This local
        implementation is intentionally kept instead of C(bodsch.core.create_link),
        which recreates the link unconditionally and would break idempotency.

        Args:
            source: The link target.
            destination: The link path to create.
            force: Recreate the link even if it already exists.
        """
        if force:
            os.remove(destination)
            os.symlink(source, destination)
            return

        if os.path.exists(destination) and not os.path.islink(destination):
            # keep a distribution-provided file around
            os.rename(destination, f"{destination}.DIST")

        if not os.path.islink(destination):
            os.symlink(source, destination)

    def __exec(
        self,
        commands: list[str],
        check_rc: bool = False,
        data: str | None = None,
    ) -> tuple[int, str, str]:
        """
        Execute a command through the Ansible module runtime.

        Args:
            commands: Command and argument list.
            check_rc: Whether Ansible should fail on a non-zero return code.
            data: Optional data written to the command's standard input.

        Returns:
            A tuple of return code, stdout, and stderr.
        """
        rc, out, err = self.module.run_command(commands, check_rc=check_rc, data=data)

        if rc != 0:
            self.module.log(f"  rc : '{rc}'")
            self.module.log(f"  out: '{out.strip()}'")
            self.module.log(f"  err: '{err.strip()}'")

        return rc, out, err


def main() -> None:
    """
    Entrypoint for the Ansible module.
    """
    args = dict(
        state=dict(
            type="str",
            choices=[
                "check",
                "clear-cache",
                "install",
                "list",
                "list-channels",
                "list-upgrades",
                "channel-update",
                "upgrade",
            ],
            default="list",
        ),
        packages=dict(required=False, default=[], type="list", elements="dict"),
        php_config=dict(required=False, default={}, type="dict"),
    )

    module = AnsibleModule(
        argument_spec=args,
        supports_check_mode=True,
    )

    state = module.params.get("state")
    packages = module.params.get("packages", [])
    php_config = module.params.get("php_config", {})

    module.log(msg=f"state      : {state}")
    module.log(msg=f"packages   : {packages}")
    module.log(msg=f"php_config : {php_config}")

    api = PhpPecl(module)
    result = api.run()

    module.log(msg=f"= result : {result}")

    if result.get("failed"):
        module.fail_json(**result)

    module.exit_json(**result)


if __name__ == "__main__":
    main()
