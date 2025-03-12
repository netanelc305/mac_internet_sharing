import plistlib
from collections import UserList
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

INTERFACE_PREFERENCES = Path('/Library/Preferences/SystemConfiguration/preferences.plist')


@dataclass
class Interface:
    devices_name: str
    user_defined_name: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Interface':
        """ Create an Interface from a dict. """
        return cls(data['DeviceName'], data['UserDefinedName'])


@dataclass
class NetworkService:
    uuid: str
    interface: Interface


class NetworkServiceList(UserList):
    def get_by_user_defined_name(self, user_defined_name: str) -> Optional[NetworkService]:
        """ Get network service by user defined name. """
        return self._find_network_service(
            lambda ns: ns.interface.user_defined_name == user_defined_name
        )

    def get_by_user_devices_name(self, devices_name: str) -> Optional[NetworkService]:
        """ Get network service by device name. """
        return self._find_network_service(
            lambda ns: ns.interface.devices_name == devices_name
        )

    def get_by_uuid(self, uuid: str) -> Optional[NetworkService]:
        """ Get network service by UUID. """
        return self._find_network_service(lambda ns: ns.uuid == uuid)

    def _find_network_service(self, condition: Callable[[NetworkService], bool]) -> Optional[NetworkService]:
        """ Find a network service that matches the condition. """
        for ns in self.data:
            if condition(ns):
                return ns
        return None


class NetworkPreferencePlist:
    def __init__(self, path: Path) -> None:
        """ Initialize with the given plist path. """
        self.path: Path = path
        with path.open('rb') as f:
            self.data = plistlib.load(f)

        self.network_services: NetworkServiceList = self._parse_network_services()
        self.current_set: Optional[NetworkService] = self._current_set()

    def _parse_network_services(self) -> NetworkServiceList:
        """ Parse network services from plist data. """
        network_services = NetworkServiceList()
        for uuid, service_data in self.data.get('NetworkServices', {}).items():
            interface = Interface.from_dict(service_data.get('Interface'))
            network_services.append(NetworkService(uuid, interface))
        return network_services

    def _current_set(self) -> Optional[NetworkService]:
        """ Get current set network service. """
        current_set_uuid = self.data.get('CurrentSet').split('/')[-1]
        current_set_device_name = list(self.data.get('Sets')[current_set_uuid]['Network']['Interface'].keys())[0]
        return self.network_services.get_by_user_devices_name(current_set_device_name)


def get_network_services_names() -> list[str]:
    """ Return list of network service names. """
    try:
        names = [services.interface.user_defined_name for services in
                 NetworkPreferencePlist(INTERFACE_PREFERENCES).network_services]
    except KeyError:
        names = []
    return names
