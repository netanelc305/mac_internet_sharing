import asyncio
import logging
from typing import Optional

import click
import coloredlogs
import inquirer3

from mac_internet_sharing.exceptions import AccessDeniedError, DeviceNotFoundError, NoDeviceConnectedError
from mac_internet_sharing.mac_internet_sharing import SharingState, configure, get_apple_usb_ethernet_interfaces, \
    set_sharing_state, update_sharing_devices, verify_bridge
from mac_internet_sharing.network_preference import INTERFACE_PREFERENCES, NetworkPreferencePlist, NetworkService, \
    get_default_route_network_service, get_network_services_names

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'], max_content_width=400)

logging.getLogger('plumbum.local').disabled = True
logging.getLogger('asyncio').disabled = True
coloredlogs.install(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def plug_n_share_task(network_service_name: Optional[str], timeout: int = 1):
    """ Continuously monitor for USB device changes and update SharingDevices. """
    network_service = get_network_service(network_service_name)

    logger.info('Starting USB device monitoring...')
    prev_usb_devices = get_apple_usb_ethernet_interfaces()
    logger.info(f'Connected devices: {set(prev_usb_devices.keys())}')

    # Configure sharing with the initially detected interfaces.
    configure(network_service, list(prev_usb_devices.values()))
    await set_sharing_state(SharingState.ON)
    while True:
        current_usb_devices = get_apple_usb_ethernet_interfaces()
        if prev_usb_devices != current_usb_devices:
            if len(prev_usb_devices) > len(current_usb_devices):
                logger.info(f'Removing devices {set(prev_usb_devices.keys()) - set(current_usb_devices.keys())}')
            else:
                logger.info(f'Adding devices {set(current_usb_devices.keys()) - set(prev_usb_devices.keys())}')
            prev_usb_devices = current_usb_devices
            interfaces = set(prev_usb_devices.values()).intersection(prev_usb_devices.values())
            await update_sharing_devices(interfaces)
            verify_bridge()
        await asyncio.sleep(timeout)


def get_network_service(network_service_name: Optional[str]) -> NetworkService:
    """ Retrieve the network service by name or return the default if none provided. """
    network_preferences = NetworkPreferencePlist(INTERFACE_PREFERENCES)
    if network_service_name is None:
        network_service = get_default_route_network_service()
        logger.info(
            f'Network service name was not provided; using default: {network_service.interface.user_defined_name}'
        )
    else:
        network_service = network_preferences.network_services.get_by_user_defined_name(network_service_name)
        if network_service is None:
            raise ValueError(f'Network service "{network_service_name}" not found')
    return network_service


def get_selected_devices(devices: Optional[tuple[str]]) -> list[str]:
    """ Retrieve the selected USB devices. """
    usb_devices = get_apple_usb_ethernet_interfaces()
    if not usb_devices:
        raise NoDeviceConnectedError()
    if not devices:
        udids = list(usb_devices.keys())
        questions = [
            inquirer3.Checkbox(
                'Devices',
                message='Choose devices',
                choices=udids,
                default=udids,
            ),
        ]
        devices = inquirer3.prompt(questions)['Devices']
    try:
        return [usb_devices[x] for x in devices]
    except KeyError as e:
        raise DeviceNotFoundError(e.args[0])


@click.group(context_settings=CONTEXT_SETTINGS)
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
def cli_configure(network_service_name: Optional[str] = None,
                  devices: Optional[tuple[str]] = None,
                  start: bool = False) -> None:
    """ Manually configure internet sharing with specified devices. """
    network_service = get_network_service(network_service_name)
    selected_devices = get_selected_devices(devices)
    configure(network_service, selected_devices)
    if start:
        asyncio.run(set_sharing_state(SharingState.ON))


@cli.command('plug-n-share')
@click.option('-n', '--network', 'network_service_name', type=click.Choice(get_network_services_names()))
@click.option('-t', '--timeout', default=5, help='Polling interval in seconds.')
def cli_plug_n_share(network_service_name: Optional[str], timeout: int = 5) -> None:
    """ Automatically detect USB devices and update internet sharing. """
    try:
        asyncio.run(plug_n_share_task(network_service_name, timeout))
    except KeyboardInterrupt:
        logger.info('Plug And Share stopped by user turning off internet sharing.')
        asyncio.run(set_sharing_state(SharingState.OFF))


def main():
    try:
        cli()
    except NoDeviceConnectedError:
        logger.error('Device is not connected')
    except DeviceNotFoundError as e:
        logger.error(f'Device not found: {e.udid}')
    except AccessDeniedError:
        logger.error('This command requires root privileges. Consider retrying with "sudo".')


if __name__ == '__main__':
    main()
