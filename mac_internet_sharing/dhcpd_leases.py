import re
from collections import UserList
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DHCPD_LEASES = Path('/var/db/dhcpd_leases')


def normalize_mac(mac_address: str) -> Optional[tuple[int, ...]]:
    """ Return a comparable form of a MAC address, since leading zeros are not always printed (e.g. `56:9:1:de`). """
    try:
        return tuple(int(part, 16) for part in mac_address.split(':'))
    except ValueError:
        return None


@dataclass
class LeaseEntry:
    """ Represents a single DHCP lease entry. """
    name: str
    ip_address: str
    hw_address: str
    expiry: int = 0

    @classmethod
    def from_entry(cls, entry: str) -> 'LeaseEntry':
        """ Parses a single lease entry block and returns a LeaseEntry object. """

        name_pattern = re.search(r'name=(.*)', entry)
        ip_pattern = re.search(r'ip_address=([\d.]+)', entry)
        mac_pattern = re.search(r'hw_address=1,([0-9a-fA-F:]+)', entry)
        expiry_pattern = re.search(r'lease=0x([0-9a-fA-F]+)', entry)

        return cls(
            name=name_pattern.group(1) if name_pattern else "Unknown",
            ip_address=ip_pattern.group(1) if ip_pattern else "Unknown",
            hw_address=mac_pattern.group(1) if mac_pattern else "Unknown",
            expiry=int(expiry_pattern.group(1), 16) if expiry_pattern else 0
        )


class LeaseList(UserList):
    """ A list subclass to store LeaseEntry objects. """

    @classmethod
    def from_file(cls, lease_file: Path) -> 'LeaseList':
        if not lease_file.exists():
            return cls([])

        data = lease_file.read_text()

        # Split entries based on lease block structures `{ ... }`
        lease_entries = re.findall(r"\{(.*?)\}", data, re.DOTALL)

        # Parse each entry and create LeaseEntry objects
        leases = [LeaseEntry.from_entry(entry.strip()) for entry in lease_entries]

        return cls(leases)

    def get_by_mac_address(self, mac_address: str) -> Optional[LeaseEntry]:
        """ Return the most recent lease given to the specified MAC address. """
        mac = normalize_mac(mac_address)
        if mac is None:
            return None
        matching = [entry for entry in self.data if normalize_mac(entry.hw_address) == mac]
        return max(matching, key=lambda entry: entry.expiry, default=None)


def get_dhcp_leases() -> LeaseList:
    return LeaseList.from_file(DHCPD_LEASES)
