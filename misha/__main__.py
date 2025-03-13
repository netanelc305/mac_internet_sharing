import asyncio
import logging

import click
import coloredlogs
import inquirer3

from misha.misha import SharingState, configure, get_apple_usb_ethernet_interfaces, set_sharing_state, verify_bridge

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
@click.argument('primary_interface')
@click.option('-u', '--udid', 'devices', multiple=True, required=False,
              help='IDevice udid')
@click.option('-s', '--start', is_flag=True, default=False)
def cli_configure(primary_interface: str, devices: tuple[str], network_name="user's MacBook Pro", start: bool = False) -> None:
    """ Share the internet with specified devices. """
    usb_devices = get_apple_usb_ethernet_interfaces()
    if not len(devices) > 0:
        questions = [
            inquirer3.Checkbox('Devices',
                               message='Choose devices',
                               choices=usb_devices,
                               ),
        ]
        devices = inquirer3.prompt(questions)['Devices']
    try:
        devices = [usb_devices[x] for x in devices]
    except KeyError as e:
        logger.error(f'No device with UDID {e.args[0]}')
    else:
        configure(primary_interface, devices, network_name)
        if start:
            asyncio.run(set_sharing_state(SharingState.ON))


if __name__ == '__main__':
    cli()
