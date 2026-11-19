import asyncio
import dataclasses
import logging
import re
from enum import Enum
from typing import Optional

import click
import psutil
from ioregistry.exceptions import IORegistryException
from ioregistry.ioentry import get_io_services_by_type
from plumbum import ProcessExecutionError, local

from mac_internet_sharing.dhcpd_leases import LeaseEntry, get_dhcp_leases
from mac_internet_sharing.native_bridge import SCPreferences
from mac_internet_sharing.network_preference import NetworkService

# Resolved by SCPreferences relative to /Library/Preferences/SystemConfiguration
NAT_PREFS_ID = 'com.apple.nat.plist'
NAT_PREFS_NAME = 'mac_internet_sharing'
NAT_KEY = 'NAT'
IFCONFIG = local['ifconfig']
IDEVICES = ['iPhone', 'iPad']

SLEEP_TIME = 1
PREFIX_SIZE = 3

logger = logging.getLogger(__name__)


class SharingState(Enum):
    ON = 'ON'
    OFF = 'OFF'
    TOGGLE = 'TOGGLE'


@dataclasses.dataclass
class USBEthernetInterface:
    product_name: str
    serial_number: str
    name: str


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

        product_name = usb_host.properties['USB Product Name']
        usb_serial_number = usb_host.properties['USB Serial Number']
        if product_name not in IDEVICES:
            continue
        interfaces[usb_serial_number] = ethernet_interface_entry.name
    return interfaces


def get_mac_address(interface: str) -> Optional[str]:
    """ Returns the MAC address of the specified network interface. """
    addrs = psutil.net_if_addrs()

    if interface in addrs:
        for addr in addrs[interface]:
            if addr.family == psutil.AF_LINK:  # AF_LINK corresponds to MAC address
                return addr.address


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
        bridge_members = re.findall(r'^\s*member:\s+(\S+)', output, re.MULTILINE)
        devices = []

        dhcp_leases = get_dhcp_leases()

        for udid, interface in get_apple_usb_ethernet_interfaces().items():
            if interface not in bridge_members:
                continue
            # Apple randomizes MAC addresses for privacy, so we match only the first few bytes
            lease_entry = dhcp_leases.get_first_entry_matching_prefix(PREFIX_SIZE, get_mac_address(interface))
            devices.append(BridgeMember(udid, interface, lease_entry))
        return cls(name, ipv4, ipv6, devices)

    def __repr__(self) -> str:
        members_formatted = '\n\t'.join(repr(member) for member in self.members)
        return (f'{click.style("🛜 Bridge details:", bold=True)}\n'
                f'🌐 {click.style("ipv4:", bold=True)} {self.ipv4}\n'
                f'🌐 {click.style("ipv6:", bold=True)} {self.ipv6}\n'
                f'{click.style("members:", bold=True)}\n'
                f'\t{members_formatted}')


def verify_bridge(name: str = 'bridge100') -> None:
    """ Verify network bridge status. """
    try:
        result = IFCONFIG(name)
    except ProcessExecutionError as e:
        if f'interface {name} does not exist' in str(e):
            logger.info('Internet sharing OFF')
        else:
            raise e
    else:
        logger.info('Internet sharing ON')
        print(Bridge.parse_ifconfig(result))


def nat_preferences() -> SCPreferences:
    """ Open an exclusive session over the NAT preferences. """
    return SCPreferences(NAT_PREFS_NAME, NAT_PREFS_ID)


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


async def set_sharing_state(state: SharingState) -> None:
    """ Set sharing state for NAT configuration. """
    with nat_preferences() as prefs:
        nat = prefs.get(NAT_KEY)
        if nat is None:
            return

        if state == SharingState.ON:
            new_state = 1
        elif state == SharingState.OFF:
            new_state = 0
        elif state == SharingState.TOGGLE:
            new_state = int(not nat['Enabled'])
        else:
            raise ValueError("Invalid NAT sharing state")

        nat['Enabled'] = new_state
        prefs.set(NAT_KEY, nat)
        prefs.commit()
    await asyncio.sleep(SLEEP_TIME)
    verify_bridge()


async def update_sharing_devices(devices: set) -> None:
    """ Update the SharingDevices list in the NAT configuration. """
    with nat_preferences() as prefs:
        nat = prefs.get(NAT_KEY)
        if nat is None:
            raise ValueError('NAT configuration not found in the plist.')
        nat['SharingDevices'] = list(devices)
        prefs.set(NAT_KEY, nat)
        prefs.commit()
    await asyncio.sleep(SLEEP_TIME)
