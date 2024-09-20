# python 3 headers, required if submitting to Ansible

from __future__ import (absolute_import, print_function)
__metaclass__ = type

from ansible.utils.display import Display

display = Display()


class FilterModule(object):
    """
        Ansible file jinja2 tests
    """

    def filters(self):
        return {
            'dependencies': self.dependencies,
        }

    def dependencies(self, data):
        """
        """
        dependencies = []

        if isinstance(data, list):
            dep = [x for x in data if x.get("dependencies")]

            if dep:
                for d in dep:
                    dependencies.append(d.get("dependencies"))

                dependencies = self.flatten_list(dependencies)
                # remove doubles
                dependencies = list(set(dependencies))

        return dependencies

    def flatten_list(self, data):
        """
            flatten a list

            input: [[0,1,2],[8,9]]
            return: [0,1,2,8,9]
        """
        return [item for sublist in data for item in sublist]
