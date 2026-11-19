import dataclasses
import logging
import re
import time
from enum import Enum
from typing import Optional

import click
from ioregistry.exceptions import IORegistryException
from ioregistry.ioentry import get_io_services_by_type
from plumbum import ProcessExecutionError, local

from mac_internet_sharing.dhcpd_leases import LeaseEntry, get_dhcp_leases
from mac_internet_sharing.exceptions import NotConfiguredError
from mac_internet_sharing.native_bridge import SCPreferences, get_dynamic_store_value
from mac_internet_sharing.network_preference import NetworkService

# Resolved by SCPreferences relative to /Library/Preferences/SystemConfiguration
NAT_PREFS_ID = 'com.apple.nat.plist'
NAT_PREFS_NAME = 'mac_internet_sharing'
NAT_KEY = 'NAT'
NETWORK_SHARING_STORE_KEY = 'com.apple.NetworkSharing'
IFCONFIG = local['ifconfig']
IDEVICES = ['iPhone', 'iPad']

STATE_CHANGE_TIMEOUT = 10
LEASE_TIMEOUT = 5
POLL_INTERVAL = 0.2

BRIDGE_MEMBER_PATTERN = re.compile(r'^\s*member:\s+(\S+)', re.MULTILINE)

logger = logging.getLogger(__name__)


class SharingState(Enum):
    ON = 'ON'
    OFF = 'OFF'
    TOGGLE = 'TOGGLE'


def get_apple_usb_ethernet_interfaces() -> dict[str, str]:
    """ Return list of Apple USB Ethernet interfaces. """
    interfaces = {}
    for ethernet_interface_entry in get_io_services_by_type('IOEthernetInterface'):
        try:
            apple_usb_ncm_data = ethernet_interface_entry.get_parent_by_type('IOService', 'AppleUSBNCMData')
        except IORegistryException:
            continue

        if 'waitBsdStart' in apple_usb_ncm_data.properties:
            # RSD interface
            continue

        try:
            usb_host = ethernet_interface_entry.get_parent_by_type('IOService', 'IOUSBHostDevice')
        except IORegistryException:
            continue

        product_name = usb_host.properties.get('USB Product Name')
        usb_serial_number = usb_host.properties.get('USB Serial Number')
        if product_name not in IDEVICES or usb_serial_number is None:
            continue
        interfaces[usb_serial_number] = ethernet_interface_entry.name
    return interfaces


@dataclasses.dataclass(repr=False)
class BridgeMember:
    udid: str
    interface: str
    lease_entry: Optional[LeaseEntry] = None

    def __repr__(self) -> str:
        lease_suffix = ''
        if self.lease_entry is not None:
            # Device may not have a prepared DHCP lease yet
            lease_suffix += f' {self.lease_entry.name:<20} {self.lease_entry.ip_address}'
        return f'{self.udid:<40} {self.interface:<8}{lease_suffix}'


class Bridge:
    def __init__(self, name: str, ipv4: str, ipv6: str, members: list[BridgeMember]) -> None:
        self.name = name
        self.ipv4 = ipv4
        self.ipv6 = ipv6
        self.members = members

    @classmethod
    def parse_ifconfig(cls, output: str) -> 'Bridge':
        name_match = re.search(r'^(\S+):', output, re.MULTILINE)
        name = name_match.group(1) if name_match else 'Unknown'

        # Extract the IPv4 configuration line.
        ipv4_match = re.search(
            r'^\s*(inet\s+\S+\s+netmask\s+\S+\s+broadcast\s+\S+)',
            output,
            re.MULTILINE
        )
        ipv4 = ipv4_match.group(1) if ipv4_match else ""

        # Extract the IPv6 configuration line.
        ipv6_match = re.search(
            r'^\s*(inet6\s+\S+\s+prefixlen\s+\d+\s+scopeid\s+\S+)',
            output,
            re.MULTILINE
        )
        ipv6 = ipv6_match.group(1) if ipv6_match else ""

        # Extract all member interfaces
        bridge_members = BRIDGE_MEMBER_PATTERN.findall(output)

        # Extract the MAC addresses the bridge has learned behind each member, e.g. "9a:e8:59:9b:d4:37 Vlan1 en29 ..."
        learned_addresses = re.findall(
            r'^\s*((?:[0-9a-fA-F]{1,2}:){5}[0-9a-fA-F]{1,2})\s+Vlan\d+\s+(\S+)',
            output,
            re.MULTILINE
        )

        dhcp_leases = get_dhcp_leases()
        devices = []
        for udid, interface in get_apple_usb_ethernet_interfaces().items():
            if interface not in bridge_members:
                continue
            lease_entry = None
            for mac_address, member in learned_addresses:
                if member == interface:
                    lease_entry = dhcp_leases.get_by_mac_address(mac_address)
                    if lease_entry is not None:
                        break
            devices.append(BridgeMember(udid, interface, lease_entry))
        return cls(name, ipv4, ipv6, devices)

    def __repr__(self) -> str:
        members_formatted = '\n\t'.join(repr(member) for member in self.members)
        return (f'{click.style("🛜 Bridge details:", bold=True)}\n'
                f'🌐 {click.style("ipv4:", bold=True)} {self.ipv4}\n'
                f'🌐 {click.style("ipv6:", bold=True)} {self.ipv6}\n'
                f'{click.style("members:", bold=True)}\n'
                f'\t{members_formatted}')


def nat_preferences(lock: bool = True) -> SCPreferences:
    """ Open a session over the NAT preferences. Locking is required for writing. """
    return SCPreferences(NAT_PREFS_NAME, NAT_PREFS_ID, lock=lock)


def get_sharing_bridge_name() -> Optional[str]:
    """ Return the name of the bridge created by Internet Sharing, or None if sharing is off. """
    with nat_preferences(lock=False) as prefs:
        nat = prefs.get(NAT_KEY)
    if nat is None:
        return None
    external_interface = nat.get('PrimaryInterface', {}).get('Device')

    # Other vmnet users (e.g. virtual machines) publish their own bridges under the same key
    state = get_dynamic_store_value(NAT_PREFS_NAME, NETWORK_SHARING_STORE_KEY) or {}
    for entry in state.get('ExternalInterfaces', []):
        if entry.get('ExternalInterface') != external_interface:
            continue
        internal_interfaces = entry.get('InternalInterfaces', [])
        if internal_interfaces:
            return internal_interfaces[0]
    return None


def get_sharing_bridge_details() -> Optional[str]:
    """ Return the `ifconfig` output of the bridge created by Internet Sharing, or None if sharing is off. """
    name = get_sharing_bridge_name()
    if name is None:
        return None
    try:
        return IFCONFIG(name)
    except ProcessExecutionError as e:
        if f'interface {name} does not exist' not in str(e):
            raise
        return None


def get_shared_interfaces() -> set[str]:
    """ Return the interfaces internet is currently shared with. """
    details = get_sharing_bridge_details()
    if details is None:
        return set()
    return set(BRIDGE_MEMBER_PATTERN.findall(details))


def wait_for_sharing_daemon(timeout: float = STATE_CHANGE_TIMEOUT) -> None:
    """ Wait for the sharing daemon to apply the committed NAT configuration. """
    with nat_preferences(lock=False) as prefs:
        nat = prefs.get(NAT_KEY) or {}
    expected = set()
    if nat.get('Enabled'):
        # Configured devices may be unplugged
        expected = set(nat.get('SharingDevices', [])).intersection(IFCONFIG('-l').split())

    deadline = time.monotonic() + timeout
    while get_shared_interfaces() != expected:
        if time.monotonic() >= deadline:
            logger.warning(f'Internet sharing configuration was not applied within {timeout}s')
            return
        time.sleep(POLL_INTERVAL)


def verify_bridge(lease_timeout: float = 0) -> None:
    """
    Verify network bridge status.

    A freshly created bridge takes a moment to get its addresses and for its members to renew their DHCP leases,
    so wait up to `lease_timeout` seconds for them.
    """
    deadline = time.monotonic() + lease_timeout
    while True:
        details = get_sharing_bridge_details()
        if details is None:
            logger.info('Internet sharing OFF')
            return
        bridge = Bridge.parse_ifconfig(details)
        ready = bridge.ipv6 and all(member.lease_entry is not None for member in bridge.members)
        if ready or time.monotonic() >= deadline:
            break
        time.sleep(POLL_INTERVAL)
    logger.info('Internet sharing ON')
    print(bridge)


def configure(service_name: NetworkService, members: list[str], network_name: str = "user's MacBook Pro") -> None:
    """ Configure NAT settings with given parameters. """
    with nat_preferences() as prefs:
        # Committing notifies the sharing daemon, so keep the current state instead of implicitly starting it
        enabled = (prefs.get(NAT_KEY) or {}).get('Enabled', 0)
        prefs.set(NAT_KEY, {
            'AirPort': {
                '40BitEncrypt': 1,
                'Channel': 0,
                'Enabled': 0,
                'NetworkName': network_name,
                'NetworkPassword': b''
            },
            'Enabled': enabled,
            'NatPortMapDisabled': False,
            'PrimaryInterface': {
                'Device': service_name.interface.devices_name,
                'Enabled': 0,
                'HardwareKey': '',
                'PrimaryUserReadable': service_name.interface.user_defined_name,
            },
            'PrimaryService': service_name.uuid,
            'SharingDevices': members
        })
        prefs.commit()


def set_sharing_state(state: SharingState) -> None:
    """ Set sharing state for NAT configuration. """
    with nat_preferences() as prefs:
        nat = prefs.get(NAT_KEY)
        if nat is None:
            raise NotConfiguredError()

        if state == SharingState.TOGGLE:
            enabled = not nat.get('Enabled', 0)
        else:
            enabled = state == SharingState.ON

        nat['Enabled'] = int(enabled)
        prefs.set(NAT_KEY, nat)
        prefs.commit()

    wait_for_sharing_daemon()
    verify_bridge(LEASE_TIMEOUT)


def update_sharing_devices(devices: list[str]) -> None:
    """ Update the SharingDevices list in the NAT configuration. """
    with nat_preferences() as prefs:
        nat = prefs.get(NAT_KEY)
        if nat is None:
            raise NotConfiguredError()
        nat['SharingDevices'] = devices
        prefs.set(NAT_KEY, nat)
        prefs.commit()

    wait_for_sharing_daemon()
    verify_bridge(LEASE_TIMEOUT)
