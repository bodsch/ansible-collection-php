# Ansible Collection - bodsch.php

A collection of Ansible roles for PHP Stuff.


[![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-php/main.yml?branch=main)][ci]
[![GitHub issues](https://img.shields.io/github/issues/bodsch/ansible-collection-php)][issues]
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/bodsch/ansible-collection-php)][releases]

[ci]: https://github.com/bodsch/ansible-collection-php/actions
[issues]: https://github.com/bodsch/ansible-collection-php/issues?q=is%3Aopen+is%3Aissue
[releases]: https://github.com/bodsch/ansible-collection-php/releases


## supported operating systems

* Arch Linux
* Debian based
    - Debian 10 / 11
    - Ubuntu 20.10

## Contribution

Please read [Contribution](CONTRIBUTING.md)

## Development,  Branches (Git Tags)

The `master` Branch is my *Working Horse* includes the "latest, hot shit" and can be complete broken!

If you want to use something stable, please use a [Tagged Version](https://github.com/bodsch/ansible-collection-php/tags)!

---

## Roles

| Role                                                      | Build State | Description |
|:--------------------------------------------------------- | :---- | :---- |
| [bodsch.php.fpm](./roles/fpm/README.md)                   | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-php/fpm.yml?branch=main)][fpm]       | Ansible role to install and configure `fpm`. |
| [bodsch.php.pecl](./roles/pecl/README.md)                 | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-php/pecl.yml?branch=main)][pecl]       | Ansible role to install and configure `pecl`. |
| [bodsch.php.composer](./roles/composer/README.md)         | [![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/bodsch/ansible-collection-php/composer.yml?branch=main)][composer] | Ansible role to install and configure `composer`. |



[fpm]: https://github.com/bodsch/ansible-collection-php/actions/workflows/fpm.yml
[pecl]: https://github.com/bodsch/ansible-collection-php/actions/workflows/pecl.yml
[composer]: https://github.com/bodsch/ansible-collection-php/actions/workflows/composer.yml
