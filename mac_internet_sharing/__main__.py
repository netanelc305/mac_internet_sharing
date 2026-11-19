import logging
import sys
import time
from typing import Optional

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.prompt import Prompt
from rich.table import Table

from mac_internet_sharing.exceptions import AccessDeniedError, DeviceNotFoundError, NetworkServiceNotFoundError, \
    NoDeviceConnectedError, NoDeviceSelectedError, NotConfiguredError, SCPreferencesError
from mac_internet_sharing.mac_internet_sharing import SharingState, configure, console, \
    get_apple_usb_ethernet_interfaces, set_sharing_state, update_sharing_devices, verify_bridge
from mac_internet_sharing.network_preference import NetworkService, get_default_route_network_service, \
    get_network_service_by_name, get_network_services_names

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'], max_content_width=400)

logging.getLogger('plumbum.local').disabled = True
logging.basicConfig(level=logging.DEBUG, format='%(message)s', datefmt='[%X]',
                    handlers=[RichHandler(console=Console(stderr=True), show_path=False)])
logger = logging.getLogger(__name__)


def plug_n_share(network_service_name: Optional[str], timeout: int = 1) -> None:
    """ Continuously monitor for USB device changes and update SharingDevices. """
    network_service = get_network_service(network_service_name)

    logger.info('Starting USB device monitoring...')
    usb_devices = get_apple_usb_ethernet_interfaces()
    logger.info(f'Connected devices: {set(usb_devices)}')

    # Configure sharing with the initially detected interfaces.
    configure(network_service, list(usb_devices.values()))
    set_sharing_state(SharingState.ON)
    while True:
        time.sleep(timeout)
        current_usb_devices = get_apple_usb_ethernet_interfaces()
        if current_usb_devices == usb_devices:
            continue
        removed = set(usb_devices) - set(current_usb_devices)
        added = set(current_usb_devices) - set(usb_devices)
        if removed:
            logger.info(f'Removing devices {removed}')
        if added:
            logger.info(f'Adding devices {added}')
        usb_devices = current_usb_devices
        update_sharing_devices(list(usb_devices.values()))


def get_network_service(network_service_name: Optional[str]) -> NetworkService:
    """ Retrieve the network service by name or return the default if none provided. """
    if network_service_name is None:
        network_service = get_default_route_network_service()
        if network_service is not None:
            logger.info(
                f'Network service name was not provided; using default: {network_service.interface.user_defined_name}'
            )
    else:
        network_service = get_network_service_by_name(network_service_name)
    if network_service is None:
        raise NetworkServiceNotFoundError(network_service_name)
    return network_service


def prompt_devices(usb_devices: dict[str, str]) -> list[str]:
    """ Ask the user which of the connected devices to share with. Return their udids. """
    udids = list(usb_devices)
    table = Table(title='Connected devices')
    for column in ('#', 'UDID', 'Interface'):
        table.add_column(column)
    for index, udid in enumerate(udids, start=1):
        table.add_row(str(index), udid, usb_devices[udid])
    console.print(table)

    while True:
        try:
            answer = Prompt.ask('Devices to share (e.g. 1,2 / all / none)', console=console, default='all')
        except (KeyboardInterrupt, EOFError):
            raise NoDeviceSelectedError()
        answer = answer.strip().lower()
        if answer == 'all':
            return udids
        if answer == 'none':
            return []
        try:
            indexes = [int(index) for index in answer.replace(',', ' ').split()]
        except ValueError:
            indexes = []
        if indexes and all(1 <= index <= len(udids) for index in indexes):
            # Keep the listed order, without duplicates
            return [udids[index - 1] for index in sorted(set(indexes))]
        console.print(f'[red]Enter numbers between 1 and {len(udids)}, "all" or "none"')


def get_selected_devices(devices: Optional[tuple[str]]) -> list[str]:
    """ Retrieve the selected USB devices. """
    usb_devices = get_apple_usb_ethernet_interfaces()
    if not usb_devices:
        raise NoDeviceConnectedError()
    if not devices:
        devices = prompt_devices(usb_devices)
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
    set_sharing_state(SharingState.ON)


@cli.command('off')
def cli_off() -> None:
    """ Turn OFF Internet Sharing. """
    set_sharing_state(SharingState.OFF)


@cli.command('toggle')
def cli_toggle() -> None:
    """ Toggle Internet Sharing. """
    set_sharing_state(SharingState.TOGGLE)


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
    if not selected_devices:
        logger.info('No device was selected; turning internet sharing off')
        set_sharing_state(SharingState.OFF)
    elif start:
        set_sharing_state(SharingState.ON)


@cli.command('plug-n-share')
@click.option('-n', '--network', 'network_service_name', type=click.Choice(get_network_services_names()))
@click.option('-t', '--timeout', default=5, help='Polling interval in seconds.')
def cli_plug_n_share(network_service_name: Optional[str], timeout: int = 5) -> None:
    """ Automatically detect USB devices and update internet sharing. """
    try:
        plug_n_share(network_service_name, timeout)
    except KeyboardInterrupt:
        logger.info('Plug And Share stopped by user turning off internet sharing.')
        set_sharing_state(SharingState.OFF)


def main() -> None:
    try:
        cli()
        return
    except NoDeviceConnectedError:
        logger.error('Device is not connected')
    except NoDeviceSelectedError:
        logger.error('Device selection was aborted')
    except DeviceNotFoundError as e:
        logger.error(f'Device not found: {e.udid}')
    except AccessDeniedError:
        logger.error('This command requires root privileges. Consider retrying with "sudo".')
    except NotConfiguredError:
        logger.error('Internet sharing is not configured. Run "misha configure" first.')
    except NetworkServiceNotFoundError as e:
        if e.name is None:
            logger.error('No network service found for the default route. Specify one using "--network".')
        else:
            logger.error(f'Network service not found: {e.name}')
    except SCPreferencesError as e:
        logger.error(f'SystemConfiguration error: {e}')
    sys.exit(1)


if __name__ == '__main__':
    main()
