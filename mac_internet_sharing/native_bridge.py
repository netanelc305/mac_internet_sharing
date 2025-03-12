import ctypes
from ctypes import c_char_p, c_void_p
from ctypes.util import find_library

kCFStringEncodingUTF8 = 0x08000100

# Load shared libraries
_cf = ctypes.CDLL(find_library('CoreFoundation'))
_sc = ctypes.CDLL(find_library('SystemConfiguration'))

_cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, ctypes.c_uint32]
_cf.CFStringCreateWithCString.restype = c_void_p


def CFStringCreateWithCString(string: bytes) -> c_void_p:
    """ Create a Core Foundation string. """
    return _cf.CFStringCreateWithCString(None, string, kCFStringEncodingUTF8)


# Configure SystemConfiguration functions
_sc.SCDynamicStoreCreate.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p]
_sc.SCDynamicStoreCreate.restype = c_void_p

_sc.SCDynamicStoreNotifyValue.argtypes = [c_void_p, c_void_p]
_sc.SCDynamicStoreNotifyValue.restype = None


def SCDynamicStoreCreate(store_name: bytes) -> c_void_p:
    """ Create a SCDynamicStore with the given store name. """
    cf_store_name = CFStringCreateWithCString(store_name)
    store = _sc.SCDynamicStoreCreate(None, cf_store_name, None, None)
    if not store:
        raise RuntimeError('Failed to create SCDynamicStore')
    return store


def SCDynamicStoreNotifyValue(store: c_void_p, key: bytes) -> None:
    """ Notify the given key in the SCDynamicStore. """
    cf_key = CFStringCreateWithCString(key)
    _sc.SCDynamicStoreNotifyValue(store, cf_key)
