
# Ansible Role:  `bodsch.php.composer`

Ansible role to install php composer on various systems.

## usage

```yaml
composer_version: "" # 2.8.3

composer_self_update: false

composer_home:
  path: '~/.composer'
  owner: root
  group: root

composer_global_packages: []
  # - name: psr/log
  #   state: present
  # - name: psr/cache
  #   release: 3.0.0
  #   state: absent
```
