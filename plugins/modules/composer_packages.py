#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2024, Bodo Schulz <bodo@boone-schulz.de>

from __future__ import absolute_import, print_function

import json
import re

from ansible.module_utils.basic import AnsibleModule


class ComposerPackages(object):
    """ """

    module = None

    def __init__(self, module):
        """
        Initialize all needed Variables
        """
        self.module = module

        self.packages = module.params.get("packages")
        self.force = module.params.get("force", False)

        self.php_bin = module.get_bin_path("php", True)
        self.composer_bin = module.get_bin_path("composer", False)

    def run(self):
        """ """
        result = dict(failed=True, msg="De wereld is om zeep.")

        result = self.package_management()

        return result

    def package_management(self):
        """ """
        result_state = []

        installed_packages = self.installed_packages()

        for package in self.packages:
            res = {}
            package_name = package.get("name", None)
            package_release = package.get("release", None)
            package_state = package.get("state", "present")
            package_installed = False

            if not package_name:
                continue

            # self.module.log(msg=f"  - {package_name}")

            res[package_name] = dict()

            if package_name in installed_packages:
                package_installed = True
                _version = installed_packages.get(package_name)
                # self.module.log(msg=f"    is installed in version: {_version}")

                if package_release and package_release == _version:
                    _msg = f"is already installed in version {_version}."
                    res[package_name].update({"changed": False, "msg": _msg})
                else:
                    pass

            if package_installed and package_state == "absent":
                result = self.remove_package(package_name)
                res[package_name].update(
                    {"changed": result.get("changed"), "msg": result.get("msg")}
                )
            else:
                _msg = "is already removed."
                res[package_name].update({"changed": False, "msg": _msg})

            if package_state == "present":
                result = self.install_package(package_name, package_release)
                res[package_name].update(
                    {"changed": result.get("changed"), "msg": result.get("msg")}
                )

            if len(res) > 0:
                result_state.append(res)

        # define changed for the running tasks
        # migrate a list of dict into dict
        combined_d = {key: value for d in result_state for key, value in d.items()}
        # find all changed and define our variable
        changed = len({k: v for k, v in combined_d.items() if v.get("changed")}) > 0

        result = dict(changed=changed, failed=False, msg=result_state)

        return result

    def installed_packages(self):
        """ """
        installed = []

        args = []
        args.append(self.composer_bin)
        args.append("global")
        args.append("show")
        args.append("--installed")
        args.append("--format")
        args.append("json")

        rc, out, err = self._exec(args)

        if rc == 0:
            output = json.loads(out)
            installed = output.get("installed", [])

        return {x.get("name"): x.get("version") for x in installed}

    def install_package(self, package_name, package_release):
        """ """
        _changed = False
        _msg = "Nothing to install, update or remove."

        if not package_release:
            package_release = "@stable"

        package = f"{package_name}:{package_release}"

        args = []
        args.append(self.composer_bin)
        args.append("global")
        args.append("require")
        args.append(package)
        args.append("--no-progress")
        args.append("--no-interaction")
        args.append("--no-audit")
        args.append("--optimize-autoloader")

        rc, out, err = self._exec(args)

        if rc == 0:
            pattern = re.compile(
                r"Installing (?P<package>[a-zA-z\/].+) \((?P<version>[0-9\.]+)\).*",
                re.MULTILINE,
            )
            result = re.search(pattern, err)
            if result:
                _version = result.group("version")

                _changed = True
                _msg = f"successfull in version {_version} installed."
            else:
                pattern = re.compile(
                    r"Nothing to install, update or remove.*.*", re.MULTILINE
                )
                result = re.search(pattern, err)

                if result:
                    self.module.log(msg="  msg: 'Nothing to install, update or remove'")

        return dict(failed=(rc != 0), changed=_changed, msg=_msg)

    def remove_package(self, package):
        """ """
        args = []

        _changed = False
        _msg = f"{package} successfull removed."

        args.append(self.composer_bin)
        args.append("global")
        args.append("remove")
        args.append(package)
        args.append("--no-interaction")
        args.append("--no-audit")
        args.append("--optimize-autoloader")

        rc, out, err = self._exec(args)

        if rc == 0:
            pattern = re.compile(
                r".*Package operations:.*\n.*Removing (?P<package>[a-zA-z\/].+) \((?P<version>[0-9\.]+)\).*",
                re.MULTILINE,
            )
            result = re.search(pattern, err)
            if result:
                _version = result.group("version")
                _msg = f"version {_version} successfull removed."

            _changed = True

        return dict(failed=(rc != 0), changed=_changed, msg=_msg)

    def _exec(self, args, env_vars=None, check_rc=False):
        """ """
        rc, out, err = self.module.run_command(
            args, environ_update=env_vars, check_rc=check_rc
        )

        if int(rc) != 0:
            self.module.log(msg=f"  rc : '{rc}'")
            self.module.log(msg=f"  out: '{out}'")
            self.module.log(msg=f"  err: '{err}'")

        return rc, out, err


"""
COMPOSER_HOME=/root/.composer
/usr/local/bin/composer global show psr/cache --format json
/usr/local/bin/composer global require psr/cache:3.0.0 --no-audit --optimize-autoloader
/usr/local/bin/composer global remove psr/log --no-audit --optimize-autoloader
/usr/local/bin/composer global show --format json --installed
"""


def main():
    """ """
    argument_spec = dict(
        packages=dict(default="", type=list),
        force=dict(default=False, type=bool),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=False,
    )

    helper = ComposerPackages(module)
    result = helper.run()

    module.log(msg=f" = result : '{result}'")

    module.exit_json(**result)


# import module snippets
if __name__ == "__main__":
    main()
