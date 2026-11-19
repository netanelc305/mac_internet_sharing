from dataclasses import dataclass
from typing import Optional

from plumbum import ProcessExecutionError, local

from mac_internet_sharing.native_bridge import SCPreferences

ROUTE = local['route']

# Resolved by SCPreferences relative to /Library/Preferences/SystemConfiguration
NETWORK_PREFS_ID = 'preferences.plist'
NETWORK_PREFS_NAME = 'mac_internet_sharing'


@dataclass
class Interface:
    devices_name: str
    user_defined_name: str


@dataclass
class NetworkService:
    uuid: str
    user_defined_name: str
    interface: Interface


def get_network_services() -> list[NetworkService]:
    """ Return the network services which are backed by a network device. """
    with SCPreferences(NETWORK_PREFS_NAME, NETWORK_PREFS_ID, lock=False) as prefs:
        services = prefs.get('NetworkServices') or {}

    network_services = []
    for uuid, service in services.items():
        interface = service.get('Interface', {})
        device_name = interface.get('DeviceName')
        if device_name is None:
            # e.g. VPN services
            continue
        network_services.append(NetworkService(
            uuid,
            service.get('UserDefinedName', device_name),
            Interface(device_name, interface.get('UserDefinedName', device_name))))
    return network_services


def get_network_services_names() -> list[str]:
    """ Return list of network service names. """
    return [service.user_defined_name for service in get_network_services()]


def get_network_service_by_name(user_defined_name: str) -> Optional[NetworkService]:
    """ Return the network service with the given user defined name. """
    for service in get_network_services():
        if service.user_defined_name == user_defined_name:
            return service
    return None


def get_default_route_interface_name() -> Optional[str]:
    """ Return default route interface name. """
    try:
        output = ROUTE('get', 'default')
    except ProcessExecutionError:
        # No default route
        return None
    for line in output.splitlines():
        # Extract the interface name from the line, e.g., "interface: en0"
        if 'interface:' not in line:
            continue
        return line.split(':', 1)[1].strip()
    return None


def get_default_route_network_service() -> Optional[NetworkService]:
    """ Return the network service of the default route. """
    device_name = get_default_route_interface_name()
    for service in get_network_services():
        if service.interface.devices_name == device_name:
            return service
    return None
