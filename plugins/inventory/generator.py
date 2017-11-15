# Copyright (c) 2017 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = '''
    name: generator
    plugin_type: inventory
    version_added: "2.5"
    short_description: Uses Jinja2 to construct hosts and groups from patterns
    description:
        - Uses a YAML configuration file with a valid YAML or ``.config`` extension to define var expressions and group conditionals
        - Create a template pattern that describes each host, and then use independent configuration layers
        - Every element of every layer is combined to create a host for every layer combination
        - Parent groups can be defined with reference to hosts and other groups using the same template variables
'''

EXAMPLES = '''
    # inventory.config file in YAML format
    plugin: generator
    strict: False
    hosts:
        name: "{{ operation }}-{{ application }}-{{ environment }}-runner"
        parents:
          - name: "{{ operation }}-{{ application }}-{{ environment }}"
            parents:
              - name: "{{ operation }}-{{ application }}"
                parents:
                  - name: "{{ operation }}"
                  - name: "{{ application }}"
              - name: "{{ application }}-{{ environment }}"
                parents:
                  - name: "{{ application }}"
                    vars:
                      application: "{{ application }}"
                  - name: "{{ environment }}"
                    vars:
                      env: "{{ environment }}"
          - name: runner
    # Allow extra overrides to define parent groups for a subset of a layer
    groups:
        - name: "product-api"
          parents:
            - name: api
        - name: "payment-api"
          parents:
            - name: api
    layers:
        operation:
            - build
            - launch
        environment:
            - dev
            - test
            - prod
        application:
            - web
            - product-api
            - payment-api
'''

import os

from collections import MutableMapping

from ansible import constants as C
from ansible.errors import AnsibleParserError
from ansible.plugins.cache import FactCache
from ansible.plugins.inventory import BaseInventoryPlugin
from ansible.module_utils._text import to_native

from itertools import product


class InventoryModule(BaseInventoryPlugin):
    """ constructs groups and vars using Jinaj2 template expressions """

    NAME = 'generator'

    def __init__(self):

        super(InventoryModule, self).__init__()

        self._cache = FactCache()

    def verify_file(self, path):

        valid = False
        if super(InventoryModule, self).verify_file(path):
            file_name, ext = os.path.splitext(path)

            if not ext or ext in ['.config'] + C.YAML_FILENAME_EXTENSIONS:
                valid = True

        return valid

    def template(self, pattern, variables):
        t = self.templar
        t.set_available_variables(variables)
        return t.do_template(pattern)

    def add_parents(self, inventory, child, parents, template_vars):
        for parent in parents:
            groupname = self.template(parent['name'], template_vars)
            if groupname not in inventory.groups:
                inventory.add_group(groupname)
            group = inventory.groups[groupname]
            for (k, v) in parent.get('vars',{}).items():
                group.set_variable(k, self.template(v, template_vars))
            inventory.add_child(groupname, child)
            self.add_parents(inventory, groupname, parent.get('parents', []), template_vars)

    def parse(self, inventory, loader, path, cache=False):
        ''' parses the inventory file '''

        super(InventoryModule, self).parse(inventory, loader, path, cache=cache)

        try:
            data = self.loader.load_from_file(path)
        except Exception as e:
            raise AnsibleParserError("Unable to parse %s: %s" % (to_native(path), to_native(e)))

        if not data:
            raise AnsibleParserError("%s is empty" % (to_native(path)))
        elif not isinstance(data, MutableMapping):
            raise AnsibleParserError('inventory source has invalid structure, it should be a dictionary, got: %s' % type(data))
        elif data.get('plugin') != self.NAME:
            raise AnsibleParserError("%s is not a generator groups config file, plugin entry must be 'generator'" % (to_native(path)))

        template_inputs = product(*data.get('layers').values())
        for item in template_inputs:
            template_vars = dict()
            for i, key in enumerate(data['layers'].keys()):
                template_vars[key] = item[i]
            host = self.template(data['hosts']['name'], template_vars)
            inventory.add_host(host)
            self.add_parents(inventory, host, data['hosts'].get('parents', []), template_vars)
        for group in data.get('groups', []):
            self.add_parents(inventory, group['name'], group['parents'], template_vars)
