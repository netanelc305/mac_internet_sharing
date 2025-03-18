import asyncio
import logging
from typing import Optional

import click
import coloredlogs
import inquirer3

from mac_internet_sharing.mac_internet_sharing import SharingState, configure, get_apple_usb_ethernet_interfaces, \
    set_sharing_state, verify_bridge
from mac_internet_sharing.network_preference import INTERFACE_PREFERENCES, NetworkPreferencePlist, \
    get_default_route_network_service, get_network_services_names

logging.getLogger('plumbum.local').disabled = True
logging.getLogger('asyncio').disabled = True
coloredlogs.install(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    """ CLI group entry point. """
    pass


@cli.command('on')
def cli_on() -> None:
    """ Turn On Internet Sharing. """
    asyncio.run(set_sharing_state(SharingState.ON))


@cli.command('off')
def cli_off() -> None:
    """ Turn OFF Internet Sharing. """
    asyncio.run(set_sharing_state(SharingState.OFF))


@cli.command('toggle')
def cli_toggle() -> None:
    """ Toggle Internet Sharing. """
    asyncio.run(set_sharing_state(SharingState.TOGGLE))


@cli.command('status')
def cli_status() -> None:
    """ Verify network bridge. """
    verify_bridge()


@cli.command('configure')
@click.option('-n', '--network', 'network_service_name', type=click.Choice(get_network_services_names()))
@click.option('-u', '--udid', 'devices', multiple=True, help='IDevice udid')
@click.option('-s', '--start', is_flag=True, default=False, help='Auto start sharing')
def cli_configure(network_service_name: Optional[str] = None, devices: Optional[tuple[str]] = None,
                  start: bool = False) -> None:
    """ Share the internet with specified devices. """
    network_preferences = NetworkPreferencePlist(INTERFACE_PREFERENCES)
    if network_service_name is None:
        network_service = get_default_route_network_service()
        logger.info(
            f'Network service name was not provided using default: {network_service.interface.user_defined_name}')
    else:
        network_service = network_preferences.network_services.get_by_user_defined_name(network_service_name)
        if network_service is None:
            raise ValueError(f'Network service "{network_service_name}" not found')

    usb_devices = get_apple_usb_ethernet_interfaces()
    if not len(devices) > 0:
        udids = list(usb_devices.keys())
        questions = [
            inquirer3.Checkbox('Devices',
                               message='Choose devices',
                               choices=udids,
                               default=udids,
                               ),
        ]
        devices = inquirer3.prompt(questions)['Devices']
    try:
        devices = [usb_devices[x] for x in devices]
    except KeyError as e:
        logger.error(f'No device with UDID {e.args[0]}')
    else:
        configure(network_service, devices)
        if start:
            asyncio.run(set_sharing_state(SharingState.ON))


if __name__ == '__main__':
    cli()
