
# Ansible Role:  `bodsch.php.pie`

Ansible role to install php pie on various systems.

## usage

```yaml
pie_version: "" # 2.8.3

pie_self_update: false

pie_home:
  path: '~/.pie'
  owner: root
  group: root

pie_global_packages: []
  # - name: psr/log
  #   state: present
  # - name: psr/cache
  #   release: 3.0.0
  #   state: absent
```
