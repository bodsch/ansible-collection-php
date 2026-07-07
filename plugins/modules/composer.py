#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Ansible module to execute Composer commands (``install`` / ``update``) in a
project or global context.

The module resolves the options actually supported by the installed Composer
version via ``composer help <command> --format=json``, builds a minimal and
deterministic command line from the requested behaviour flags, executes
Composer, and derives the Ansible ``changed`` state from the command output.
"""

from __future__ import annotations

import re
import shlex
from typing import Any, Final

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r"""
---
module: composer

short_description: Run Composer install/update commands

version_added: "1.0.0"

description:
  - Execute C(composer install) or C(composer update) in a project or global context.
  - Automatically restrict passed options to those actually supported by the
    installed Composer version, based on C(composer help <command> --format=json).
  - Derive the Ansible C(changed) state from the Composer output.

author:
  - Bodo Schulz

options:
  command:
    description:
      - Composer command to execute.
    required: false
    type: str
    choices:
      - install
      - update
    default: install

  arguments:
    description:
      - Additional free-form arguments appended to the Composer command line.
      - Use this for positional arguments, e.g. specific package names to update.
      - Must not be used to pass the O(command) itself (whitespace is rejected).
    required: false
    type: str
    default: ""

  executable:
    description:
      - Path to the PHP interpreter used to run Composer.
      - When omitted, the C(php) binary is resolved from the C(PATH).
    required: false
    type: path
    aliases: [php_path]

  composer_executable:
    description:
      - Path to the C(composer.phar) / C(composer) executable.
      - When omitted, the C(composer) binary is resolved from the C(PATH).
    required: false
    type: path

  working_dir:
    description:
      - Working directory Composer operates in.
      - Ignored when O(global_command=true).
    required: false
    type: path

  global_command:
    description:
      - Execute the command in the Composer global context (C(composer global <command>)).
      - When enabled, O(working_dir) is ignored.
    required: false
    type: bool
    default: false

  prefer_source:
    description:
      - Install packages from source when available.
    required: false
    type: bool
    default: false

  prefer_dist:
    description:
      - Install packages from dist archives when available.
    required: false
    type: bool
    default: false

  no_dev:
    description:
      - Skip installation of packages listed in C(require-dev).
    required: false
    type: bool
    default: true

  no_scripts:
    description:
      - Skip execution of scripts defined in C(composer.json).
    required: false
    type: bool
    default: false

  no_plugins:
    description:
      - Disable installed Composer plugins.
    required: false
    type: bool
    default: false

  apcu_autoloader:
    description:
      - Use an APCu-based autoloader cache.
    required: false
    type: bool
    default: false

  optimize_autoloader:
    description:
      - Convert PSR-0/PSR-4 autoloading rules into a classmap for improved performance.
    required: false
    type: bool
    default: true

  classmap_authoritative:
    description:
      - Use a fully authoritative classmap. Implicitly enables O(optimize_autoloader).
    required: false
    type: bool
    default: false

  ignore_platform_reqs:
    description:
      - Ignore all platform requirement checks (PHP version, extensions, ...).
    required: false
    type: bool
    default: false

notes:
  - The module requires working C(php) and C(composer) binaries on the target host.
  - Only options actually supported by the resolved Composer command are passed
    on the command line; unsupported flags are silently skipped.
  - The module supports check mode only for Composer commands that themselves
    expose a C(--dry-run) option; otherwise the task is reported as skipped.
"""

EXAMPLES = r"""
- name: Install project dependencies (no dev dependencies)
  bodsch.php.composer:
    command: install
    working_dir: /var/www/app

- name: Update all dependencies with an optimized authoritative classmap
  bodsch.php.composer:
    command: update
    working_dir: /var/www/app
    no_dev: true
    optimize_autoloader: true
    classmap_authoritative: true

- name: Update a single package in the global context
  bodsch.php.composer:
    command: update
    global_command: true
    arguments: "vendor/package"
"""

RETURN = r"""
changed:
  description:
    - Indicates whether Composer reported any installed, updated, or removed packages.
  returned: always
  type: bool
  sample: true

msg:
  description:
    - Normalized Composer output (single line, whitespace-collapsed).
  returned: always
  type: str
  sample: "Nothing to install, update or remove"

stdout:
  description:
    - Raw combined stdout/stderr of the executed Composer command.
  returned: always
  type: str

failed:
  description:
    - Indicates whether the module execution failed.
  returned: always
  type: bool
  sample: false
"""


class Composer:
    """
    Execute Composer ``install`` / ``update`` commands.

    The class resolves which command-line options the installed Composer
    version actually supports for the requested command, builds a minimal and
    deterministic argument list from the module's boolean parameters, executes
    Composer, and derives the Ansible ``changed`` state from its output.
    """

    #: Options that are always requested when supported by the resolved command.
    _DEFAULT_OPTIONS: Final[tuple[str, ...]] = (
        "no-ansi",
        "no-interaction",
        "no-progress",
    )

    #: Mapping of boolean module parameters to their Composer long option name.
    _OPTION_PARAMS: Final[dict[str, str]] = {
        "prefer_source": "prefer-source",
        "prefer_dist": "prefer-dist",
        "no_dev": "no-dev",
        "no_scripts": "no-scripts",
        "no_plugins": "no-plugins",
        "apcu_autoloader": "apcu-autoloader",
        "optimize_autoloader": "optimize-autoloader",
        "classmap_authoritative": "classmap-authoritative",
        "ignore_platform_reqs": "ignore-platform-reqs",
    }

    #: Composer output fragments that indicate a no-op run.
    _NO_CHANGE_MARKERS: Final[tuple[str, ...]] = (
        "Nothing to install or update",
        "Nothing to install, update or remove",
    )

    def __init__(self, module: AnsibleModule) -> None:
        """
        Initialize the helper and resolve the PHP/Composer executables.

        Args:
            module:
                The Ansible module instance.
        """
        self.module = module

        self.command: str = module.params["command"]
        self.arguments: str = module.params["arguments"]
        self.working_dir: str | None = module.params.get("working_dir")
        self.global_command: bool = bool(module.params.get("global_command", False))

        # Resolved once, instead of on every composer_command() call.
        self.php_bin: str = module.params.get("executable") or module.get_bin_path(
            "php", required=True, opt_dirs=["/usr/local/bin"]
        )
        self.composer_bin: str = module.params.get(
            "composer_executable"
        ) or module.get_bin_path(
            "composer", required=True, opt_dirs=["/usr/local/bin"]
        )

    def run(self) -> dict[str, Any]:
        """
        Execute the requested Composer command.

        Returns:
            A standard Ansible result dictionary containing ``failed``,
            ``changed``, ``msg``, and, once Composer was actually executed,
            ``stdout``.
        """
        try:
            return self._run()
        except Exception as exc:  # noqa: BLE001
            return {
                "failed": True,
                "changed": False,
                "msg": str(exc),
            }

    def _run(self) -> dict[str, Any]:
        """
        Build the command line, execute Composer, and interpret its result.

        Returns:
            A standard Ansible result dictionary.

        Raises:
            ValueError:
                If ``command`` unexpectedly contains whitespace.
        """
        if re.search(r"\s", self.command):
            raise ValueError(
                "Use the 'arguments' param for passing arguments with the 'command'"
            )

        arguments = shlex.split(self.arguments)
        available_options = self.get_available_options(command=self.command)
        options = self._build_options(available_options)

        if self.module.check_mode:
            if "dry-run" in available_options:
                options.append("--dry-run")
            else:
                return {
                    "failed": False,
                    "changed": False,
                    "skipped": True,
                    "msg": (
                        f"command '{self.command}' does not support check mode, "
                        "skipping"
                    ),
                }

        rc, out, err = self.composer_command([self.command], arguments, options)

        if rc != 0:
            return {
                "failed": True,
                "changed": False,
                "msg": self.parse_out(err),
                "stdout": err,
            }

        # Composer versions newer than 1.0.0-alpha9 use stderr for standard
        # notification messages, so both streams are considered here.
        output = self.parse_out(out + err)

        return {
            "failed": False,
            "changed": self.has_changed(output),
            "msg": output,
            "stdout": out + err,
        }

    def _build_options(self, available_options: dict[str, Any]) -> list[str]:
        """
        Build the list of Composer CLI options from module parameters.

        Args:
            available_options:
                Options supported by the resolved Composer command, as returned
                by ``composer help <command> --format=json``.

        Returns:
            A list of ``--option`` strings to append to the Composer command line.
        """
        options: list[str] = [
            f"--{option}"
            for option in self._DEFAULT_OPTIONS
            if option in available_options
        ]

        for param, option in self._OPTION_PARAMS.items():
            if self.module.params.get(param) and option in available_options:
                options.append(f"--{option}")

        return options

    def composer_command(
        self,
        command: list[str],
        arguments: list[str] | None = None,
        options: list[str] | None = None,
    ) -> tuple[int, str, str]:
        """
        Assemble and execute a full Composer command line.

        Args:
            command:
                Composer subcommand, e.g. ``["install"]``.
            arguments:
                Additional positional arguments.
            options:
                Additional ``--option`` flags.

        Returns:
            A tuple of return code, stdout, and stderr.
        """
        options = list(options) if options else []
        arguments = list(arguments) if arguments else []

        if self.global_command:
            scope = ["global"]
        else:
            scope = []
            if self.working_dir:
                options.extend(["--working-dir", self.working_dir])

        cmd = [self.php_bin, self.composer_bin, *scope, *command, *options, *arguments]

        return self._exec(cmd)

    def get_available_options(self, command: str = "install") -> dict[str, Any]:
        """
        Resolve the options supported by a given Composer command.

        Args:
            command:
                Composer command to inspect, e.g. ``install`` or ``update``.

        Returns:
            The ``definition.options`` mapping from
            ``composer help <command> --format=json``.

        Raises:
            RuntimeError:
                If ``composer help`` fails or returns unparsable output.
        """
        rc, out, err = self.composer_command(
            ["help", command], arguments=["--no-interaction", "--format=json"]
        )

        if rc != 0:
            raise RuntimeError(self.parse_out(err))

        command_help_json = self.module.from_json(out)

        return command_help_json["definition"]["options"]

    @staticmethod
    def parse_out(text: str) -> str:
        """
        Collapse whitespace in Composer output for compact, stable messages.

        Args:
            text:
                Raw Composer output.

        Returns:
            The whitespace-collapsed, stripped output.
        """
        return re.sub(r"\s+", " ", text).strip()

    def has_changed(self, text: str) -> bool:
        """
        Derive the Ansible ``changed`` state from normalized Composer output.

        Args:
            text:
                Normalized Composer output, as returned by :meth:`parse_out`.

        Returns:
            ``False`` when Composer reported a no-op run, otherwise ``True``.
        """
        return not any(marker in text for marker in self._NO_CHANGE_MARKERS)

    def _exec(self, args: list[str]) -> tuple[int, str, str]:
        """
        Execute a command through the Ansible module runtime.

        Uses ``check_rc=False`` deliberately: non-zero return codes are
        interpreted by the calling method so that failures are reported with
        the module's own normalized ``msg``, instead of Ansible's generic
        ``run_command`` failure message.

        Args:
            args:
                Command and argument list.

        Returns:
            A tuple of return code, stdout, and stderr.
        """
        return self.module.run_command(args, check_rc=False)


def main() -> None:
    """
    Entrypoint for the Ansible module.
    """
    argument_spec = dict(
        command=dict(
            choices=["install", "update"],
            default="install",
            type="str",
        ),
        arguments=dict(default="", type="str"),
        executable=dict(type="path", aliases=["php_path"]),
        working_dir=dict(type="path"),
        global_command=dict(default=False, type="bool"),
        prefer_source=dict(default=False, type="bool"),
        prefer_dist=dict(default=False, type="bool"),
        no_dev=dict(default=True, type="bool"),
        no_scripts=dict(default=False, type="bool"),
        no_plugins=dict(default=False, type="bool"),
        apcu_autoloader=dict(default=False, type="bool"),
        optimize_autoloader=dict(default=True, type="bool"),
        classmap_authoritative=dict(default=False, type="bool"),
        ignore_platform_reqs=dict(default=False, type="bool"),
        composer_executable=dict(type="path"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    composer = Composer(module)
    result = composer.run()

    # module.log(msg=f"result: {result}")
    module.exit_json(**result)


if __name__ == "__main__":
    main()
