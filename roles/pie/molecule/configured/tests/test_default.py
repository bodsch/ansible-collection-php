# coding: utf-8
from __future__ import annotations, unicode_literals

import os

import pytest
import testinfra.utils.ansible_runner
from helper.molecule import get_vars, infra_hosts, local_facts

# --- tests -----------------------------------------------------------------


@pytest.mark.parametrize(
    "files",
    [
        "/usr/local/bin/pie",
        "/root/.ansible/pie/pie.sha256",
        "/etc/ansible/facts.d/pie.fact",
    ],
)
def test_files(host, files):
    f = host.file(files)
    assert f.exists


def test_pie_runs(host):
    cmd = host.run("php /usr/local/bin/pie --version --no-ansi")
    assert cmd.rc == 0


def test_extension_installed(host):
    cmd = host.run("php /usr/local/bin/pie show --no-ansi")
    assert cmd.rc == 0
    assert "asgrim/example-pie-extension" in cmd.stdout


def test_extension_loaded(host):
    cmd = host.run("php -m")
    assert "example_pie_extension" in cmd.stdout.lower()
