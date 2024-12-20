# python 3 headers, required if submitting to Ansible
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.utils.display import Display

display = Display()


class FilterModule(object):
    """
    """
    def filters(self):
        return {
            'ini_values': self.ini_values,
            'remove_empty_values': self.remove_empty_values,
        }

    def ini_values(self, data, join_list=False, default=None, valid_values=None):
        """
        """
        # display.v(f"ini_values(self, {data}, {join_list}, {default}, {valid_values})")
        result = ""

        if isinstance(data, bool):
            return "On" if data else "Off"
        if isinstance(data, int):
            return data
        if isinstance(data, str) and len(data) == 0:
            return '""'
        if isinstance(data, str):
            return f'"{data}"'

        return result

    def remove_empty_values(self, data):
        # display.v(f"remove_empty_values(self, {data})")

        def is_empty(value):
            """Überprüfen, ob der Wert leer ist (ignoriere boolesche Werte)."""
            if isinstance(value, bool):
                return False  # Boolesche Werte sollen erhalten bleiben
            if value == 0:
                return False  # Zahl 0 soll erhalten bleiben

            return value in [None, '', {}, [], False]

        if isinstance(data, dict):
            # Durch alle Schlüssel-Wert-Paare iterieren
            return {key: self.remove_empty_values(value) for key, value in data.items() if not is_empty(value)}
        elif isinstance(data, list):
            # Leere Listen und leere Elemente entfernen
            return [self.remove_empty_values(item) for item in data if not is_empty(item)]
        else:
            # Andere Typen direkt zurückgeben (einschließlich boolesche Werte)
            return data
