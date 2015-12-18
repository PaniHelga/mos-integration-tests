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

import logging

import pytest
from waiting import wait

from mos_tests.neutron.python_tests import base
from mos_tests import settings


logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_ha', 'has_2_or_more_computes')
@pytest.mark.usefixtures("setup")
class TestBanDHCPAgent(base.TestBase):
    """Check DHCP agents rescheduling."""

    def create_cirros_instance_with_ssh(self, name='server01',
                                        net_name='net04', **kwargs):
        """Boot instance from cirros image with access by ssh.

        :param name: instance name
        :param net_name: network name
        :param kwargs: some other params to create instance
        :returns: created instance
        """
        security_group = self.os_conn.create_sec_group_for_ssh()

        network = [net.id for net in self.os_conn.nova.networks.list()
                   if net.label == net_name]

        kwargs.update({'nics': [{'net-id': network[0]}],
                       'security_groups': [security_group.name]})

        instance = self.os_conn.create_server(
            name=name, **kwargs)
        return instance

    def ban_dhcp_agent(self, node_to_ban, host, network_name=None,
                       wait_for_die=True, wait_for_rescheduling=True):
        """Ban DHCP agent and wait until agents rescheduling.

        Ban dhcp agent on same node as network placed and wait until agents
        rescheduling.

        :param node_to_ban: dhcp-agent host to ban
        :param host: host or ip of controller onto execute ban command
        :param network_name: name of network to determine node with dhcp agents
        :param wait_for_die: wait until dhcp-agent die
        :param wait_for_rescheduling: wait new dhcp-agent starts
        :returns: str, name of banned node
        """
        list_dhcp_agents = lambda: self.os_conn.list_all_neutron_agents(
            agent_type='dhcp', filter_attr='host')
        if network_name:
            network = self.os_conn.neutron.list_networks(
                name=network_name)['networks'][0]
            list_dhcp_agents = (
                lambda: self.os_conn.get_node_with_dhcp_for_network(
                    network['id']))
        current_agents = list_dhcp_agents()

        # ban dhcp agent on provided node
        with self.env.get_ssh_to_node(host) as remote:
            remote.execute(
                "pcs resource ban p_neutron-dhcp-agent {0}".format(
                    node_to_ban))

        logger.info("Ban DHCP agent on node {0}".format(node_to_ban))

        # Wait to die banned dhcp agent
        if wait_for_die:
            err_msg = "Awainting ban of DHCP agent: {0}"
            wait(
                lambda: (node_to_ban not in list_dhcp_agents()),
                timeout_seconds=60 * 3,
                sleep_seconds=(1, 60, 5),
                waiting_for=err_msg.format(node_to_ban))
        # Wait to reschedule dhcp agent
        if wait_for_rescheduling:
            err_msg = "New DHCP agent wasn't rescheduled"
            wait(
                lambda: (set(list_dhcp_agents()) - set(current_agents)),
                timeout_seconds=60 * 3,
                sleep_seconds=(1, 60, 5),
                waiting_for=err_msg)
        return node_to_ban

    def clear_dhcp_agent(self, node_to_clear, host, network_name=None,
                         wait_for_rescheduling=True):
        """Clear DHCP agent after ban and wait until agents rescheduling.

        :param node_to_clear: dhcp-agent host to clear
        :param host: host or ip of controller onto execute ban command
        :param network_name: name of network to determine node with dhcp agents
        :param wait_for_rescheduling: wait until dhcp-agent reschedule
        :returns: str, name of cleared node
        """
        list_dhcp_agents = lambda: self.os_conn.list_all_neutron_agents(
            agent_type='dhcp', filter_attr='host')
        if network_name:
            network = self.os_conn.neutron.list_networks(
                name=network_name)['networks'][0]
            list_dhcp_agents = (
                lambda: self.os_conn.get_node_with_dhcp_for_network(
                    network['id']))

        # clear dhcp agent on provided node
        with self.env.get_ssh_to_node(host) as remote:
            remote.execute(
                "pcs resource clear p_neutron-dhcp-agent {0}".format(
                    node_to_clear))

        logger.info("Clear DHCP agent on node {0}".format(node_to_clear))

        # Wait to reschedule dhcp agent
        if wait_for_rescheduling:
            err_msg = (
                "Wait for DHCP agent ({0}) rescheduling after clear from ban")
            wait(
                lambda: (node_to_clear in list_dhcp_agents()),
                timeout_seconds=60 * 3,
                sleep_seconds=(1, 60, 5),
                waiting_for=err_msg.format(node_to_clear))
        return node_to_clear

    def run_on_cirros_through_host(self, vm, cmd):
        """Run command on Cirros VM, connected through some host.

        :param vm: instance with cirros
        :param cmd: command to execute
        :returns: dict, result of command with code, stdout, stderr.
        """
        vm = self.os_conn.get_instance_detail(vm)
        srv_host = self.env.find_node_by_fqdn(
            self.os_conn.get_srv_hypervisor_name(vm)).data['ip']

        _floating_ip = self.os_conn.get_nova_instance_ips(vm)['floating']

        with self.env.get_ssh_to_node(srv_host) as remote:
            res = self.os_conn.execute_through_host(
                remote, _floating_ip, cmd)
        return res

    def check_ping_from_cirros(self, vm, ip_to_ping=None):
        """Run ping some ip from Cirros instance.

        :param vm: instance with cirros
        :param ip_to_ping: ip to ping
        """
        ip_to_ping = ip_to_ping or settings.PUBLIC_TEST_IP
        cmd = "ping -c1 {0}".format(ip_to_ping)
        res = self.run_on_cirros_through_host(vm, cmd)
        error_msg = (
            'Instance has no connectivity, '
            'exit code {exit_code},'
            'stdout {stdout}, stderr {stderr}').format(**res)
        assert 0 == res['exit_code'], error_msg

    def check_dhcp_on_cirros_instance(self, vm):
        """Check dhcp client on Cirros instance.

        :param vm: instance with cirros
        """
        cmd = 'sudo -i cirros-dhcpc up eth0'
        res = self.run_on_cirros_through_host(vm, cmd)
        err_msg = (
            'DHCP client can\'t get ip, '
            'exit code {exit_code}, '
            'stdout {stdout}, stderr {stderr}'.format(**res))
        assert 0 == res['exit_code'], err_msg

    @pytest.fixture(autouse=True)
    def _prepare_openstack_state(self, init):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance and associate floating IP
            4. Check ping from instance google DNS
            6. Check run dhcp-client in instance's console:
               sudo cirros-dhcpc up eth0
        """
        # init variables
        exist_networks = self.os_conn.list_networks()['networks']
        ext_net = [net for net in exist_networks
                   if net.get('router:external')][0]

        # create network with subnet and router
        int_net, sub_net = self.create_internal_network_with_subnet()
        self.net_id = int_net['network']['id']
        self.net_name = int_net['network']['name']
        router = self.create_router_between_nets(ext_net, sub_net)
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')

        # create instance and assign floating ip to it
        self.instance = self.create_cirros_instance_with_ssh(
            net_name=int_net['network']['name'],
            key_name=self.instance_keypair.name,
            router=router)

        self.os_conn.assign_floating_ip(self.instance)

        # check ping from instance and dhcp client on instance
        self.check_vm_is_available(self.instance, **self.cirros_creds)
        self.check_ping_from_cirros(vm=self.instance)
        self.check_dhcp_on_cirros_instance(vm=self.instance)

    @pytest.mark.parametrize('ban_count', [1, 2])
    def test_ban_some_dhcp_agents(self, ban_count):
        """Check dhcp-agent rescheduling after dhcp-agent dies.

        :param ban_count: count of banned dhcp-agents

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance and associate floating IP
            5. Run dhcp-client in instance's console: sudo cirros-dhcpc up eth0
            6. Look on what DHCP-agents chosen network is:
               neutron dhcp-agent-list-hosting-net <network_name>
            7. Ban one DHCP-agent on what chosen network is:
               pcs resource ban p_neutron-dhcp-agent <node>
            8. Run dhcp-client in instance's console: sudo cirros-dhcpc up eth0
            9. Check that this network is on other dhcp-agent and
               other health dhcp-agent:
               neutron dhcp-agent-list-hosting-net <network_name>

        Duration 15m

        """
        # Fixture init from method self._prepare_openstack_state
        # Get dhcp agents and ban some of it
        agents_hosts = self.os_conn.get_node_with_dhcp_for_network(self.net_id)
        controller_host = self.env.find_node_by_fqdn(
            agents_hosts[0]).data['ip']

        for identifier in range(ban_count):
            host_to_ban = agents_hosts[identifier]
            self.ban_dhcp_agent(node_to_ban=host_to_ban,
                                host=controller_host,
                                network_name=self.net_name,
                                wait_for_rescheduling=(not identifier))

        # check dhcp client on instance
        self.check_dhcp_on_cirros_instance(vm=self.instance)

        # check dhcp agent nodes after rescheduling
        new_agents_hosts = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id)
        err_msg = ('Rescheduling failed, agents list after and '
                   'before scheduling are same: '
                   'old agents hosts - {0}, '
                   'new agents hosts - {1}'.format(agents_hosts,
                                                   new_agents_hosts))
        assert sorted(agents_hosts) != sorted(new_agents_hosts), err_msg

    def test_ban_all_dhcp_agents_and_restart_one(self):
        """Check dhcp-agent state after ban all agents and restart one of them.

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance and associate floating IP
            5. Run dhcp-client in instance's console: sudo cirros-dhcpc up eth0
            6. Look on what DHCP-agents chosen network is:
               neutron dhcp-agent-list-hosting-net <network_name>
            7. Ban both DHCP-agent on what chosen network is:
               pcs resource ban p_neutron-dhcp-agent <node1>
               pcs resource ban p_neutron-dhcp-agent <node2>
            8. Check that network is on other DHCP-agent(s)
            9. Ban other DHCP-agent(s)
            10. Clear last banned DHCP-agent
            11. Run dhcp-client in instance's console:
                sudo cirros-dhcpc up eth0
            12. Check that this network is on cleared dhcp-agent:
                neutron dhcp-agent-list-hosting-net <network_name>
            13. Check that all networks is on cleared dhcp-agent:
                neutron net-list-on-dhcp-agent <id_clr_agnt> | grep net | wc -l

        Duration 15m

        """
        # Fixture init from method self._prepare_openstack_state
        # Get dhcp agents and ban all of it
        agents = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id, filter_attr=None)

        # collect all networks on dhcp agents
        agents_ids = [agent['id'] for agent in agents]
        agents_networks = [net['id'] for agent_id in agents_ids for net in
                           self.os_conn.get_networks_on_dhcp_agent(agent_id)]
        # ban first part of agents
        agents_hosts = [agent['host'] for agent in agents]
        controller_host = self.env.find_node_by_fqdn(
            agents_hosts[0]).data['ip']

        for index, host_to_ban in enumerate(agents_hosts):
            self.ban_dhcp_agent(node_to_ban=host_to_ban,
                                host=controller_host,
                                network_name=self.net_name,
                                wait_for_rescheduling=(not index))

        # ban rescheduled dhcp agents
        new_agents_hosts = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id)
        last_banned = None
        for host_to_ban in new_agents_hosts:
            last_banned = self.ban_dhcp_agent(node_to_ban=host_to_ban,
                                              host=controller_host,
                                              network_name=self.net_name,
                                              wait_for_rescheduling=False)
        # check that it was other rescheduled agent after ban presented agents
        assert (
            last_banned is not None), (
            "First step DHCP agent rescheduling failed")
        # clear last banned
        cleared_agent = self.clear_dhcp_agent(node_to_clear=last_banned,
                                              host=controller_host,
                                              network_name=self.net_name)
        # check dhcp client on instance after agent clearing and rescheduling
        self.check_dhcp_on_cirros_instance(vm=self.instance)

        # check dhcp agent behaviour after clearing
        actual_agents = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id)
        err_msg = ('We have to much dhcp-agent alive:'
                   'last banned - {0}, '
                   'last cleared - {1},'
                   'current actual - {2}'.format(last_banned,
                                                 cleared_agent,
                                                 actual_agents))
        # check that network of instance on last cleared agent
        assert len(actual_agents) == 1, err_msg
        assert actual_agents[0] == cleared_agent, err_msg

        # check that all networks are on last cleared agent
        cleared_agent_id = self.os_conn.get_node_with_dhcp_for_network_by_host(
            self.net_id, cleared_agent)[0]['id']
        nets_on_dhcp_agent = [net['id'] for net in
                              self.os_conn.get_networks_on_dhcp_agent(
                                  cleared_agent_id)]
        err_msg = (
            'There is not all networks on cleared agent: '
            'all existing networks - {0}, '
            'networks on cleared agent - {1}'.format(agents_networks,
                                                     nets_on_dhcp_agent))
        assert set(agents_networks) == set(nets_on_dhcp_agent), err_msg
