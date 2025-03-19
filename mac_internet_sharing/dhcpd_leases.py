import re
from collections import UserList
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DHCPD_LEASES = Path('/var/db/dhcpd_leases')


@dataclass
class LeaseEntry:
    """ Represents a single DHCP lease entry. """
    name: str
    ip_address: str
    hw_address: str

    @classmethod
    def from_entry(cls, entry: str) -> 'LeaseEntry':
        """ Parses a single lease entry block and returns a LeaseEntry object. """

        name_pattern = re.search(r'name=(.*)', entry)
        ip_pattern = re.search(r'ip_address=([\d.]+)', entry)
        mac_pattern = re.search(r'hw_address=1,([0-9a-fA-F:]+)', entry)

        return cls(
            name=name_pattern.group(1) if name_pattern else "Unknown",
            ip_address=ip_pattern.group(1) if ip_pattern else "Unknown",
            hw_address=mac_pattern.group(1) if mac_pattern else "Unknown"
        )


class LeaseList(UserList):
    """ A list subclass to store LeaseEntry objects. """

    @classmethod
    def from_file(cls, lease_file: Path) -> 'LeaseList':
        with lease_file.open("r") as f:
            data = f.read()

        # Split entries based on lease block structures `{ ... }`
        lease_entries = re.findall(r"\{(.*?)\}", data, re.DOTALL)

        # Parse each entry and create LeaseEntry objects
        leases = [LeaseEntry.from_entry(entry.strip()) for entry in lease_entries]

        return cls(leases)

    def get_first_entry_matching_prefix(self, prefix_length: int, mac_address: str) -> Optional[LeaseEntry]:
        """ Return lease entry if the first 'prefix_length' parts of this lease's MAC address match the given MAC address. """

        for entry in self.data:
            lease_mac_parts = entry.hw_address.split(":")[:prefix_length]
            compare_mac_parts = mac_address.split(":")[:prefix_length]
            if lease_mac_parts != compare_mac_parts:
                continue
            return entry


def get_dhcp_leases() -> LeaseList:
    return LeaseList.from_file(DHCPD_LEASES)
