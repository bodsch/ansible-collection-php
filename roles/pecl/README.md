
# Ansible Role:  `bodsch.php.pecl`

Ansible role to install php pecl packages on various systems.

Detect available PHP Version based on `php_version` Variable.

## usage

```yaml
php_pecl_extensions:
  - name: APCu
    version: 5.1.22
    enabled: true
  - name: imagick
    version: 3.7.0
    dependencies:
      - libmagickwand-dev
  - name: memcached
    dependencies:
      - libmemcached-dev
      - libzstd-dev
      - liblz-dev
```

| Key            | type     | requiered  | default value | Description                             |
|:----           | :---     | :----      |:----          | :----                                   |
| `name`         | `string` | **TRUE**   | `-`           | The Name of the Pecl Extension          |
| `version`      | `string` | **FALSE**  | `-`           | The Version of the Pecl Extension       |
| `state`        | `string` | **FALSE**  | `present`     |                                         |
| `enabled`      | `bool`   | **FALSE**  | `true`        | should be the extension enabled?        |
| `priority`     | `string` | **FALSE**  | `80`          | priority for the enabled extension      |
| `dependencies` | `list`   | **FALSE**  | `[]`          | a list with dependencies for the build  |


```yaml

php_pecl_extensions:
  - name: memcached
    version: 3.2.0
    state: present
    enabled: true
    dependencies:
      - libmemcached-dev
      - libzstd-dev
      - liblz-dev
  - name: APCu
    version: 5.1.22
    state: absent

```
