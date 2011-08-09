# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
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

from nova import flags
from nova import log as logging
from nova import test
from nova import context
from nova.network.quantummanager import QuantumManager
from nova.network import manager
from nova.network import quantum
from nova.network import melange_client
from nova.db import api as db_api
from mox import IgnoreArg


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.network')


class TestCreateNetworks(test.TestCase):

    def setUp(self):
        super(TestCreateNetworks, self).setUp()
        self.mox.StubOutWithMock(melange_client, 'create_block')
        self._stub_out_and_ignore_quantum_client_calls()

    def test_creates_network_sized_v4_subnet_in_melange(self):
        self.flags(use_ipv6=False)
        melange_client.create_block(IgnoreArg(), "10.1.1.0/26", "project1")
        self.mox.ReplayAll()

        create_quantum_network(cidr="10.1.1.0/24", num_networks=1,
                               network_size=64, project_id="project1")

    def test_creates_multiple_ipv4_melange_blocks(self):
        self.flags(use_ipv6=False)
        melange_client.create_block(IgnoreArg(), "10.1.0.0/24", "project1")
        melange_client.create_block(IgnoreArg(), "10.1.1.0/24", "project1")
        melange_client.create_block(IgnoreArg(), "10.1.2.0/24", "project1")
        self.mox.ReplayAll()

        create_quantum_network(cidr="10.1.0.0/20", num_networks=3,
                               network_size=256, project_id="project1")

    def test_creates_ipv6_melange_blocks(self):
        self.flags(use_ipv6=True)
        melange_client.create_block(IgnoreArg(), "10.1.1.0/26", "project1")
        melange_client.create_block(IgnoreArg(), "fe::/64", "project1")
        self.mox.ReplayAll()

        create_quantum_network(cidr="10.1.1.0/24", num_networks=1,
                               network_size=64, cidr_v6="fe::/60",
                               project_id="project1")

    def test_creates_multiple_ipv6_melange_blocks(self):
        self.flags(use_ipv6=True)
        melange_client.create_block(IgnoreArg(), "10.1.0.0/24", "project1")
        melange_client.create_block(IgnoreArg(), "fe::/64", "project1")

        melange_client.create_block(IgnoreArg(), "10.1.1.0/24", "project1")
        melange_client.create_block(IgnoreArg(), "fe:0:0:1::/64", "project1")

        self.mox.ReplayAll()

        create_quantum_network(cidr="10.1.0.0/20", num_networks=2,
                               cidr_v6="fe::/60", network_size=256,
                               project_id="project1")

    def _stub_out_and_ignore_quantum_client_calls(self):
        self.mox.StubOutWithMock(quantum, 'create_network')
        quantum.create_network(IgnoreArg(),
                             IgnoreArg()).MultipleTimes().AndReturn("network1")


class TestAllocateForInstance(test.TestCase):

    def setUp(self):
        super(TestAllocateForInstance, self).setUp()
        self.mox.StubOutWithMock(quantum, 'create_port')
        self.mox.StubOutWithMock(quantum, 'plug_iface')

        quantum.create_port(IgnoreArg(), IgnoreArg()).\
                           MultipleTimes().AndReturn("port_id")
        quantum.plug_iface(IgnoreArg(), IgnoreArg(),
                           IgnoreArg(), IgnoreArg()).MultipleTimes()

    def test_allocates_v4_ips_from_melange(self):
        quantum_mgr = QuantumManager()
        admin_context = context.get_admin_context()

        instance = db_api.instance_create(admin_context, {})

        private_network = db_api.network_create_safe(admin_context,
                                  dict(label='private',
                                       project_id="project1", priority=1))
        private_noise_network = db_api.network_create_safe(admin_context,
                                  dict(label='private',
                                       project_id="some_other_project",
                                       priority=1))
        public_network = db_api.network_create_safe(admin_context,
                                  dict(label='public', priority=1))

        self.mox.StubOutWithMock(melange_client, 'allocate_ip')
        private_v4block = dict(netmask="255.255.255.0", cidr="10.1.1.0/24",
                               gateway="10.1.1.1", broadcast="10.1.1.255")
        private_v4ip = dict(address="10.1.1.2", version=4,
                            ip_block=private_v4block)
        public_v4block = dict(netmask="255.255.0.0", cidr="77.1.1.0/24",
                               gateway="77.1.1.1", broadcast="77.1.1.255")

        public_v4ip = dict(address="77.1.1.2", version=4,
                           ip_block=public_v4block)

        melange_client.allocate_ip(private_network.id, IgnoreArg(),
                                   project_id="project1",
                                   mac_address=IgnoreArg())\
                                   .InAnyOrder().AndReturn([private_v4ip])
        melange_client.allocate_ip(public_network.id, IgnoreArg(),
                                   project_id=None,
                                   mac_address=IgnoreArg())\
                                   .InAnyOrder().AndReturn([public_v4ip])
        self.mox.ReplayAll()

        net_info = quantum_mgr.allocate_for_instance(admin_context,
                                               instance_id=instance.id,
                                               host="localhost",
                                               project_id="project1",
                                               instance_type_id=1,
                                               vpn="vpn_address")
        [(private_net, private_net_info),
         (public_net, public_net_info)] = net_info

        self.assertEqual(private_net_info['label'], 'private')
        self.assertEqual(private_net_info['gateway'], '10.1.1.1')
        self.assertEqual(private_net_info['broadcast'], '10.1.1.255')
        self.assertEqual(private_net_info['ips'], [{'ip': '10.1.1.2',
                                            'netmask': '255.255.255.0',
                                            'enabled': '1'}])

        self.assertEqual(public_net_info['label'], 'public')
        self.assertEqual(public_net_info['gateway'], '77.1.1.1')
        self.assertEqual(public_net_info['broadcast'], '77.1.1.255')

        self.assertEqual(public_net_info['ips'], [{'ip': '77.1.1.2',
                                            'netmask': '255.255.0.0',
                                            'enabled': '1'}])

    def test_allocates_v6_ips_from_melange(self):
        quantum_mgr = QuantumManager()
        mac_address = "11:22:33:44:55:66"
        self._stub_out_mac_address_generation(mac_address, quantum_mgr)
        admin_context = context.get_admin_context()
        instance = db_api.instance_create(admin_context, {})

        network = db_api.network_create_safe(admin_context,
                                             dict(project_id="project1",
                                                  cidr_v6="fe::/96",
                                                  priority=1))

        self.mox.StubOutWithMock(melange_client, 'allocate_ip')
        v4_block = dict(netmask="255.255.255.0", cidr="10.1.1.0/24",
                               gateway="10.1.1.1", broadcast="10.1.1.255")

        allocated_v4ip = dict(address="10.1.1.2", version=4,
                              ip_block=v4_block)
        v6_block = dict(netmask="f:f:f:f::", cidr="fe::/96",
                        gateway="fe::1", broadcast="fe::ffff:ffff")
        allocated_v6ip = dict(address="fe::2", version=6, ip_block=v6_block)
        v6_block_prefix_length = 96

        melange_client.allocate_ip(network.id, IgnoreArg(),
                                   project_id="project1",
                                   mac_address=mac_address)\
                                   .AndReturn([allocated_v4ip, allocated_v6ip])
        self.mox.ReplayAll()

        [(net, net_info)] = quantum_mgr.allocate_for_instance(admin_context,
                                               instance_id=instance.id,
                                               host="localhost",
                                               project_id="project1",
                                               instance_type_id=1,
                                               vpn="vpn_address")

        self.assertEqual(net_info['ips'], [{'ip': '10.1.1.2',
                                            'netmask': '255.255.255.0',
                                            'enabled': '1'}])
        self.assertEqual(net_info['ip6s'], [{'ip': 'fe::2',
                                            'netmask': v6_block_prefix_length,
                                            'enabled': '1'}])
        self.assertEqual(net_info['gateway'], "10.1.1.1")
        self.assertEqual(net_info['broadcast'], "10.1.1.255")
        self.assertEqual(net_info['gateway6'], "fe::1")

    def _stub_out_mac_address_generation(self, stub_mac_address,
                                         network_manager):
        self.mox.StubOutWithMock(network_manager, 'generate_mac_address')
        network_manager.generate_mac_address().AndReturn(stub_mac_address)


class TestGetIps(test.TestCase):

    def test_get_all_allocated_ips_for_an_interface(self):
        quantum_mgr = QuantumManager()
        interface = dict(network_id="network123", id="vif_id",
                         network=dict(project_id="project1"))
        self.mox.StubOutWithMock(melange_client, 'get_allocated_ips')
        allocated_v4ip = dict(address="10.1.1.2", version=4)
        allocated_v6ip = dict(address="fe::2", version=6)

        melange_client.get_allocated_ips("network123", "vif_id",
                                         project_id="project1").AndReturn([
            allocated_v4ip, allocated_v6ip])
        self.mox.ReplayAll()

        ips = quantum_mgr.get_ips(interface)
        self.assertEqual(ips, [allocated_v4ip, allocated_v6ip])


class TestDeallocateForInstance(test.TestCase):

    def test_deallocates_ips_from_melange(self):
        quantum_mgr = QuantumManager()
        admin_context = context.get_admin_context()
        project_id = "project1"

        instance_id = db_api.instance_create(admin_context, dict())['id']
        network1 = db_api.network_create_safe(admin_context,
                                             dict(instance_id=instance_id,
                                                  priority=1,
                                                  project_id=project_id))
        network2 = db_api.network_create_safe(admin_context,
                                             dict(instance_id=instance_id,
                                                  priority=2,
                                                  project_id=project_id))

        vif1 = db_api.virtual_interface_create(admin_context,
                                              dict(instance_id=instance_id,
                                              network_id=network1['id'],
                                              project_id=project_id))
        vif2 = db_api.virtual_interface_create(admin_context,
                                              dict(instance_id=instance_id,
                                              network_id=network2['id'],
                                              project_id=project_id))
        self._setup_quantum_mocks()

        self.mox.StubOutWithMock(melange_client, "deallocate_ips")
        melange_client.deallocate_ips(network1['id'], vif1['id'],
                                      project_id=project_id)
        melange_client.deallocate_ips(network2['id'], vif2['id'],
                                      project_id=project_id)

        self.mox.ReplayAll()

        quantum_mgr.deallocate_for_instance(admin_context,
                                            instance_id=instance_id,
                                            project_id=project_id)

        vifs_left = db_api.virtual_interface_get_by_instance(admin_context,
                                                             instance_id)
        self.assertEqual(len(vifs_left), 0)

    def _setup_quantum_mocks(self):
        self.mox.StubOutWithMock(quantum, "get_port_by_attachment")
        self.mox.StubOutWithMock(quantum, "unplug_iface")
        self.mox.StubOutWithMock(quantum, "delete_port")

        quantum.get_port_by_attachment(IgnoreArg(), IgnoreArg(), IgnoreArg()).\
                                           MultipleTimes().AndReturn("port_id")
        quantum.unplug_iface(IgnoreArg(), IgnoreArg(), IgnoreArg()).\
                                          MultipleTimes()
        quantum.delete_port(IgnoreArg(), IgnoreArg(), IgnoreArg()).\
                                         MultipleTimes()


def create_quantum_network(**kwargs):
    default_params = dict(context=context.get_admin_context(),
                          label="label",
                          cidr="169.1.1.0/24",
                          multi_host=False,
                          num_networks=1,
                          network_size=64,
                          vlan_start=0,
                          vpn_start=0,
                          cidr_v6=None,
                          gateway_v6=None,
                          bridge="river kwai",
                          bridge_interface="too far",
                          dns1=None,
                          dns2=None,
                          project_id="project1",
                          priority=1)
    params = dict(default_params.items() + kwargs.items())
    return QuantumManager().create_networks(**params)
