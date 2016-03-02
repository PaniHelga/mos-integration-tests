#    Copyright 2015 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json

from tempest_lib import exceptions


def os_execute(remote, command, fail_ok=False, merge_stderr=False):
    command = '. openrc && {}'.format(command)
    result = remote.execute(command)
    if not fail_ok and not result.is_ok:
        raise exceptions.CommandFailed(result['exit_code'],
                                       command,
                                       result.stdout_string,
                                       result.stderr_string)
    output = ''
    if merge_stderr:
        output += result.stderr_string
    return output + result.stdout_string


class CLICLient(object):

    command = ''

    def __init__(self, remote):
        self.remote = remote
        super(CLICLient, self).__init__()

    def build_command(self, action, flags='', params=''):
        return ' '.join([self.command, flags, action, params])

    def execute(self, action, flags='', params='', fail_ok=False,
                merge_stderr=False):
        command = self.build_command(action, flags, params)
        return os_execute(self.remote, command, fail_ok=fail_ok,
                          merge_stderr=merge_stderr)

    def details(self, output):
        return {x['Field']: x['Value'] for x in json.loads(output)}


class OpenStack(CLICLient):
    command = 'openstack'

    def project_create(self, name):
        output = self.execute('project create',
                              params='{} -f json'.format(name))
        return self.details(output)

    def project_delete(self, name):
        return self.execute('project delete', params=name)

    def user_create(self, name, password, project=None):
        params = '{name} --password {password} -f json'.format(
            name=name, password=password)
        if project is not None:
            params += ' --project {}'.format(project)
        output = self.execute('user create', params=params)
        return self.details(output)

    def user_delete(self, name):
        return self.execute('user delete', params=name)