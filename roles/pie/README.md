
# Ansible Role:  `bodsch.php.pie`

Ansible role to install [PIE](https://github.com/php/pie) (PHP Installer for
Extensions) and, optionally, PHP extensions with it. PIE is the designated
successor of PECL.

## Requirements

- A working PHP installation (PHP 8.1 or newer is required to run PIE itself).
- On Linux, build tooling to compile extensions. The role installs it via
  `pie_dependencies` (see the OS specific `vars/` files).

> **Note**
> Installing extensions targets a specific PHP version. When a role such as
> `bodsch.php.php` or `bodsch.php.fpm` has run before, the target PHP version is
> already present. Use `pie_php_config` to target a specific PHP installation.

## usage

```yaml
# Requested PIE version, empty installs the latest release.
pie_version: ""

# Force a reinstall even if PIE is already up to date.
pie_self_update: false

# Directory the PIE binary is installed into.
pie_install_path: /usr/local/bin

# Add pie_install_path to the global PATH via /etc/profile.d/pie.sh.
pie_add_to_path: false

# php-config of the target PHP installation (empty targets PIE's own PHP).
pie_php_config: ""

# Let PIE install missing build tools / system dependencies non-interactively.
pie_auto_install_build_tools: false
pie_auto_install_system_dependencies: false

# Remove the build dependencies again during cleanup.
pie_remove_build_dependencies: false

# PHP extensions to manage.
pie_packages: []
  # - name: xdebug/xdebug
  #   release: "^3.4"
  #   state: present
  # - name: asgrim/example-pie-extension
  #   state: absent
```

## options

| variable                              | default          | description |
| :------------------------------------ | :--------------- | :---------- |
| `pie_version`                         | `""`             | requested PIE version, empty installs the latest release |
| `pie_self_update`                     | `false`          | force a reinstall even if already satisfied |
| `pie_install_path`                    | `/usr/local/bin` | directory the `pie` binary is installed into |
| `pie_add_to_path`                     | `false`          | add `pie_install_path` to the global `PATH` |
| `pie_php_config`                      | `""`             | `php-config` of the target PHP installation |
| `pie_auto_install_build_tools`        | `false`          | let PIE install missing build tools non-interactively |
| `pie_auto_install_system_dependencies`| `false`          | let PIE install missing system dependencies non-interactively |
| `pie_remove_build_dependencies`       | `false`          | remove the build dependencies during cleanup |
| `pie_packages`                        | `[]`             | list of extensions to install or remove |

### `pie_packages`

Each entry describes one extension:

| key       | required | description |
| :-------- | :------- | :---------- |
| `name`    | yes      | Composer package name in `vendor/package` format |
| `release` | no       | version or Composer constraint, e.g. `1.2.3` or `^3.4` |
| `state`   | no       | `present` (default) or `absent` |
