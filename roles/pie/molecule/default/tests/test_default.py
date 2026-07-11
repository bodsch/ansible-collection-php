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
        # "/usr/local/bin/pie.phar",
        "/usr/local/bin/pie",
        "/root/.cache/pie",
        "/root/.ansible/pie/pie.sha256",
        "/root/.ansible/pie/pie-installer.sha384",
        "/root/.ansible/pie/pie-installer.php",
    ],
)
def test_files(host, files):
    f = host.file(files)
    assert f.exists
