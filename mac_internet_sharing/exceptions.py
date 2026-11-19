from typing import Optional


class MacInternetSharingException(Exception):
    """ Mac Internet Sharing related exception. """


class NoDeviceConnectedError(MacInternetSharingException):
    """ Raised when no device is connected. """


class NoDeviceSelectedError(MacInternetSharingException):
    """ Raised when the device selection is aborted or cannot be prompted for. """


class AccessDeniedError(MacInternetSharingException):
    """ Raised when access to a resource is denied. """


class NotConfiguredError(MacInternetSharingException):
    """ Raised when internet sharing was never configured. """


class SCPreferencesError(MacInternetSharingException):
    """ Raised when a SystemConfiguration call fails. """


class DeviceNotFoundError(MacInternetSharingException):
    """ Raised when the device with the specified udid is not found. """
    def __init__(self, udid: str):
        super().__init__()
        self.udid = udid


class NetworkServiceNotFoundError(MacInternetSharingException):
    """ Raised when the requested network service is not found. """
    def __init__(self, name: Optional[str]):
        super().__init__()
        self.name = name
