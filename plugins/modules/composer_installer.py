#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2024, Bodo Schulz <bodo@boone-schulz.de>

from __future__ import absolute_import, print_function

import os
import re
from pathlib import Path

import requests
import urllib3
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.bodsch.core.plugins.module_utils.cache.cache_valid import (
    cache_valid,
)
from ansible_collections.bodsch.core.plugins.module_utils.checksum import Checksum
from ansible_collections.bodsch.core.plugins.module_utils.directory import (
    create_directory,
)
from ansible_collections.bodsch.core.plugins.module_utils.file import create_link


class ComposerInstaller(object):
    """ """

    module = None

    def __init__(self, module):
        """
        Initialize all needed Variables
        """
        self.module = module

        self.signature = module.params.get("signature")
        self.installer = module.params.get("installer")
        self.version = module.params.get("version")
        self.version_branch = module.params.get("version_branch")
        self.update = module.params.get("update")
        self.path = module.params.get("path")
        self.force = module.params.get("force", False)

        self.cache_directory = f"{Path.home()}/.ansible/composer"
        self.composer_installer = os.path.join(
            self.cache_directory, "composer-installer.php"
        )
        self.composer_signature = os.path.join(
            self.cache_directory, "composer-installer.sha384"
        )

        self.php_bin = module.get_bin_path("php", True)
        self.composer_bin = module.get_bin_path("composer", False)
        self.composer_bin_checksum = os.path.join(
            self.cache_directory, "composer.sha256"
        )

        self.cache_minutes = 120

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def run(self):
        result = dict(failed=True, msg="De wereld is om zeep.")

        create_directory(self.cache_directory)

        self.checksum = Checksum(self.module)

        if bool(self.force):
            # self.module.log(msg=f"force mode: {self.force} {type(self.force)}")
            self.remove_file(self.composer_signature)
            self.remove_file(self.composer_installer)
            self.remove_file(self.composer_bin)
            self.remove_file(self.composer_bin_checksum)

        """
            check cached signature
        """
        if os.path.exists(self.composer_signature):
            out_of_cache_sign = cache_valid(
                self.module,
                cache_file_name=self.composer_signature,
                cache_minutes=self.cache_minutes,
            )

            if not out_of_cache_sign:
                self.validate_checksum(remove_changed=True)

        if not os.path.exists(self.composer_signature) or not os.path.exists(
            self.composer_installer
        ):
            """ """
            self.download_installer_files()
            self.validate_checksum(remove_changed=True)

        if os.path.exists(self.composer_installer):
            result = self.run_installer()

        return result

    def download_installer_files(self):
        """ """
        status_code, output = self.call_url(url=self.installer)

        if status_code == 200:
            with open(self.composer_installer, "w") as f:
                f.write(output)

        status_code, output = self.call_url(url=self.signature)

        if status_code == 200:
            with open(self.composer_signature, "w") as f:
                f.write(output)

    def validate_checksum(self, remove_changed=False):
        """ """
        old_checksum = ""

        checksum_from_file = self.checksum.checksum_from_file(
            path=self.composer_installer, algorithm="sha384"
        )

        if os.path.exists(self.composer_signature):
            with open(self.composer_signature, "r") as f:
                old_checksum = f.readlines()[0].strip()

        changed = not (old_checksum == checksum_from_file)

        if remove_changed and changed:
            self.remove_file(self.composer_signature)
            self.remove_file(self.composer_installer)

        return (changed, checksum_from_file, old_checksum)

    def composer_version(self):
        """ """
        args = []

        composer_version = ""
        composer_date = ""

        if self.composer_bin and os.path.exists(self.composer_bin):
            args.append(self.php_bin)
            args.append(self.composer_bin)
            args.append("--version")

            rc, out, err = self._exec(args)

            if rc == 0:
                pattern = re.compile(
                    r"^Composer version (?P<version>[0-9\.]+) (?P<date>.+)$"
                )

                result = re.search(pattern, out)
                composer_version = result.group("version")
                composer_date = result.group("date")

        return (composer_version, composer_date)

    def remove_file(self, filename):
        self.module.log(msg=f"remove_file({filename})")

        if filename and os.path.exists(filename):
            os.remove(filename)

    def run_installer(self):
        """ """
        args = []

        if self.composer_bin and os.path.exists(self.composer_bin):
            changed, checksum_from_file, old_checksum = (
                self.checksum.validate_from_file(
                    checksum_file=self.composer_bin_checksum,
                    data_file=self.composer_bin,
                )
            )

            composer_version, composer_date = self.composer_version()

            if not changed:
                return dict(failed=False, changed=False, version=composer_version)
        else:
            args.append(self.php_bin)
            args.append(self.composer_installer)
            args.append("--no-ansi")

            if self.version:
                args.append("--version")
                args.append(self.version)
            else:
                args.append(self.version_branch)

            args.append("--install-dir")
            args.append(self.path)

            rc, out, err = self._exec(args)

            if rc == 0:
                composer_bin_phar = self.module.get_bin_path("composer.phar", False)
                composer_bin_dest = os.path.join(self.path, "composer")

                if os.path.exists(composer_bin_phar) and not os.path.exists(
                    composer_bin_dest
                ):
                    create_link(source=composer_bin_phar, destination=composer_bin_dest)

        self.composer_bin = self.module.get_bin_path("composer", False)

        if os.path.exists(self.composer_bin) and not os.path.exists(
            self.composer_bin_checksum
        ):
            checksum = self.checksum.checksum_from_file(self.composer_bin)
            self.checksum.write_checksum(self.composer_bin_checksum, checksum)

            composer_version, composer_date = self.composer_version()

        return dict(failed=False, changed=True, version=composer_version)

    def call_url(self, url=None, method="GET", data=None):
        """ """
        response = None

        headers = {}

        try:
            # authentication = (self.github_username, self.github_password)

            if method == "GET":
                response = requests.get(
                    url,
                    headers=headers,
                    # auth=authentication
                )

            else:
                print("unsupported")
                pass

            response.raise_for_status()

            return response.status_code, response.text

        except requests.exceptions.HTTPError as e:
            self.module.log(msg=f"ERROR   : {e}")
            status_code = e.response.status_code
            status_message = e.response.text

            return status_code, status_message

        except ConnectionError as e:
            error_text = (
                f"{type(e).__name__} {(str(e) if len(e.args) == 0 else str(e.args[0]))}"
            )
            self.module.log(msg=f"ERROR   : {error_text}")
            return 500, error_text

        except Exception as e:
            self.module.log(msg=f"ERROR   : {e}")

            return response.status_code, response.text

    def _exec(self, args):
        """ """
        rc, out, err = self.module.run_command(args, check_rc=True)

        return rc, out, err


def main():
    """ """
    argument_spec = dict(
        signature=dict(
            required=False, default="https://composer.github.io/installer.sig", type=str
        ),
        installer=dict(
            required=False, default="https://getcomposer.org/installer", type=str
        ),
        version=dict(required=False, default="", type=str),
        version_branch=dict(required=False, default="--2", type=str),
        self_update=dict(required=False, default=False, type=bool),
        path=dict(default="/usr/local/bin", type=str),
        force=dict(default=False, type=bool),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=False,
    )

    helper = ComposerInstaller(module)
    result = helper.run()

    module.log(msg=f" = result : '{result}'")

    module.exit_json(**result)


# import module snippets
if __name__ == "__main__":
    main()
