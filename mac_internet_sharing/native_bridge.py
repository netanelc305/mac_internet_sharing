import ctypes
import plistlib
from ctypes import c_bool, c_char_p, c_int, c_long, c_ulong, c_void_p
from ctypes.util import find_library
from typing import Any, Optional

from mac_internet_sharing.exceptions import AccessDeniedError

kCFStringEncodingUTF8 = 0x08000100
kCFPropertyListImmutable = 0
kCFPropertyListBinaryFormat_v1_0 = 200
kSCStatusAccessError = 1003

# Load shared libraries
_cf = ctypes.CDLL(find_library('CoreFoundation'))
_sc = ctypes.CDLL(find_library('SystemConfiguration'))

_cf.CFRelease.argtypes = [c_void_p]
_cf.CFRelease.restype = None

_cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, ctypes.c_uint32]
_cf.CFStringCreateWithCString.restype = c_void_p

_cf.CFDataCreate.argtypes = [c_void_p, c_char_p, c_long]
_cf.CFDataCreate.restype = c_void_p

_cf.CFDataGetBytePtr.argtypes = [c_void_p]
_cf.CFDataGetBytePtr.restype = c_void_p

_cf.CFDataGetLength.argtypes = [c_void_p]
_cf.CFDataGetLength.restype = c_long

_cf.CFPropertyListCreateWithData.argtypes = [c_void_p, c_void_p, c_ulong, c_void_p, c_void_p]
_cf.CFPropertyListCreateWithData.restype = c_void_p

_cf.CFPropertyListCreateData.argtypes = [c_void_p, c_void_p, c_long, c_ulong, c_void_p]
_cf.CFPropertyListCreateData.restype = c_void_p

# Configure SystemConfiguration functions
_sc.SCError.argtypes = []
_sc.SCError.restype = c_int

_sc.SCErrorString.argtypes = [c_int]
_sc.SCErrorString.restype = c_char_p

_sc.SCPreferencesCreate.argtypes = [c_void_p, c_void_p, c_void_p]
_sc.SCPreferencesCreate.restype = c_void_p

_sc.SCPreferencesLock.argtypes = [c_void_p, c_bool]
_sc.SCPreferencesLock.restype = c_bool

_sc.SCPreferencesUnlock.argtypes = [c_void_p]
_sc.SCPreferencesUnlock.restype = c_bool

_sc.SCPreferencesGetValue.argtypes = [c_void_p, c_void_p]
_sc.SCPreferencesGetValue.restype = c_void_p

_sc.SCPreferencesSetValue.argtypes = [c_void_p, c_void_p, c_void_p]
_sc.SCPreferencesSetValue.restype = c_bool

_sc.SCPreferencesCommitChanges.argtypes = [c_void_p]
_sc.SCPreferencesCommitChanges.restype = c_bool


class SCPreferencesError(Exception):
    """ Raised when a SystemConfiguration preferences call fails. """


def _raise_sc_error(function_name: str) -> None:
    """ Raise an exception describing the last SystemConfiguration error. """
    error = _sc.SCError()
    if error == kSCStatusAccessError:
        raise AccessDeniedError()
    raise SCPreferencesError(f'{function_name} failed: {_sc.SCErrorString(error).decode()} ({error})')


def _cf_string(string: str) -> c_void_p:
    """ Create a Core Foundation string. The caller owns the result. """
    return _cf.CFStringCreateWithCString(None, string.encode(), kCFStringEncodingUTF8)


def _to_cf_property_list(value: Any) -> c_void_p:
    """ Convert a python object into a Core Foundation property list. The caller owns the result. """
    serialized = plistlib.dumps(value, fmt=plistlib.FMT_BINARY)
    data = _cf.CFDataCreate(None, serialized, len(serialized))
    try:
        result = _cf.CFPropertyListCreateWithData(None, data, kCFPropertyListImmutable, None, None)
    finally:
        _cf.CFRelease(data)
    if not result:
        raise SCPreferencesError('CFPropertyListCreateWithData failed')
    return result


def _from_cf_property_list(value: c_void_p) -> Any:
    """ Convert a Core Foundation property list into a python object. """
    data = _cf.CFPropertyListCreateData(None, value, kCFPropertyListBinaryFormat_v1_0, 0, None)
    if not data:
        raise SCPreferencesError('CFPropertyListCreateData failed')
    try:
        return plistlib.loads(ctypes.string_at(_cf.CFDataGetBytePtr(data), _cf.CFDataGetLength(data)))
    finally:
        _cf.CFRelease(data)


class SCPreferences:
    """
    Exclusive SCPreferences session over a preferences file in /Library/Preferences/SystemConfiguration.

    The session is locked for the duration of the `with` block. Nothing is written unless `commit()` is called.
    """

    def __init__(self, name: str, prefs_id: str) -> None:
        self._name = name
        self._prefs_id = prefs_id
        self._prefs = None

    def __enter__(self) -> 'SCPreferences':
        cf_name = _cf_string(self._name)
        cf_prefs_id = _cf_string(self._prefs_id)
        try:
            self._prefs = _sc.SCPreferencesCreate(None, cf_name, cf_prefs_id)
        finally:
            _cf.CFRelease(cf_name)
            _cf.CFRelease(cf_prefs_id)
        if not self._prefs:
            _raise_sc_error('SCPreferencesCreate')
        if not _sc.SCPreferencesLock(self._prefs, True):
            try:
                _raise_sc_error('SCPreferencesLock')
            finally:
                _cf.CFRelease(self._prefs)
                self._prefs = None
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        _sc.SCPreferencesUnlock(self._prefs)
        _cf.CFRelease(self._prefs)
        self._prefs = None

    def get(self, key: str) -> Optional[Any]:
        """ Return the value stored under the given key, or None if missing. """
        cf_key = _cf_string(key)
        try:
            # Returned reference is owned by the session
            value = _sc.SCPreferencesGetValue(self._prefs, cf_key)
        finally:
            _cf.CFRelease(cf_key)
        if not value:
            return None
        return _from_cf_property_list(value)

    def set(self, key: str, value: Any) -> None:
        """ Set the value stored under the given key. """
        cf_key = _cf_string(key)
        cf_value = _to_cf_property_list(value)
        try:
            if not _sc.SCPreferencesSetValue(self._prefs, cf_key, cf_value):
                _raise_sc_error('SCPreferencesSetValue')
        finally:
            _cf.CFRelease(cf_key)
            _cf.CFRelease(cf_value)

    def commit(self) -> None:
        """ Write the changes to persistent storage and notify the preferences observers. """
        if not _sc.SCPreferencesCommitChanges(self._prefs):
            _raise_sc_error('SCPreferencesCommitChanges')
