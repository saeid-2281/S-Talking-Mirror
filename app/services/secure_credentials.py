from __future__ import annotations

import base64
import ctypes
import getpass
import hashlib
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol


class CredentialBackend(Protocol):
    def set_password(self, target: str, secret: str) -> None: ...

    def get_password(self, target: str) -> str | None: ...

    def delete_password(self, target: str) -> None: ...


class WindowsCredentialManager:
    """Minimal wrapper around the Windows Credential Manager generic-credential API."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", wintypes.LPVOID),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows Credential Manager is available only on Windows.")
        self._advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi32.CredWriteW.argtypes = [ctypes.POINTER(self.CREDENTIALW), wintypes.DWORD]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(self.CREDENTIALW)),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [wintypes.LPVOID]
        self._advapi32.CredFree.restype = None

    def set_password(self, target: str, secret: str) -> None:
        value = secret.encode("utf-8")
        if len(value) > 512:
            raise ValueError("Credential exceeds the Windows generic credential size limit.")
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        credential = self.CREDENTIALW()
        credential.Type = self.CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(value)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = getpass.getuser()
        if not self._advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def get_password(self, target: str) -> str | None:
        pointer = ctypes.POINTER(self.CREDENTIALW)()
        if not self._advapi32.CredReadW(
            target,
            self.CRED_TYPE_GENERIC,
            0,
            ctypes.byref(pointer),
        ):
            error = ctypes.get_last_error()
            if error == self.ERROR_NOT_FOUND:
                return None
            raise ctypes.WinError(error)
        try:
            credential = pointer.contents
            value = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            return value.decode("utf-8")
        finally:
            self._advapi32.CredFree(pointer)

    def delete_password(self, target: str) -> None:
        if self._advapi32.CredDeleteW(target, self.CRED_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != self.ERROR_NOT_FOUND:
            raise ctypes.WinError(error)


class SecureCredentialStore:
    """Store provider secrets without persisting raw keys in project metadata.

    Frozen Windows production builds use Credential Manager and migrate legacy
    DPAPI files on first successful read. Source-mode Windows runs keep the
    DPAPI-file backend so development and automated tests remain isolated.
    Non-Windows development uses a per-user obfuscated file fallback; production
    security audits report that fallback as degraded rather than encryption.
    """

    def __init__(
        self,
        directory: Path,
        namespace: str = "S-Talking",
        *,
        native_backend: CredentialBackend | None = None,
        platform: str | None = None,
        use_native: bool | None = None,
    ) -> None:
        self.directory = directory
        self.namespace = namespace
        self.platform = platform or sys.platform
        self.directory.mkdir(parents=True, exist_ok=True)
        self._native_backend = native_backend
        self._native_error = ""
        self._native_requested = (
            bool(use_native)
            if use_native is not None
            else self.platform == "win32" and bool(getattr(sys, "frozen", False))
        )
        if self._native_requested and self.platform == "win32" and self._native_backend is None:
            try:
                self._native_backend = WindowsCredentialManager()
            except Exception as exc:
                self._native_error = str(exc)

    @property
    def backend_name(self) -> str:
        if self._native_backend is not None:
            return "windows-credential-manager"
        if self.platform == "win32":
            return "windows-dpapi-file"
        return "development-file-fallback"

    def security_status(self) -> tuple[str, str]:
        if self.backend_name == "windows-credential-manager":
            return "pass", "Provider credentials are stored in Windows Credential Manager."
        if self.backend_name == "windows-dpapi-file":
            if self._native_requested:
                detail = "Windows Credential Manager is unavailable; DPAPI-protected files are used."
                if self._native_error:
                    detail += f" Native backend error: {self._native_error}"
                return "warn", detail
            return (
                "warn",
                "Source-mode Windows uses isolated DPAPI-protected files; frozen production builds use Credential Manager.",
            )
        return (
            "warn",
            "A development-only per-user file fallback is active; production Windows builds use Credential Manager.",
        )

    def set_password(self, key: str, secret: str) -> None:
        if not secret:
            self.delete_password(key)
            return
        if self._native_backend is not None:
            self._native_backend.set_password(self._target(key), secret)
            self._secure_delete(self._path(key))
            return
        protected = self._protect(secret.encode("utf-8"), key)
        encoded = base64.b64encode(protected).decode("ascii")
        self._atomic_write(self._path(key), encoded)

    def get_password(self, key: str) -> str | None:
        if self._native_backend is not None:
            native = self._native_backend.get_password(self._target(key))
            if native is not None:
                return native
            legacy = self._read_file_secret(key)
            if legacy is not None:
                self._native_backend.set_password(self._target(key), legacy)
                self._secure_delete(self._path(key))
            return legacy
        return self._read_file_secret(key)

    def delete_password(self, key: str) -> None:
        if self._native_backend is not None:
            self._native_backend.delete_password(self._target(key))
        self._secure_delete(self._path(key))

    def legacy_file_count(self) -> int:
        return sum(1 for path in self.directory.glob("*.cred") if path.is_file())

    def _read_file_secret(self, key: str) -> str | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            protected = base64.b64decode(path.read_text(encoding="utf-8"), validate=True)
            return self._unprotect(protected, key).decode("utf-8")
        except Exception:
            return None

    def _target(self, key: str) -> str:
        digest = hashlib.sha256(f"{self.namespace}:{key}".encode("utf-8")).hexdigest()
        return f"{self.namespace}/provider/{digest}"

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(f"{self.namespace}:{key}".encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.cred"

    def _protect(self, value: bytes, key: str) -> bytes:
        if self.platform == "win32":
            return self._dpapi(value, protect=True)
        return self._xor(value, key)

    def _unprotect(self, value: bytes, key: str) -> bytes:
        if self.platform == "win32":
            return self._dpapi(value, protect=False)
        return self._xor(value, key)

    def _xor(self, value: bytes, key: str) -> bytes:
        seed = hashlib.sha256(
            f"{self.namespace}:{key}:{getpass.getuser()}".encode("utf-8")
        ).digest()
        return bytes(byte ^ seed[index % len(seed)] for index, byte in enumerate(value))

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(path)

    @staticmethod
    def _secure_delete(path: Path) -> None:
        if not path.exists() or not path.is_file():
            return
        try:
            size = path.stat().st_size
            with path.open("r+b", buffering=0) as handle:
                remaining = size
                while remaining > 0:
                    chunk_size = min(64 * 1024, remaining)
                    handle.write(os.urandom(chunk_size))
                    remaining -= chunk_size
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            pass
        path.unlink(missing_ok=True)

    @staticmethod
    def _dpapi(value: bytes, *, protect: bool) -> bytes:
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        buffer = ctypes.create_string_buffer(value)
        source = DATA_BLOB(
            len(value),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)),
        )
        target = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if protect:
            ok = crypt32.CryptProtectData(
                ctypes.byref(source),
                None,
                None,
                None,
                None,
                0,
                ctypes.byref(target),
            )
        else:
            ok = crypt32.CryptUnprotectData(
                ctypes.byref(source),
                None,
                None,
                None,
                None,
                0,
                ctypes.byref(target),
            )
        if not ok:
            raise OSError("DPAPI credential operation failed.")
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            kernel32.LocalFree(target.pbData)
