from __future__ import annotations

import base64
import getpass
import hashlib
import sys
from pathlib import Path


class SecureCredentialStore:
    """Small credential abstraction for API profile keys.

    On Windows this uses DPAPI through ``CryptProtectData``. Other platforms use
    a per-user obfuscated file fallback so tests and development remain portable;
    callers still treat it as secret material and never persist keys elsewhere.
    """

    def __init__(self, directory: Path, namespace: str = "S-Talking") -> None:
        self.directory = directory
        self.namespace = namespace
        self.directory.mkdir(parents=True, exist_ok=True)

    def set_password(self, key: str, secret: str) -> None:
        path = self._path(key)
        if not secret:
            self.delete_password(key)
            return
        protected = self._protect(secret.encode("utf-8"), key)
        path.write_text(base64.b64encode(protected).decode("ascii"), encoding="utf-8")

    def get_password(self, key: str) -> str | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            protected = base64.b64decode(path.read_text(encoding="utf-8"))
            return self._unprotect(protected, key).decode("utf-8")
        except Exception:
            return None

    def delete_password(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(f"{self.namespace}:{key}".encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.cred"

    def _protect(self, value: bytes, key: str) -> bytes:
        if sys.platform == "win32":
            try:
                return self._dpapi(value, protect=True)
            except Exception:
                pass
        return self._xor(value, key)

    def _unprotect(self, value: bytes, key: str) -> bytes:
        if sys.platform == "win32":
            try:
                return self._dpapi(value, protect=False)
            except Exception:
                pass
        return self._xor(value, key)

    def _xor(self, value: bytes, key: str) -> bytes:
        seed = hashlib.sha256(f"{self.namespace}:{key}:{getpass.getuser()}".encode("utf-8")).digest()
        return bytes(byte ^ seed[index % len(seed)] for index, byte in enumerate(value))

    @staticmethod
    def _dpapi(value: bytes, *, protect: bool) -> bytes:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        buffer = ctypes.create_string_buffer(value)
        source = DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        target = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if protect:
            ok = crypt32.CryptProtectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target))
        else:
            ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target))
        if not ok:
            raise OSError("DPAPI credential operation failed.")
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            kernel32.LocalFree(target.pbData)
