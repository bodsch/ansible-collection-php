# # coding: utf-8
# from __future__ import unicode_literals
#
# from ansible.parsing.dataloader import DataLoader
# from ansible.template import Templar
#
# import json
# import pytest
# import os
#
# import testinfra.utils.ansible_runner
#
# HOST = 'instance'
#
# testinfra_hosts = testinfra.utils.ansible_runner.AnsibleRunner(
#     os.environ['MOLECULE_INVENTORY_FILE']).get_hosts(HOST)
#
#
# def pp_json(json_thing, sort=True, indents=2):
#     if type(json_thing) is str:
#         print(json.dumps(json.loads(json_thing), sort_keys=sort, indent=indents))
#     else:
#         print(json.dumps(json_thing, sort_keys=sort, indent=indents))
#     return None
#
#
# def base_directory():
#     """
#     """
#     cwd = os.getcwd()
#
#     if 'group_vars' in os.listdir(cwd):
#         directory = "../.."
#         molecule_directory = "."
#     else:
#         directory = "."
#         molecule_directory = f"molecule/{os.environ.get('MOLECULE_SCENARIO_NAME')}"
#
#     return directory, molecule_directory
#
#
# def read_ansible_yaml(file_name, role_name):
#     """
#     """
#     read_file = None
#
#     for e in ["yml", "yaml"]:
#         test_file = f"{file_name}.{e}"
#         if os.path.isfile(test_file):
#             read_file = test_file
#             break
#
#     return f"file={read_file} name={role_name}"
#
#
# @pytest.fixture()
# def get_vars(host):
#     """
#         parse ansible variables
#         - defaults/main.yml
#         - vars/main.yml
#         - vars/${DISTRIBUTION}.yaml
#         - molecule/${MOLECULE_SCENARIO_NAME}/group_vars/all/vars.yml
#     """
#     base_dir, molecule_dir = base_directory()
#     distribution = host.system_info.distribution
#     operation_system = None
#
#     if distribution in ['debian', 'ubuntu']:
#         operation_system = "debian"
#     elif distribution in ['arch', 'artix']:
#         operation_system = f"{distribution}linux"
#
#     # print(" -> {} / {}".format(distribution, os))
#     # print(" -> {}".format(base_dir))
#
#     file_defaults = read_ansible_yaml(f"{base_dir}/defaults/main", "role_defaults")
#     file_vars = read_ansible_yaml(f"{base_dir}/vars/main", "role_vars")
#     file_distibution = read_ansible_yaml(f"{base_dir}/vars/{operation_system}", "role_distibution")
#     file_molecule = read_ansible_yaml(f"{molecule_dir}/group_vars/all/vars", "test_vars")
#     # file_host_molecule = read_ansible_yaml("{}/host_vars/{}/vars".format(base_dir, HOST), "host_vars")
#
#     defaults_vars = host.ansible("include_vars", file_defaults).get("ansible_facts").get("role_defaults")
#     vars_vars = host.ansible("include_vars", file_vars).get("ansible_facts").get("role_vars")
#     distibution_vars = host.ansible("include_vars", file_distibution).get("ansible_facts").get("role_distibution")
#     molecule_vars = host.ansible("include_vars", file_molecule).get("ansible_facts").get("test_vars")
#     # host_vars          = host.ansible("include_vars", file_host_molecule).get("ansible_facts").get("host_vars")
#
#     ansible_vars = defaults_vars
#     ansible_vars.update(vars_vars)
#     ansible_vars.update(distibution_vars)
#     ansible_vars.update(molecule_vars)
#     # ansible_vars.update(host_vars)
#
#     templar = Templar(loader=DataLoader(), variables=ansible_vars)
#     result = templar.template(ansible_vars, fail_on_undefined=False)
#
#     return result
#
#
# def local_facts(host=host, fact="php"):
#     """
#         return local fact
#     """
#     local_fact = host.ansible("setup").get("ansible_facts").get("ansible_local")
#
#     print(f"local_fact     : {local_fact}")
#
#     if local_fact:
#         return local_fact.get("php", {})
#     else:
#         return dict()

from __future__ import annotations, unicode_literals

import os

import testinfra.utils.ansible_runner
from helper.molecule import get_vars, infra_hosts, local_facts

# testinfra_hosts = infra_hosts(host_name="primary")

# local_facts(host=host, fact="php")

# --- tests -----------------------------------------------------------------

def test_installed_package(host, get_vars):
    """
        test insatlled package
    """
    package = 'php-cli'
    distribution = host.system_info.distribution

    _facts = local_facts(host=host, fact="php_fpm")

    # print(distribution)
    # print(_facts)

    if not distribution == "artix":
        if distribution == "arch":
            package_version = _facts.get("version").get("major")

            print(f"package_version: {package_version}")

            if package_version == 7:
                package = f"php{package_version}"
            else:
                package = "php-fpm"
                if "legacy" in _facts.get("binary"):
                    package = "php-legacy-fpm"

        p = host.package(package)
        assert p.is_installed


def test_installed_custom_package(host, get_vars):
    """
        custom packages
    """
    _facts = local_facts(host=host, fact="php_fpm")

    custom_packages = get_vars.get("php_packages")
    distribution = host.system_info.distribution

    if "legacy" in _facts.get("binary"):
        rewritten: List[str] = []
        for pkg in custom_packages:
            if "php-legacy" in pkg:
                rewritten.append(pkg)
            elif pkg.startswith("php"):
                rewritten.append(pkg.replace("php", "php-legacy", 1))
            else:
                rewritten.append(pkg)
        custom_packages = rewritten

    if not distribution == "artix":
        if custom_packages:
            for pkg in custom_packages:
                package = pkg

                p = host.package(package)
                assert p.is_installed


def test_directories(host, get_vars):
    """
        test created directories
    """
    distribution = host.system_info.distribution
    _facts = local_facts(host=host, fact="php_fpm")

    print(distribution)
    print(_facts.get("version"))

    package_version = _facts.get("version").get("full")

    directories = [
        f"/etc/php/{package_version}/cli",
    ]

    if distribution in ['arch', 'artix']:
        # global overwrite for arch
        directories = ["/etc/php/conf.d",]
        # package_version = local_facts(host=host, fact="php").get("version").get("major")

        if package_version == 7:
            directories = [
                f"/etc/php{major}/conf.d",
            ]
        elif "legacy" in _facts.get("binary"):
            directories = ["/etc/php-legacy/conf.d",]

    print(f"directory: {directories}")

    for dirs in directories:

        d = host.file(dirs)
        assert d.is_directory


def test_user(host, get_vars):
    """
        test service user and group
    """
    user = local_facts(host=host, fact="php").get("user")
    group = local_facts(host=host, fact="php").get("group")

    if group:
        assert host.user(user).exists
    if user:
        assert host.group(group).exists
    if user and group:
        assert group in host.user(user).groups
