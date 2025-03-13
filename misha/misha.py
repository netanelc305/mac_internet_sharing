import contextlib
import ctypes
import dataclasses
import logging
import plistlib
import re
import time
from ctypes import c_char_p, c_void_p
from ctypes.util import find_library
from enum import Enum
from pathlib import Path
from typing import Generator, Optional

from ioregistry.exceptions import IORegistryException
from ioregistry.ioentry import get_io_services_by_type
from plumbum import ProcessExecutionError, local

SYSTEM_CONFIGURATION = Path('/Library/Preferences/SystemConfiguration')
NAT_CONFIGS = SYSTEM_CONFIGURATION / 'com.apple.nat.plist'
INTERFACE_PREFERENCES = SYSTEM_CONFIGURATION / 'preferences.plist'
IFCONFIG = local['ifconfig']
IDEVICES = ['iPhone', 'iPad']

SLEEP_TIME = 1

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


@contextlib.contextmanager
def plist_editor(file_path: Path) -> Generator:
    """ Context manager to edit a plist file. """
    if file_path.exists():
        with file_path.open('rb') as fp:
            data = plistlib.load(fp)
    else:
        data = {}
    yield data
    with file_path.open('wb') as fp:
        plistlib.dump(data, fp)


def get_primary_service_uuid(primary_interface: str) -> Optional[str]:
    """ Return primary service UUID for given primary interface. """
    with INTERFACE_PREFERENCES.open('rb') as fp:
        data = plistlib.load(fp)

    # 'NetworkServices' contains all configured network services keyed by UUID
    network_services = data.get('NetworkServices', {})

    # Iterate through the services and match by the 'DeviceName'
    for uuid, service in network_services.items():
        interface = service.get('Interface', {})
        if interface.get('DeviceName') == primary_interface:
            return uuid

    return None


def get_apple_usb_ethernet_interfaces() -> dict[str, str]:
    """ Return list of USB Ethernet interfaces. """
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


def notify_store() -> None:
    """ Notify system configuration store. """
    sc = ctypes.CDLL(find_library('SystemConfiguration'))
    cf = ctypes.CDLL(find_library('CoreFoundation'))

    kCFStringEncodingUTF8 = 0x08000100

    cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = c_void_p

    store_name = cf.CFStringCreateWithCString(None, b'MyStore', kCFStringEncodingUTF8)

    sc.SCDynamicStoreCreate.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p]
    sc.SCDynamicStoreCreate.restype = c_void_p

    store = sc.SCDynamicStoreCreate(None, store_name, None, None)
    if not store:
        raise RuntimeError('Failed to create SCDynamicStore')

    notify_key = cf.CFStringCreateWithCString(
        None,
        f'Prefs:commit:{NAT_CONFIGS}'.encode(),
        kCFStringEncodingUTF8
    )

    sc.SCDynamicStoreNotifyValue.argtypes = [c_void_p, c_void_p]
    sc.SCDynamicStoreNotifyValue.restype = None
    sc.SCDynamicStoreNotifyValue(store, notify_key)


class Bridge:
    def __init__(self, name: str, ipv4: str, ipv6: str, members: dict[str, str]) -> None:
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
        devices = {}
        for udid, interface in get_apple_usb_ethernet_interfaces().items():
            if interface not in bridge_members:
                continue
            devices[udid] = interface
        return cls(name, ipv4, ipv6, devices)

    def __repr__(self) -> str:
        members_formatted = '\n\t'.join([f'{interface}: {udid}' for udid, interface in self.members.items()])
        return f'Bridge details:\nipv4: {self.ipv4}\nipv6: {self.ipv6}\nmembers:\n\t{members_formatted}'


def verify_bridge(name: str = 'bridge100') -> None:
    """ Verify network bridge status. """
    try:
        result = IFCONFIG(name)
    except ProcessExecutionError as e:
        if f'interface {name} does not exist' in str(e):
            logger.debug('Internet sharing OFF')
        else:
            raise e
    else:
        logger.debug('Internet sharing ON')
        logger.debug(Bridge.parse_ifconfig(result))


def configure(primary_interface: str, members: list[str], network_name: str = "user's MacBook Pro") -> None:
    """ Configure NAT settings with given parameters. """
    with plist_editor(NAT_CONFIGS) as configs:
        primary_service = get_primary_service_uuid(primary_interface)
        configs.update({
            'NAT': {
                'AirPort': {
                    '40BitEncrypt': 1,
                    'Channel': 0,
                    'Enabled': 0,
                    'NetworkName': f'{network_name}',
                    'NetworkPassword': b''
                },
                'Enabled': 1,
                'NatPortMapDisabled': False,
                'PrimaryInterface': {
                    'Device': f'{primary_interface}',
                    'Enabled': 0,
                    'HardwareKey': '',
                },
                'PrimaryService': primary_service,
                'SharingDevices': members
            }
        })


async def set_sharing_state(state: SharingState) -> None:
    """ Set sharing state for NAT configuration. """
    with plist_editor(NAT_CONFIGS) as configs:
        if 'NAT' not in configs:
            return

        if state == SharingState.ON:
            new_state = 1
        elif state == SharingState.OFF:
            new_state = 0
        elif state == SharingState.TOGGLE:
            new_state = int(not configs['NAT']['Enabled'])
        else:
            raise ValueError("Invalid NAT sharing state")

        configs['NAT']['Enabled'] = new_state

    notify_store()
    time.sleep(SLEEP_TIME)
    verify_bridge()
