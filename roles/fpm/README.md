
# Ansible Role:  `bodsch.php.fpm`

Ansible role to install fpm-php on various systems.

Only inspired by [geerlingguy](https://github.com/geerlingguy/ansible-role-php)

Detect available PHP Version based on `php_version` Variable.

Supports PHP version 7 and 8, **as long as the corresponding versions are available.**

ArchLinux has removed the PHP 7 packages from their repository!

> **Note**
> This role does **not** manage `php.ini`. Use the `bodsch.php.ini` role for
> `php.ini` (it supports global and per-SAPI configuration via `php_ini` /
> `php_ini_sapi`). This role manages `php-fpm.conf`, pools, PHP modules and the
> service.


## usage

```yaml
# choose your version!
php_version: "8"

php_packages_state: present

php_fpm_log_directory: /var/log/php-fpm
php_fpm_tmp_upload_directory: /tmp/php-fpm
php_fpm_socket_directory: /run/php

php_fpm_log_level: notice

php_enable_php_fpm: true

php_fpm_listen: "127.0.0.1:9000"
php_fpm_listen_allowed_clients: "127.0.0.1"
php_fpm_pm:
  max_children: 50
  start_servers: 5
  spare_servers:
    min: 5
    max: 5

php_packages: []

php_fpm_default_pool:
  delete: false
  name: www.conf

php_fpm_pools: []

# php modules
php_modules: []
```

### custom packages

To install more PHP packages, you can find a list at `php_packages` specify.

E.G.:

```yaml
php_packages:
  - php-ldap
```

The packages do not require version information, as it would be necessary for RedHat and Remis packages,
for example. The role takes care that the package name is valid.

As an example, `php-ldap` would be `php73-php-ldap`.


### php pools

```yaml
php_fpm_pools:
  - name: worker-01
    user: "{{ php_fpm_pool_user }}"
    group: "{{ php_fpm_pool_group }}"
    listen.owner: "{{ php_fpm_pool_user }}"
    listen.group: "{{ php_fpm_pool_group }}"
    listen: "{{ php_fpm_socket_directory }}/$pool.sock"
    # static, dynamic or ondemand
    pm: ondemand
    pm.max_children: 10
    pm.start_servers: 4
    pm.min_spare_servers: 2
    pm.max_spare_servers: 6
    pm.status_path: /status

  - name: worker-02
    user: "{{ php_fpm_pool_user }}"
    group: "{{ php_fpm_pool_group }}"
    listen.owner: "{{ php_fpm_pool_user }}"
    listen.group: "{{ php_fpm_pool_group }}"
    listen: "{{ php_fpm_socket_directory }}/$pool.sock"
    pm: dynamic
    pm.max_children: 10
    pm.start_servers: 4
    pm.min_spare_servers: 2
    pm.max_spare_servers: 6
    pm.status_path: /status
    ping.path: /ping
    ping.response: pong
    access.log: "{{ php_fpm_log_directory }}/$pool_access.log"
    access.format: "%R - %n - %{HTTP_HOST}e - %u %t \"%m %r [%Q%q]\" %s %f %{mili}d %{kilo}M %C%%"
    chdir: /
    env:
      PATH: "/usr/local/bin:/usr/bin:/bin"
      TMPDIR: "{{ php_fpm_tmp_upload_diectory }}"
    php_admin_value:
      date.timezone: "Europe/Berlin"
      log_errors: 'on'
      max_execution_time: 300
      memory_limit: 512M
      upload_max_filesize: 32M
```

### php modules

```yaml
php_modules:
  # gd
  - name: gd
    enabled: true
    priority: 20
    content: |
      extension=gd
  # OpCache settings
  - name: opcache
    enabled: true
    priority: 10
    content: |
      zend_extension=opcache
      opcache.enable=1
      opcache.enable_cli=1
      opcache.memory_consumption=128
      opcache.interned_strings_buffer=16
      opcache.max_accelerated_files=10000
      opcache.max_wasted_percentage=5
      opcache.validate_timestamps=1
      opcache.revalidate_path=0
      opcache.revalidate_freq=1
      opcache.max_file_size=0
  # PDO mysql
  - name: pdo_mysql
    enabled: true
    priority: 20
    content: |
      extension=pdo_mysql
```

Under [documentation](documentation) you can find some module configurations that have been copied from php.ini.

---

