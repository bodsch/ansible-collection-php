#!/usr/bin/python3
# -*- coding: utf-8 -*-

# (c) 2022-2023, Bodo Schulz <bodo@boone-schulz.de>
# Apache-2.0 (see LICENSE or https://opensource.org/license/apache-2-0)
# SPDX-License-Identifier: Apache-2.0

from __future__ import absolute_import, print_function
import json
import os
import re
import time
import hashlib

from ansible.module_utils.basic import AnsibleModule

__metaclass__ = type

DOCUMENTATION = r"""
"""

EXAMPLES = r"""
"""

RETURN = r"""
"""

DEFAULT_ERROR_MSG = "De wereld is om zeep."


class Checksum():
    """
        TODO
        use collection bodsch.core
    """

    def __init__(self, module):
        self.module = module

    def checksum(self, plaintext, algorithm="sha256"):
        """
            compute checksum for plaintext
        """
        _data = self._harmonize_data(plaintext)

        checksum = hashlib.new(algorithm)
        checksum.update(_data.encode('utf-8'))

        return checksum.hexdigest()

    def validate(self, checksum_file, data=None):
        """
        """
        # self.module.log(msg=f" - checksum_file '{checksum_file}'")
        old_checksum = None

        if not isinstance(data, str) or not isinstance(data, dict):
            if not data and os.path.exists(checksum_file):
                os.remove(checksum_file)

        if os.path.exists(checksum_file):
            with open(checksum_file, "r") as f:
                old_checksum = f.readlines()[0]

        _data = self._harmonize_data(data)

        checksum = self.checksum(_data)
        changed = not (old_checksum == checksum)

        return (changed, checksum, old_checksum)

    def checksum_from_file(self, path, read_chunksize=65536, algorithm='sha256'):
        """
            Compute checksum of a file's contents.

        :param path: Path to the file
        :param read_chunksize: Maximum number of bytes to be read from the file
                                at once. Default is 65536 bytes or 64KB
        :param algorithm: The hash algorithm name to use. For example, 'md5',
                                'sha256', 'sha512' and so on. Default is 'sha256'. Refer to
                                hashlib.algorithms_available for available algorithms
        :return: Hex digest string of the checksum
        """

        if os.path.isfile(path):
            checksum = hashlib.new(algorithm)  # Raises appropriate exceptions.
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(read_chunksize), b''):
                    checksum.update(chunk)
                    # Release greenthread, if greenthreads are not used it is a noop.
                    time.sleep(0)

            return checksum.hexdigest()
        else:
            return None

    def write_checksum(self, checksum_file, checksum=None):
        """
        """
        with open(checksum_file, "w") as f:
            f.write(checksum)

    def _harmonize_data(self, data):
        """
        """
        if isinstance(data, dict):
            _data = json.dumps(data, sort_keys=True)

        if isinstance(data, list):
            _data = ''.join(str(x) for x in data)

        if isinstance(data, str):
            _data = data

        return _data


class PhpPecl(object):
    """
    Main Class
    """
    module = None

    def __init__(self, module):
        """
          Initialize all needed Variables
        """
        self.module = module

        # self.module.log(msg=f"module.params: {module.params}")

        self.state = module.params.get("state")
        self.packages = module.params.get("packages")
        php_config = module.params.get("php_config", None)

        self.php_module_dir = None
        self.php_config_dirs = []

        if php_config:
            self.php_module_dir = php_config.get("module_dir", None)
            self.php_config_dirs = php_config.get("config_dirs", [])

        self.pecl_bin = self.module.get_bin_path('pecl', True)
        self.pear_bin = self.module.get_bin_path('pear', True)

        self.cache_directory = "/var/cache/ansible/php_pecl"

    def run(self):
        """
        """
        _failed = True

        self.__create_directory(self.cache_directory)

        self.checksum = Checksum(self.module)

        result_state = []

        # checksum_file = os.path.join(self.cache_directory, "pecl.checksum")

        rc, self.php_extension_dir, err = self.php_information("extension_dir")

        self.module.log(msg=f"  - extension dir '{self.php_extension_dir}'")

        if self.state == "channel-update":
            """
            """
            rc, out, err = self.__simple_pecl_command(["channel-update", "pecl.php.net"])

            result = dict(
                changed = False,
                failed = False,
                result = out
            )

        elif self.state == "install":

            # changed, checksum, old_checksum = self.checksum.validate(
            #     checksum_file=checksum_file,
            #     data=self.packages
            # )
            #
            # if not changed:
            #     return dict(
            #         changed = False,
            #         msg = "The pecl configurations has not been changed."
            #     )

            result_state = self.__install()

            # define changed for the running tasks
            # migrate a list of dict into dict
            combined_d = {key: value for d in result_state for key, value in d.items()}
            # find all changed and define our variable
            changed = {k: v for k, v in combined_d.items() if isinstance(v, dict) if v.get('changed')}
            failed = {k: v for k, v in combined_d.items() if isinstance(v, dict) if v.get('failed')}

            _changed = (len(changed) > 0)
            _failed = (len(failed) > 0)

            # if not _failed:
            #     self.checksum.write_checksum(
            #         checksum_file=checksum_file,
            #         checksum=checksum
            #     )

            result = dict(
                changed = _changed,
                failed = _failed,
                result = result_state
            )
        elif self.state == "check":

            result_state, packages = self.__check()

            # define changed for the running tasks
            # migrate a list of dict into dict
            combined_d = {key: value for d in result_state for key, value in d.items()}
            # find all changed and define our variable
            changed = {k: v for k, v in combined_d.items() if isinstance(v, dict) if v.get('changed')}
            failed = {k: v for k, v in combined_d.items() if isinstance(v, dict) if v.get('failed')}
            # installed = [k for k, v in combined_d.items() if isinstance(v, dict) if not v.get('installed')]

            _changed = (len(changed) > 0)
            _failed = (len(failed) > 0)

            result = dict(
                changed = _changed,
                failed = _failed,
                result = result_state,
                missing = packages
            )

        else:
            rc, out, err = self.__simple_pecl_command(self.state)

            result = dict(
                changed = False,
                failed = False,
                result = out
            )

        return result

    def php_information(self, command=None):
        """
        """
        php_bin = self.module.get_bin_path('php', True)
        args = []
        args.append(php_bin)

        # php_config_bin = self.module.get_bin_path('php-config', True)
        # args = []
        # args.append(php_config_bin)

        if command:
            # args.append(command)
            args.append("-r")
            args.append(f"echo ini_get(\"{command}\");")

        # self.module.log(msg=f"  - args '{args}'")

        rc, out, err = self.__exec(args)

        # self.module.log(msg=f"  - {rc} - {out} - {err}")

        return (rc, out.strip(), err)

    def pecl_information(self, package):
        """
        """
        _name = package.lower()
        _version = None

        args = []
        args.append(self.pecl_bin)
        args.append("info")
        args.append(package)

        self.module.log(msg=f"  - args {args}")

        rc, out, err = self.__exec(args, check_rc=False)

        if rc == 0:
            regex_name = re.compile(r".*Name.* (?P<pecl_name>.*).*")
            regex_version = re.compile(r".*Release Version.* (?P<pecl_release>.*) \(.*\)")

            pecl_name = re.search(regex_name, out)
            pecl_version = re.search(regex_version, out)

            if pecl_name:
                _name = pecl_name.group('pecl_name')
            if pecl_name:
                _version = pecl_version.group('pecl_release')

        # self.module.log(msg=f"  - name {_name}")
        # self.module.log(msg=f"  - version {_version}")

        return _name, _version

    def __simple_pecl_command(self, command):
        """
        """
        self.module.log(msg=f"__simple_pecl_command({command})")

        args = []
        args.append(self.pecl_bin)

        if isinstance(command, str):
            args.append(command)

        if isinstance(command, list):
            args += command

        self.module.log(msg=f"  - args {args}")

        rc, out, err = self.__exec(args)

        return (rc, out, err)

    def __install(self):
        """
        """
        self.module.log(msg=f"__install()")

        result_state = []

        """
            fix temp_dir issue
        pear config-set temp_dir /root/tmp
        """
        args = []
        args.append(self.pear_bin)
        args.append("config-set")
        args.append("temp_dir")
        # args.append("--nobuild")
        args.append(self.cache_directory)

        self.module.log(msg=f"  - args {args}")

        rc, out, err = self.__exec(args)


        package_name = None
        for p in self.packages:
            """
            """
            res = {}
            package_name = p.get("name", None)
            package_state = p.get("state", "present")
            package_priority = p.get("priority", 80)
            package_enabled  = p.get("enabled", True)

            if package_name:
                self.module.log(msg=f"- package {package_name} should be {package_state} and {package_enabled}")

                _name, _version = self.pecl_information(package_name)
                checksum = self.__check_pecl_package(_name)

                self.module.log(f" - pecl {package_name} : {_name} / {_version} / {checksum}")

                if package_state == "present":
                    if not checksum:
                        """
                            present version == package are available
                            no checksum == package not installed
                        """
                        res[package_name] = self.__install_pecl_package(p)
                    else:
                        res[package_name] = dict(
                            changed = False,
                            msg = f"{package_name} is already installed."
                        )
                else:
                    res[package_name] = self.__uninstall_pecl_package(p)

                if package_enabled:
                    self.__enable_pecl_module(package_name, package_priority)
                else:
                    self.__disable_pecl_module(package_name, package_priority)

            result_state.append(res)

        return result_state

    def __check(self):
        """
        """
        self.module.log(msg=f"__check()")

        result_state = []

        pac = self.packages.copy()

        package_name = None
        for p in self.packages:
            """
            """
            res = {}
            package_name = p.get("name", None)
            package_state = p.get("state", "present")

            self.module.log(msg=f"- package {package_name} should be {package_state}")

            if package_name:
                _name, _version = self.pecl_information(package_name)
                checksum = self.__check_pecl_package(_name)

                self.module.log(msg=f"  - {_name} {_version} - {checksum}")

                if not _version and not checksum:
                    res[package_name] = dict(
                        installed = False,
                        changed = False,
                        msg = f"{package_name} is not installed.",
                    )

                elif _version and not checksum:
                    res[package_name] = dict(
                        installed = False,
                        changed = False,
                        msg = f"{package_name} is not installed.",
                    )

                elif not _version and checksum:
                    res[package_name] = dict(
                        installed = True,
                        changed = False,
                        failed = True,
                        msg = f"{package_name} is already installed, but not via pear."
                    )

                    pac.remove(p)

                else:
                    res[package_name] = dict(
                        installed = True,
                        changed = False,
                        msg = f"{package_name} is already with version {_version} installed."
                    )

                    pac.remove(p)

            result_state.append(res)

        # self.module.log(msg=f"= {result_state}, {pac}")

        return result_state, pac

    def __check_pecl_package(self, package):
        """
        """
        self.module.log(msg=f"__check_pecl_package({package})")

        package_so_name = os.path.join(
            self.php_extension_dir,
            f"{package}.so"
        )

        self.module.log(msg=f"  - package_so_name: {package_so_name}")

        if os.path.isfile(package_so_name):
            checksum = self.checksum.checksum_from_file(package_so_name)
            self.module.log(msg=f"    checksum {checksum}")
            return checksum

        return None

    def __install_pecl_package(self, package):
        """
        """
        self.module.log(msg=f"__install_pecl_package({package})")

        package_name = package.get("name", None)
        package_version = package.get("version", None)

        # package_state = package.get("state", "present")
        # package_priority = package.get("priority", 80)
        # package_enabled  = package.get("enabled", True)

        if package_version:
            package_name += f"-{package_version}"

        checksum_file = os.path.join(os.path.join(self.cache_directory, f"{package_name}.checksum"))

        args = []
        args.append(self.pecl_bin)
        args.append("install")
        # args.append("--soft")
        # args.append("--nobuild")
        args.append(package_name)

        self.module.log(msg=f"  - args {args}")

        rc, out, err = self.__exec(args)

        if rc == 0:
            """
                build successful
                next step:
                    - build checksum of created file
                    - enable module
            """
            msg = f"{package_name} successful installed."

            _name, _version = self.pecl_information(package_name)
            checksum = self.__check_pecl_package(_name)

            self.checksum.write_checksum(
                checksum_file=checksum_file,
                checksum=checksum
            )

        return dict(
            rc = rc,
            args = ' '.join(args),
            failed = False,
            changed = True,
            msg = msg
        )

    def __uninstall_pecl_package(self, package):
        """
            remove named pecl package and his corresponding checksum file and configs
        """
        package_name = package.get("name", None)
        package_priority = package.get("priority", 80)
        # package_enabled  = package.get("enabled", True)

        _changed = False
        _msg = f"{package_name} is not installed."

        checksum_file = os.path.join(os.path.join(self.cache_directory, f"{package_name.lower()}.checksum"))

        # get package informations
        _name, _version = self.pecl_information(package_name)

        if _name and _version:
            args = []
            args.append(self.pecl_bin)
            args.append("uninstall")
            args.append(package_name)

            self.module.log(msg=f"  - args {args}")

            rc, out, err = self.__exec(args)
            if rc == 0:
                _changed = True
                _msg = f"{package_name} successful removed."

        self.__disable_pecl_module(package_name, package_priority, checksum_file)

        return dict(
            changed = _changed,
            msg = _msg
        )

    def __enable_pecl_module(self, package_name, package_priority):
        """
            create config file and links
        """
        self.module.log(msg=f"__enable_pecl_module({package_name}, {package_priority})")
        # config file
        config_file = os.path.join(self.php_module_dir, f"{package_name.lower()}.ini")

        with open(config_file, 'w+') as outfile:
            outfile.write(f"extension={package_name.lower()}\n")

        # config links
        for d in self.php_config_dirs:
            destination = os.path.join(d, f"{package_priority}-{package_name.lower()}.ini")

            self.__create_link(source=config_file, destination=destination)

    def __disable_pecl_module(self, package_name, package_priority, checksum_file = None):
        """
            create config file and links
        """
        # files to remove ..
        _files = []
        if checksum_file:
            # checksum file
            _files.append(checksum_file)

        # config file
        _files.append(os.path.join(self.php_module_dir, f"{package_name.lower()}.ini"))
        # config links
        for d in self.php_config_dirs:
            _files.append(os.path.join(d, f"{package_priority}-{package_name.lower()}.ini"))

        self.module.log(f"  - {_files}")

        for f in _files:
            if os.path.isfile(f):
                os.remove(f)

    def __create_directory(self, dir):
        """
        """
        try:
            os.makedirs(dir, exist_ok=True)
        except FileExistsError:
            pass

        if os.path.isdir(dir):
            return True
        else:
            return False

    def __create_link(self, source, destination, force=False):
        """
        """
        if force:
            os.remove(destination)
            os.symlink(source, destination)
        else:
            if os.path.exists(destination):
                if not os.path.islink(destination):
                    # rename
                    os.rename(destination, f"{destination}.DIST")

            if not os.path.islink(destination):
                os.symlink(source, destination)

    def __exec(self, commands, check_rc=True):
        """
          execute shell program
        """
        rc, out, err = self.module.run_command(commands, check_rc=check_rc)

        if rc != 0:
            self.module.log(msg=f"  rc : '{rc}'")
            self.module.log(msg=f"  out: '{out}'")
            self.module.log(msg=f"  err: '{err}'")

        return rc, out, err


def main():
    """
    """
    args = dict(
        state=dict(
            type=str,
            choices=[
                "check",
                "clear-cache",
                "install",
                "list",
                "list-channels",
                "list-upgrades",
                "channel-update",
                "upgrade"
            ],
            default="list",
        ),
        packages=dict(
            required=False,
            default=[],
            type=list
        ),
        php_config=dict(
            required=False,
            default={},
            type=dict
        )
    )

    module = AnsibleModule(
        argument_spec=args,
        supports_check_mode=False,
    )

    state = module.params.get("state")
    packages = module.params.get("packages", [])
    php_config = module.params.get("php_config", {})

    module.log(msg=f"state      : {state}")
    module.log(msg=f"packages   : {packages}")
    module.log(msg=f"php_config : {php_config}")

    if state in ["install", "check"] and len(packages) == 0:
        module.fail_json(msg="install or check state requires packages")

    api = PhpPecl(module)
    result = api.run()

    module.log(msg=f"= result : {result}")

    module.exit_json(**result)


# import module snippets
if __name__ == '__main__':
    main()
