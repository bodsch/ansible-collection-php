# coding: utf-8
from __future__ import annotations, unicode_literals

import os

import testinfra.utils.ansible_runner
from helper.molecule import get_vars, infra_hosts, local_facts

# --- tests -----------------------------------------------------------------


def test_installed_package(host, get_vars):
    """
    test insatlled package
    """
    package = "php-cli"
    distribution = host.system_info.distribution

    _facts = local_facts(host=host, fact="php")

    # print(distribution)
    # print(_facts)

    if not distribution == "artix":
        if distribution == "arch":
            package_version = _facts.get("version").get("major")

            print(f"package_version: {package_version}")

            if package_version == 7:
                package = f"php{package_version}"
            else:
                package = "php"
                if "legacy" in _facts.get("binary"):
                    package = "php-legacy"

        p = host.package(package)
        assert p.is_installed


def test_installed_custom_package(host, get_vars):
    """
    custom packages
    """
    _facts = local_facts(host=host, fact="php")

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
    _facts = local_facts(host=host, fact="php")

    print(distribution)
    print(_facts.get("version"))

    package_version = _facts.get("version").get("full")

    directories = [
        f"/etc/php/{package_version}/cli",
    ]

    if distribution in ["arch", "artix"]:
        # global overwrite for arch
        directories = [
            "/etc/php/conf.d",
        ]
        # package_version = local_facts(host=host, fact="php").get("version").get("major")

        if package_version == 7:
            directories = [
                f"/etc/php{major}/conf.d",
            ]
        elif "legacy" in _facts.get("binary"):
            directories = [
                "/etc/php-legacy/conf.d",
            ]

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
