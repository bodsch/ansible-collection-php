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

import glob
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union, cast

from ansible.module_utils import distro
from ansible.module_utils.basic import AnsibleModule

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

TPL_MODULE = """; generated by ansible
{% if item is defined %}
{{ item }}
{% endif %}
"""

# Example php -i output line:
#   extension_dir => /usr/lib/php/20230831 => /usr/lib/php/20230831
_EXT_DIR_RE = re.compile(
    r"^extension_dir\s*=>\s*(?P<configured>.*?)\s*=>",
    re.MULTILINE,
)

_EXTENSION_RE = re.compile(
    r"^(?P<ident>zend_extension|extension)\s*=\s*(?P<extension>[^\s;]+)",
    re.MULTILINE,
)

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


@dataclass(frozen=True)
class ModuleDefinition:
    """Normalized representation of a single PHP module entry."""

    name: str
    enabled: bool
    priority: int
    content: Optional[str]


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

        self.php_modules_cache_directory: str = str(
            Path.home() / ".ansible" / "cache" / "php"
        )

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
        if not self.__create_directory(self.php_modules_cache_directory):
            return {
                "failed": True,
                "changed": False,
                "msg": (
                    f"Unable to create cache directory "
                    f"'{self.php_modules_cache_directory}'."
                ),
            }

        extension_directory, err = self.find_extension_dir()
        if not extension_directory:
            return {"failed": True, "changed": False, "msg": err}

        result_state: List[Dict[str, Any]] = []

        if isinstance(self.php_modules, list):
            for module_definition in self.__iter_module_definitions(self.php_modules):
                module_result = self.__process_module(
                    module_definition=module_definition,
                    extension_directory=extension_directory,
                )
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

    def find_extension_dir(self) -> Tuple[Optional[str], Optional[str]]:
        """Determine the configured PHP extension directory.

        Returns:
            A tuple containing the detected extension directory and an optional
            error message.
        """
        if not self.php_binary:
            return None, "PHP does not appear to be installed in the default paths."

        rc, out, err = self.__exec([self.php_binary, "-i"], check_rc=False)
        if rc != 0:
            return None, err or "Unable to determine PHP extension directory."

        match = _EXT_DIR_RE.search(out)
        if not match:
            return None, "Unable to parse the PHP extension directory from 'php -i'."

        return match.group("configured").strip(), None

    def extension_available(
        self, extension_directory: str, module_content: Any
    ) -> bool:
        """Check whether the configured extension is available.

        Args:
            extension_directory: Directory containing PHP extension binaries.
            module_content: Raw INI content for a module.

        Returns:
            C(True) if the extension can be considered available, otherwise
            C(False).
        """
        if not isinstance(module_content, str) or not module_content.strip():
            return False

        match = _EXTENSION_RE.search(module_content)
        if not match:
            return False

        ident = match.group("ident").strip()
        extension = match.group("extension").replace(".so", "").strip()

        self.module.log(f"  - extension: {extension}")

        if ident == "zend_extension":
            return True

        search = glob.glob(os.path.join(extension_directory, f"{extension}.*"))
        if search:
            self.module.log(f"  - found: {search}")
            return True

        return False

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

    def write_module_configuration(
        self, module_name: str, file_name: str, data: Optional[str] = None
    ) -> bool:
        """Write or remove a PHP module configuration file.

        The method applies version-specific normalization before rendering and
        writing the final configuration content. Idempotency is preserved through
        checksum comparison.

        Args:
            module_name: Logical module name used for the checksum cache file.
            file_name: Destination file path of the module configuration.
            data: Raw module configuration content.

        Returns:
            True if the configuration file content changed, otherwise False.
        """
        checksum_file = os.path.join(
            self.php_modules_cache_directory, f"{module_name}.checksum"
        )

        if not data:
            changed = False

            if os.path.exists(file_name):
                os.remove(file_name)
                changed = True

            if os.path.exists(checksum_file):
                os.remove(checksum_file)
                changed = True

            return changed

        normalized_data = self.__normalize_module_content(module_name, data)
        rendered_data = self.__templated_data(normalized_data)

        changed, new_checksum, old_checksum = self.__has_changed(
            file_name, checksum_file, rendered_data
        )

        if changed:
            self.__write_template(
                data=rendered_data,
                data_file=file_name,
                checksum=new_checksum,
                checksum_file=checksum_file,
            )

        if os.path.exists(file_name):
            os.chmod(file_name, 0o0664)

        return changed

    def write_module_configuration_OLD(
        self,
        module_name: str,
        file_name: str,
        data: Optional[str] = None,
    ) -> bool:
        """Write or remove a module configuration file.

        Args:
            module_name: Logical module name used for the checksum cache file.
            file_name: Destination configuration file path.
            data: Raw INI content.

        Returns:
            C(True) when the filesystem state changed, otherwise C(False).
        """
        checksum_file = os.path.join(
            self.php_modules_cache_directory,
            f"{module_name}.checksum",
        )

        if not data:
            changed = False

            if os.path.exists(file_name):
                os.remove(file_name)
                changed = True

            if os.path.exists(checksum_file):
                os.remove(checksum_file)
                changed = True

            return changed

        rendered_data = self.__templated_data(data)
        changed, new_checksum, _old_checksum = self.__has_changed(
            file_name,
            checksum_file,
            rendered_data,
        )

        if changed:
            self.__write_template(
                data=rendered_data,
                data_file=file_name,
                checksum=new_checksum,
                checksum_file=checksum_file,
            )

        if os.path.exists(file_name):
            os.chmod(file_name, 0o0664)

        return changed

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
                    enabled=self.__strtobool(item.get("enabled", False)),
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
        module_file_name = os.path.join(
            self.php_modules_path,
            f"{module_definition.name}.ini",
        )

        module_link_names = [
            os.path.join(
                path,
                "conf.d",
                f"{module_definition.priority}-{module_definition.name}.ini",
            )
            for path in self.dest
        ]

        module_installed = self.extension_available(
            extension_directory=extension_directory,
            module_content=module_definition.content,
        )

        changed_write = self.write_module_configuration(
            module_definition.name,
            module_file_name,
            module_definition.content,
        )

        changed_enable = False
        changed_disable = False
        state_message: Optional[str] = None

        if changed_write:
            state_message = "Module successfully written."

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

        elif not module_definition.enabled or not module_installed:
            changed_disable = self.disable_module(module_link_names)

            if changed_disable:
                if not module_installed:
                    state_message = (
                        "Module is not installed and has therefore not been activated."
                    )
                else:
                    state_message = "Module successfully disabled."

        changed = changed_write or changed_enable or changed_disable

        result: Dict[str, Any] = {"changed": changed}
        if state_message:
            result["state"] = state_message

        return result

    def __write_template(
        self,
        data: str,
        data_file: str,
        checksum: str,
        checksum_file: str,
    ) -> None:
        """Write configuration and checksum files atomically.

        Args:
            data: Rendered configuration content.
            data_file: Destination configuration file path.
            checksum: Calculated checksum value.
            checksum_file: Destination checksum file path.
        """
        data_path = Path(data_file)
        data_path.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            "w",
            delete=False,
            dir=str(data_path.parent),
            encoding="utf-8",
        ) as file_handle:
            file_handle.write(data)
            tmp_name = file_handle.name

        os.replace(tmp_name, data_file)

        checksum_path = Path(checksum_file)
        checksum_path.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            "w",
            delete=False,
            dir=str(checksum_path.parent),
            encoding="utf-8",
        ) as file_handle:
            file_handle.write(checksum)
            tmp_checksum = file_handle.name

        os.replace(tmp_checksum, checksum_file)

    def __checksum(self, plaintext: str) -> str:
        """Compute a SHA-256 checksum for text content.

        Args:
            plaintext: Input text.

        Returns:
            Hex-encoded SHA-256 checksum.
        """
        return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

    def __templated_data(self, data: Any) -> str:
        """Render raw configuration content through the internal Jinja template.

        Args:
            data: Raw configuration content.

        Returns:
            Rendered template output as a string.
        """
        from jinja2 import Template

        template = Template(TPL_MODULE)
        return str(template.render(item=data))

    def __has_changed(
        self,
        data_file: str,
        checksum_file: str,
        rendered_data: str,
    ) -> Tuple[bool, str, str]:
        """Determine whether the target configuration content differs.

        Args:
            data_file: Destination configuration file path.
            checksum_file: Cached checksum file path.
            rendered_data: Newly rendered configuration content.

        Returns:
            Tuple of C(changed), C(new_checksum), and C(old_checksum).
        """
        old_checksum = ""

        if not os.path.exists(data_file) and os.path.exists(checksum_file):
            os.remove(checksum_file)

        if os.path.exists(checksum_file):
            with open(checksum_file, "r", encoding="utf-8") as file_handle:
                old_checksum = file_handle.readline().strip()

        new_checksum = self.__checksum(rendered_data)

        if self.force:
            return True, new_checksum, old_checksum

        file_checksum: Optional[str] = None
        if os.path.exists(data_file):
            with open(data_file, "r", encoding="utf-8") as file_handle:
                file_checksum = self.__checksum(file_handle.read())

        changed = (old_checksum != new_checksum) or (
            file_checksum is not None and file_checksum != new_checksum
        )

        return changed, new_checksum, old_checksum

    def __create_directory(self, directory: Union[str, Path]) -> bool:
        """Create a directory if needed and report whether it exists afterward.

        Args:
            directory: Target directory path.

        Returns:
            C(True) when the directory exists after the operation, otherwise
            C(False).
        """
        try:
            os.makedirs(str(directory), exist_ok=True)
        except OSError:
            return False

        return os.path.isdir(str(directory))

    def __strtobool(self, val: Any) -> bool:
        """Convert common truthy and falsy representations to bool.

        Args:
            val: Arbitrary value interpreted as a boolean.

        Returns:
            Normalized boolean value.

        Raises:
            ValueError: If the string value is not a known boolean representation.
        """
        if isinstance(val, bool):
            return val

        if isinstance(val, str):
            normalized = val.lower()

            if normalized in ("y", "yes", "t", "true", "on", "1"):
                return True

            if normalized in ("n", "no", "f", "false", "off", "0"):
                return False

            raise ValueError(f"invalid truth value {val}")

        return bool(val)

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

    def __normalize_module_content(
        self,
        module_name: str,
        data: str,
    ) -> str:
        """Normalize module configuration content for version-specific behavior.

        For PHP 8.5.x, the opcache extension must no longer be loaded explicitly via
        a zend_extension directive. Matching lines are removed while all other
        configuration lines remain unchanged.

        Args:
            module_name: Logical PHP module name.
            data: Raw module configuration content.

        Returns:
            Normalized configuration content.
        """
        if not self.__is_php_branch(8, 5):
            return data

        if module_name.lower() != "opcache":
            return data

        pattern = re.compile(
            r"(?im)^\s*zend_extension\s*=\s*opcache(?:\.so)?\s*(?:;.*)?\n?"
        )

        normalized = pattern.sub("", data)

        return normalized.strip() + "\n" if normalized.strip() else ""

    def __exec(
        self,
        args: Sequence[str],
        environ_update: Optional[Dict[str, str]] = None,
        check_rc: bool = True,
    ) -> Tuple[int, str, str]:
        """Execute a prepared command via Ansible's C(run_command()) helper.

        Args:
            args: Full argument vector.
            environ_update: Optional environment variables for the command.
            check_rc: Whether Ansible should fail on non-zero exit codes.

        Returns:
            Tuple of return code, stdout, and stderr.
        """
        rc, out, err = self.module.run_command(
            list(args),
            environ_update=environ_update,
            check_rc=check_rc,
        )

        return rc, out, err


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
