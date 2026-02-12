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
    package = "php-fpm"
    distribution = host.system_info.distribution

    _facts = local_facts(host=host, fact="php_fpm")

    print(distribution)

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
        f"/etc/php/{package_version}/fpm"
    ]

    if distribution in ["arch", "artix"]:

        if package_version == 7:
            directories = [
                f"/etc/php{package_version}/conf.d",
                f"/etc/php{package_version}/mods-available",
                f"/etc/php{package_version}/php-fpm.d",
            ]
        elif "legacy" in _facts.get("binary"):
            directories = [
                "/etc/php-legacy/conf.d",
                "/etc/php-legacy/mods-available",
                "/etc/php-legacy/php-fpm.d",
            ]
        else:
            directories = [
                "/etc/php/conf.d",
                "/etc/php/mods-available",
                "/etc/php/php-fpm.d",
            ]

    print(f"directory: {directories}")

    for dirs in directories:
        d = host.file(dirs)
        assert d.is_directory


def test_user(host, get_vars):
    """
    test service user and group
    """
    _facts = local_facts(host=host, fact="php_fpm")

    user = _facts.get("user")
    group = _facts.get("group")

    assert host.group(group).exists
    assert host.user(user).exists
    assert group in host.user(user).groups


def test_service(host):
    """
    is service running and enabled
    """
    _facts = local_facts(host=host, fact="php_fpm")

    print(_facts)
    service = host.service(_facts.get("daemon"))

    assert service.is_enabled
    assert service.is_running


def test_fpm_pools(host, get_vars):
    """
    test sockets
    """
    for i in host.socket.get_listening_sockets():
        print(i)

    for pool in get_vars.get("php_fpm_pools"):
        name = pool.get("name")
        listen = pool.get("listen")

        socket_name = listen.replace("$pool", name)

        print(socket_name)

        assert host.file(socket_name).exists
        assert host.socket(f"unix://{socket_name}").is_listening
