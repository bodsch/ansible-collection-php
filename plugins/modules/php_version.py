#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2020, Bodo Schulz <bodo@boone-schulz.de>
# BSD 2-clause (see LICENSE or https://opensource.org/licenses/BSD-2-Clause)

from __future__ import absolute_import, division, print_function
import re

from ansible.module_utils import distro
from ansible.module_utils.basic import AnsibleModule

__metaclass__ = type

ANSIBLE_METADATA = {
    'metadata_version': '0.1',
    'status': ['preview'],
    'supported_by': 'community'
}


class PHPVersion(object):
    """
        Main Class
    """
    module = None

    def __init__(self, module):
        """
          Initialize all needed Variables
        """
        self.module = module
        self.package = module.params.get("package")
        self.package_version = module.params.get("package_version")

        (self.distribution, self.version, self.codename) = distro.linux_distribution(
            full_distribution_name=False)

    def run(self):
        result = dict(
            failed=False,
            available_php_version="none"
        )

        version = ''
        error = True
        msg = f"not supported distribution: {self.distribution}."

        if self.distribution.lower() in ["redhat", "centos", "oracle", "fedora", "rocky", "almalinux"]:
            # error, version, msg = self._search_yum()
            return dict(
                failed=error,
                msg=msg
            )

        # self.module.log(msg=f"  distribution : '{self.distribution}'.")

        if self.distribution.lower() in ["redhat", "centos", "oracle", "fedora", "rocky", "almalinux"]:
            return dict(
                failed=True,
                msg=msg
            )

        if self.distribution.lower() in ["debian", "ubuntu"]:
            error, version, msg = self._search_apt()

        if self.distribution.lower() in ["arch", "artix"]:
            self.pacman_bin = self.module.get_bin_path('pacman', True)
            error, version, msg = self._search_pacman()

        package_version = version.replace('.', '')
        major_version = version.split('.')[0]

        version = dict(
            version=version,
            package_version=package_version,
            major_version=major_version
        )

        result = dict(
            failed=error,
            available=version,
            msg=msg
        )

        return result

    def _search_apt(self):
        """
            apt-cache show php | grep Version | sort | tail -n1 | awk -F'[:+]' '{print $3}' | tr -d '[:space:]'

            bionic provides PHP 7.2
            buster provides PHP 7.3
            stretch provides PHP 7.0
        """
        import apt

        version = ''

        cache = apt.cache.Cache()
        cache.update()
        cache.open()

        pkg = cache.get(self.package)

        # self.module.log(msg=f"pkg            : {pkg}")
        # self.module.log(msg=f"installed      : {pkg.is_installed}")
        # self.module.log(msg=f"virtual_package: {cache.is_virtual_package(self.package)}")
        # self.module.log(msg=f"shortname      : {pkg.shortname}")
        # self.module.log(msg=f"versions       : {pkg.versions}")

        if pkg:
            pattern = re.compile(r'^\d:(?P<version>[0-9.]+)\+.*')

            for pkg_version in pkg.versions:
                _version = pkg_version.version
                # self.module.log(
                #     msg=f" - version  : {_version} {type(_version)}")
                result = re.search(pattern, _version)

                if result:
                    version = result.group('version')
                # self.module.log(msg=f" - version  : {version}")
                if version.startswith(self.package_version):
                    break
                else:
                    version = ''

        # self.module.log(msg=f"version  : {version}")

        if version == '':
            return True, '', f"no php version {self.package_version} found."

        return False, version, ''

    def _search_pacman(self):
        """
            pacman support

            pacman --noconfirm --sync --search php7 | grep -E "^(extra|world)\/php7 (.*)\[installed\]" | cut -d' ' -f2
        """
        self.module.log(msg="= _search_pacman()")

        # match to
        #  extra/php 8.1.2-1
        #  extra/php7 7.4.27-1
        pattern = re.compile(
            r'^(?P<repository>extra|world)\/php[0-9 ]+(?P<version>\d\.\d).*-.*', re.MULTILINE)

        args = []
        args.append("--noconfirm")
        args.append("--sync")
        args.append("--search")
        args.append(self.package)

        rc, out, err = self._pacman(args)

        version = re.findall(pattern, out)

        # version = result.group(1)

        versions = []

        if version:
            if len(version) == 1:
                result = re.search(pattern, out)

                return False, result.group('version'), ""
            else:
                v = ""
                for _, v in version:
                    versions.append(v)

                    if v.startswith(self.package_version) or v == self.package_version:
                        break
                    else:
                        v = None

                if v is None and len(versions) == 0:
                    return True, "", f"package {self.package} in version {self.package_version} not found."
                elif v is None and len(versions) != 0:
                    return True, "", f"you want version {self.package_version}, but i found versions {versions}."
                else:
                    return False, v, ""
        else:
            return True, "", "not found"

    def _pacman(self, args):
        '''   '''
        cmd = [self.pacman_bin] + args

        self.module.log(msg=f"cmd: {cmd}")

        rc, out, err = self.module.run_command(cmd, check_rc=False)
        # self.module.log(msg="  rc : '{}'".format(rc))
        # self.module.log(msg="  out: '{}' ({})".format(out, type(out)))
        # self.module.log(msg="  err: '{}'".format(err))
        return rc, out, err


def main():

    argument_spec = dict(
        package=dict(
            required=False,
            default="php"
        ),
        package_version=dict(
            required=False,
            default=''
        ),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=False,
    )

    helper = PHPVersion(module)
    result = helper.run()

    module.log(msg=f" = result : '{result}'")

    module.exit_json(**result)


# import module snippets
if __name__ == '__main__':
    main()
