"""Owner-only credential storage, separate from report/SQLite backups."""
import json
import os
import tempfile
from pathlib import Path


def dpapi(data, decrypt=False):
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ValueError('Не удалось открыть защищённые настройки Windows. Используйте исходную учётную запись.')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


class SecretStore:
    def __init__(self, directory):
        self.directory = Path(directory) / 'connections-private'
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != 'nt': os.chmod(self.directory, 0o700)
        self.path = self.directory / ('credentials.dpapi' if os.name == 'nt' else 'credentials.json')

    def read(self):
        if not self.path.exists(): return {}
        raw = self.path.read_bytes()
        if os.name == 'nt': raw = dpapi(raw, True)
        return json.loads(raw)

    def write(self, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        if os.name == 'nt': raw = dpapi(raw)
        fd, name = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as file: file.write(raw)
            if os.name != 'nt': os.chmod(name, 0o600)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name): os.unlink(name)
