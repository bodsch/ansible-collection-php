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


def test_pie_is_executable(host):
    pie = host.file("/usr/local/bin/pie")
    assert pie.exists
    assert pie.mode & 0o111


def test_pie_runs(host):
    cmd = host.run("php /usr/local/bin/pie --version --no-ansi")
    assert cmd.rc == 0
