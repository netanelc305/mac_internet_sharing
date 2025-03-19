class MacInternetSharingException(Exception):
    """ Mac Internet Sharing related exception. """


class NoDeviceConnectedError(MacInternetSharingException):
    """ Raised when no device is connected. """


class AccessDeniedError(MacInternetSharingException):
    """ Raised when access to a resource is denied. """


class DeviceNotFoundError(MacInternetSharingException):
    """ Raised when the device with the specified udid is not found. """
    def __init__(self, udid: str):
        super().__init__()
        self.udid = udid


class NetworkServiceNotFoundError(MacInternetSharingException):
    """ Raised when the network service with the specified name is not found. """
    def __init__(self, name: str):
        super().__init__()
        self.name = name
