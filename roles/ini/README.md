
# Ansible Role:  `bodsch.php.ini`

Ansible role to manage the `php.ini` configuration on various systems.

## Requirements

> **Note**
> This role reads the detected PHP version from the local fact
> `ansible_local.php.version`. Run `bodsch.php.php` (or `bodsch.php.fpm`) first
> so that fact is present.

## usage

```yaml
php_ini: []

```
