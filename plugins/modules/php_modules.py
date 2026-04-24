#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Ansible module for managing PHP module configuration files and activation links.

This module writes PHP module configuration snippets, detects whether the
referenced PHP extension is available on the target system, and manages the
corresponding activation symlinks inside one or more PHP configuration roots.

The public helper API is intentionally kept stable while the internal structure
is improved for readability, typing, and more robust filesystem handling.
"""

# (c) 2022-2023, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

from __future__ import absolute_import, division, print_function

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union, cast

from ansible.module_utils import distro
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.bodsch.php.plugins.module_utils.php_dataclasses import (
    ModuleDefinition,
)
from ansible_collections.bodsch.php.plugins.module_utils.php_extension import (
    PhpExtension,
)
from ansible_collections.bodsch.php.plugins.module_utils.php_module import PhpModule
from ansible_collections.bodsch.php.plugins.module_utils.utils import strtobool

# ---------------------------------------------------------------------------------------

DOCUMENTATION = r"""
---
module: php_modules
short_description: Manage PHP module configuration files and activation symlinks
version_added: "1.0.0"

author:
  - Bodo Schulz (@bodsch) <bodo@boone-schulz.de>

description:
  - Manage PHP module configuration snippets and activation symlinks.
  - The module writes C(.ini) files into a module configuration directory.
  - It detects the active PHP extension directory by executing C(php -i).
  - Referenced extensions are only enabled when the extension binary exists or
    when the configuration contains a C(zend_extension) directive.
  - Existing symlinks in the target C(conf.d) directories are created, updated,
    or removed to match the requested state.
  - For PHP 8.5.x, the module removes C(zend_extension=opcache) and
    C(zend_extension=opcache.so) lines from the C(opcache) module content before
    writing the configuration file.

options:
  php_version:
    description:
      - PHP version used for version-specific configuration normalization.
      - Accepts values such as C(8.5), C(8.5.0), or C(8.5.3).
      - For PHP 8.5.x, explicit opcache C(zend_extension) lines are removed from
        the generated module configuration.
    type: str
    required: true

  php_modules:
    description:
      - List of PHP module definitions.
      - Each entry describes one module configuration file and its desired
        activation state.
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description:
          - Module name used for the generated C(.ini) file.
        type: str
        required: true
      enabled:
        description:
          - Whether the module should be enabled through symlinks in the target
            C(conf.d) directories.
        type: raw
        required: false
        default: false
      priority:
        description:
          - Numeric prefix used for the symlink name inside each C(conf.d)
            directory.
        type: int
        required: false
        default: 10
      content:
        description:
          - Raw INI content written into the module configuration file.
          - If omitted or empty, the configuration file is removed.
        type: str
        required: false

  php_modules_path:
    description:
      - Directory where module configuration files are written.
    type: str
    required: true

  dest:
    description:
      - List of PHP installation root directories.
      - For each entry, the module manages a symlink below C(conf.d).
      - Example result path: C(/etc/php/8.2/cli/conf.d/10-opcache.ini).
    type: list
    elements: str
    required: true

  force:
    description:
      - Force rewriting configuration files even when the checksum did not
        change.
    type: bool
    required: false
    default: false

notes:
  - This module does not support check mode.
  - The module uses Ansible's C(run_command()) helper to execute C(php -i).
  - The module creates a checksum cache below C(~/.ansible/cache/php).
  - If a module is enabled but the referenced PHP extension is not available,
    activation links are removed or kept absent.
  - Symlinks are created below the C(conf.d) subdirectory of each path listed
    in O(dest).

attributes:
  check_mode:
    support: none
"""

EXAMPLES = r"""
- name: Write and enable the opcache module for PHP 8.2
  bodsch.core.php_modules:
    php_version: "8.2.12"
    php_modules:
      - name: opcache
        enabled: true
        priority: 10
        content: |
          zend_extension=opcache.so
    php_modules_path: /etc/php/conf.avail
    dest:
      - /etc/php/8.2/apache2
      - /etc/php/8.2/cli

- name: Write opcache configuration for PHP 8.5 without explicit zend_extension
  bodsch.core.php_modules:
    php_version: "8.5.3"
    php_modules:
      - name: opcache
        enabled: true
        priority: 10
        content: |
          zend_extension=opcache.so
          opcache.enable=1
          opcache.memory_consumption=192
    php_modules_path: /etc/php/conf.avail
    dest:
      - /etc/php/8.5/apache2
      - /etc/php/8.5/cli

- name: Disable a PHP module in all target SAPIs
  bodsch.core.php_modules:
    php_version: "8.3"
    php_modules:
      - name: xdebug
        enabled: false
        priority: 20
        content: |
          zend_extension=xdebug.so
    php_modules_path: /etc/php/conf.avail
    dest:
      - /etc/php/8.3/apache2
      - /etc/php/8.3/cli

- name: Remove a configuration file by passing empty content
  bodsch.core.php_modules:
    php_version: "8.2"
    php_modules:
      - name: custom-module
        enabled: false
        content: ""
    php_modules_path: /etc/php/conf.avail
    dest:
      - /etc/php/8.2/cli

- name: Force rewrite of an existing module configuration
  bodsch.core.php_modules:
    php_version: "8.4"
    force: true
    php_modules:
      - name: redis
        enabled: true
        priority: 30
        content: |
          extension=redis
    php_modules_path: /etc/php/conf.avail
    dest:
      - /etc/php/8.4/fpm
      - /etc/php/8.4/cli
"""

RETURN = r"""
changed:
  description:
    - Indicates whether any module configuration file or activation symlink was changed.
  returned: always
  type: bool
  sample: true

failed:
  description:
    - Indicates whether module execution failed.
  returned: always
  type: always
  sample: false

msg:
  description:
    - Module execution result.
    - On success, this contains a per-module execution summary.
    - On failure, this may contain a plain error string instead.
  returned: always
  type: raw
  sample:
    - opcache:
        changed: true
        state: Module successfully written and enabled.
"""

# ---------------------------------------------------------------------------------------

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    try:
        from typing_extensions import Protocol  # type: ignore
    except ImportError:  # pragma: no cover
        Protocol = object  # type: ignore[misc,assignment]


class AnsibleModuleLike(Protocol):
    """Typing surface for the subset of AnsibleModule used by this helper."""

    params: Mapping[str, Any]

    def run_command(
        self,
        args: Sequence[str],
        cwd: Optional[str] = None,
        environ_update: Optional[Mapping[str, str]] = None,
        check_rc: bool = True,
    ) -> Tuple[int, str, str]:
        """Execute a command and return return code, stdout, and stderr."""

    def get_bin_path(self, arg: str, required: bool = False) -> Optional[str]:
        """Resolve a binary path from the remote execution environment."""

    def log(self, msg: str = "", **kwargs: Any) -> None:
        """Write a debug message to the Ansible log."""


class PHPModules(object):
    """Manage PHP module configuration files and activation symlinks.

    The class encapsulates all command execution and filesystem operations
    required to synchronize PHP module definitions with the requested state.

    Public method names, parameter types, and return types are intentionally
    preserved to keep the external API stable.
    """

    module: AnsibleModuleLike

    def __init__(self, module: AnsibleModuleLike):
        """Initialize the helper from an Ansible module instance.

        Args:
            module: Active Ansible module instance providing parameters,
                command execution, path resolution, and logging.
        """
        self.module = module

        self.php_modules: Any = module.params.get("php_modules")
        self.php_modules_path: str = str(module.params.get("php_modules_path"))
        self.dest: Sequence[str] = cast(Sequence[str], module.params.get("dest") or [])
        self.force: bool = bool(module.params.get("force", False))
        self.php_version = str(module.params.get("php_version", "")).strip()

        self.php_binary: Optional[str] = self.module.get_bin_path("php", False)

        self.distribution, self.version, self.codename = distro.linux_distribution(
            full_distribution_name=False
        )

        if str(self.distribution).lower() in ["archlinux", "arch"]:
            if "php-legacy" in self.php_modules_path:
                self.php_binary = self.module.get_bin_path("php-legacy", False)

    def run(self) -> Dict[str, Any]:
        """Execute the module logic and return an Ansible-compatible result.

        Returns:
            A result dictionary containing C(changed), C(failed), and C(msg).
        """
        # self.module.log("PHPModules::run()")

        if not self.php_binary:
            return {
                "failed": True,
                "changed": False,
                "msg": "PHP does not appear to be installed in the default paths.",
            }

        self.php_extension = PhpExtension(
            module=self.module,
            php_binary=self.php_binary,
        )

        extension_directory, err = self.php_extension.find_extension_dir()
        if not extension_directory:
            return {"failed": True, "changed": False, "msg": err}

        self.php_module = PhpModule(
            module=self.module,
            extension_directory=extension_directory,
            modules_path=self.php_modules_path,
            is_php_branch=self.__is_php_branch(8, 5),
        )

        result_state: List[Dict[str, Any]] = []

        if isinstance(self.php_modules, list):
            for module_definition in self.__iter_module_definitions(self.php_modules):

                module_result = self.__process_module(
                    module_definition=module_definition,
                    extension_directory=extension_directory,
                )

                # self.module.log(f"module_result: {module_result}")

                result_state.append({module_definition.name: module_result})

        changed = any(
            isinstance(item, dict)
            and isinstance(details, dict)
            and bool(details.get("changed"))
            for item in result_state
            for details in item.values()
        )

        result = {"changed": changed, "failed": False, "msg": result_state}

        self.module.log(msg=f"= result {result}")

        return result

    def create_link(self, source: str, destination: str, force: bool = False) -> None:
        """Create or replace a symlink.

        Args:
            source: Symlink source path.
            destination: Symlink destination path.
            force: Replace an existing symlink without preserving it.
        """
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        if force:
            try:
                destination_path.unlink()
            except FileNotFoundError:
                pass

            os.symlink(source, destination)
            return

        if destination_path.exists() or destination_path.is_symlink():
            if destination_path.is_symlink():
                destination_path.unlink()
            else:
                os.rename(destination, f"{destination}.DIST")

        os.symlink(source, destination)

    def enable_module(
        self,
        module_file_name: str,
        module_link_names: Sequence[str],
    ) -> Tuple[bool, Dict[str, Dict[str, Union[str, bool]]]]:
        """Ensure activation symlinks exist and point to the requested file.

        Args:
            module_file_name: Source configuration file.
            module_link_names: Destination symlink paths.

        Returns:
            A tuple containing a changed flag and per-link result details.
        """
        result: Dict[str, Dict[str, Union[str, bool]]] = {}
        changed = False

        for link in module_link_names:
            result[link] = {}

            if os.path.islink(link) and os.readlink(link) == module_file_name:
                result[link].update(
                    {"msg": "link exists and is valid", "changed": False}
                )
                continue

            if not os.path.islink(link):
                self.create_link(module_file_name, link)
            else:
                self.create_link(module_file_name, link, True)

            result[link].update({"msg": f"link {link} created", "changed": True})
            changed = True

        return changed, result

    def disable_module(self, module_link_names: Sequence[str]) -> bool:
        """Remove activation links or files for a PHP module.

        Args:
            module_link_names: Paths to remove.

        Returns:
            C(True) when at least one path was removed, otherwise C(False).
        """
        # self.module.log(
        #     f"PHPModules::disable_module(module_link_names: {module_link_names})"
        # )

        changed = False

        for link in module_link_names:
            if os.path.lexists(link):
                os.remove(link)
                changed = True

        return changed

    def __iter_module_definitions(self, items: Sequence[Any]) -> List[ModuleDefinition]:
        """Normalize raw module parameter entries into typed objects.

        Args:
            items: Raw entries from the Ansible parameter list.

        Returns:
            A list of normalized module definitions.
        """
        definitions: List[ModuleDefinition] = []

        for item in items:
            if not isinstance(item, Mapping):
                continue

            name = str(item.get("name") or "").strip()
            if not name:
                continue

            priority_raw = item.get("priority", 10)
            try:
                priority = int(priority_raw)
            except (TypeError, ValueError):
                priority = 10

            content_raw = item.get("content")
            content = str(content_raw) if content_raw is not None else None

            definitions.append(
                ModuleDefinition(
                    name=name,
                    enabled=strtobool(item.get("enabled", False)),
                    priority=priority,
                    content=content,
                )
            )

        return definitions

    def __process_module(
        self,
        module_definition: ModuleDefinition,
        extension_directory: str,
    ) -> Dict[str, Any]:
        """Synchronize one module definition and build its result payload.

        Args:
            module_definition: Normalized module definition.
            extension_directory: PHP extension directory detected from the system.

        Returns:
            Per-module result dictionary compatible with the current module output.
        """
        # self.module.log(
        #     f"PHPModules::__process_module(module_definition: {module_definition}, extension_directory: {extension_directory})"
        # )
        #
        # self.module.log(
        #     f"=> module: {module_definition.name} , enabled: {module_definition.enabled} , prio: {module_definition.priority}"
        # )

        changed: bool = False
        changed_write: bool = False
        changed_enable: bool = False
        changed_disable: bool = False
        state_message: Optional[str] = None

        module_file_name = os.path.join(
            self.php_modules_path,
            f"{module_definition.name}.ini",
        )

        if module_definition.content:
            """
            write module config
            """
            changed_write = self.php_module.write_module_configuration(
                module_definition=module_definition,
            )

        if changed_write:
            state_message = "Module configuration successfully written."

        # ------------------------------------------------------------------------------------------
        module_link_names = [
            os.path.join(
                path,
                "conf.d",
                f"{module_definition.priority}-{module_definition.name}.ini",
            )
            for path in self.dest
        ]

        module_installed = self.php_extension.extension_available(
            extension_directory=extension_directory,
            module_content=module_definition.content,
        )

        # self.module.log(
        #     f"=> module: {module_definition.name}, installed: {module_installed}"
        # )

        # deactivate module
        if not bool(module_definition.enabled) or not module_installed:
            """ """
            # self.module.log("    - disable module")
            changed_disable = self.disable_module(module_link_names)

            if changed_disable:
                if not module_installed:
                    state_message = (
                        "Module is not installed and has therefore not been activated."
                    )
                else:
                    changed = True
                    state_message = "Module successfully disabled."

            result: Dict[str, Any] = {"changed": changed}

            if state_message:
                result["state"] = state_message

        # ------------------------------------------------------------------------------------------
        # activate module
        if bool(module_definition.enabled) or module_installed:
            """ """
            # self.module.log("    - enable module")

            if module_definition.enabled and module_installed:
                changed_enable, _details = self.enable_module(
                    module_file_name,
                    module_link_names,
                )

                if changed_enable:
                    state_message = (
                        "Module successfully written and enabled."
                        if changed_write
                        else "Module successfully enabled."
                    )

            changed = changed_write or changed_enable or changed_disable

            result: Dict[str, Any] = {"changed": changed}
            if state_message:
                result["state"] = state_message

        if bool(module_definition.enabled) and not module_installed:
            """ """
            state_message = "The module should be enabled, but it is not installed."

            result: Dict[str, Any] = {
                "changed": False,
                "failed": True,
                "state": state_message,
            }

        # self.module.log(f"= result: {result}")

        return result

    def __php_version_tuple(self) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """Parse the configured PHP version into major, minor, and patch numbers.

        The parser is intentionally tolerant and accepts values such as:
        - "8.5"
        - "8.5.3"
        - " 8.5.3 "
        - "php-8.5.3"

        Returns:
            A tuple of (major, minor, patch). Missing components are returned as
            None. If no version numbers can be extracted, all values are None.
        """
        if not self.php_version:
            return None, None, None

        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", self.php_version)
        if not match:
            return None, None, None

        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3)) if match.group(3) is not None else None

        return major, minor, patch

    def __is_php_branch(self, major: int, minor: int) -> bool:
        """Check whether the configured PHP version belongs to a specific branch.

        Args:
            major: Expected PHP major version.
            minor: Expected PHP minor version.

        Returns:
            True if the configured version matches the requested major/minor branch,
            otherwise False.
        """
        current_major, current_minor, _ = self.__php_version_tuple()
        return current_major == major and current_minor == minor


def main() -> None:
    """Create the Ansible module instance and execute the helper."""
    specs = dict(
        php_version=dict(required=True, type="str"),
        php_modules=dict(required=True, type="list"),
        php_modules_path=dict(required=True, type="str"),
        dest=dict(required=True, type="list"),
        force=dict(required=False, type="bool", default=False),
    )

    module = AnsibleModule(
        argument_spec=specs,
        supports_check_mode=False,
    )

    helper = PHPModules(module)
    result = helper.run()

    module.log(msg=f" = result : '{result}'")
    module.exit_json(**result)


if __name__ == "__main__":
    main()
