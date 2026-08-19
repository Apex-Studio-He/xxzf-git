#!/usr/bin/env python3
"""Fail-closed helpers for private runtime storage.

The service stores credentials and notification content.  A successful
``chmod`` call is not sufficient on filesystems that do not enforce POSIX
ownership or modes, so every helper verifies the final object with ``lstat``
and an already-open, no-follow file descriptor.
"""

import os
import stat
from pathlib import Path


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


class StorageSecurityError(RuntimeError):
    """Raised when runtime storage cannot be made private."""


def _current_uid():
    try:
        return os.geteuid()
    except AttributeError as exc:  # pragma: no cover - POSIX service only
        raise StorageSecurityError("private storage requires POSIX ownership") from exc


def _lstat(path, *, required):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        if required:
            raise StorageSecurityError(f"required private path is missing: {path}")
        return None
    except OSError as exc:
        raise StorageSecurityError(f"cannot inspect private path: {path}") from exc


def _verify_identity(path, path_stat, descriptor_stat, expected_mode, kind):
    if (path_stat.st_dev, path_stat.st_ino) != (
        descriptor_stat.st_dev,
        descriptor_stat.st_ino,
    ):
        raise StorageSecurityError(f"private {kind} changed during verification: {path}")
    if descriptor_stat.st_uid != _current_uid() or path_stat.st_uid != _current_uid():
        raise StorageSecurityError(f"private {kind} is not owned by the service user: {path}")
    descriptor_mode = stat.S_IMODE(descriptor_stat.st_mode)
    path_mode = stat.S_IMODE(path_stat.st_mode)
    if descriptor_mode != expected_mode or path_mode != expected_mode:
        raise StorageSecurityError(
            f"filesystem cannot enforce mode {expected_mode:04o} for private {kind}: {path}"
        )


def ensure_private_directory(path, *, create=True):
    """Create (when requested) and verify a real, owned, mode-0700 directory."""

    path = Path(path)
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
        except OSError as exc:
            raise StorageSecurityError(f"cannot create private directory: {path}") from exc

    before = _lstat(path, required=True)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise StorageSecurityError(f"private directory must not be a symbolic link: {path}")
    if before.st_uid != _current_uid():
        raise StorageSecurityError(f"private directory is not owned by the service user: {path}")

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StorageSecurityError(f"cannot open private directory safely: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise StorageSecurityError(f"private directory is not a directory: {path}")
        if opened.st_uid != _current_uid():
            raise StorageSecurityError(
                f"private directory is not owned by the service user: {path}"
            )
        if stat.S_IMODE(opened.st_mode) != PRIVATE_DIRECTORY_MODE:
            try:
                os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
            except OSError as exc:
                raise StorageSecurityError(f"cannot protect private directory: {path}") from exc
        final_descriptor = os.fstat(descriptor)
        final_path = _lstat(path, required=True)
        if stat.S_ISLNK(final_path.st_mode) or not stat.S_ISDIR(final_path.st_mode):
            raise StorageSecurityError(f"private directory changed type: {path}")
        _verify_identity(
            path,
            final_path,
            final_descriptor,
            PRIVATE_DIRECTORY_MODE,
            "directory",
        )
    finally:
        os.close(descriptor)
    return path


def ensure_private_file(path, *, required=True):
    """Verify a real, owned, regular file and enforce mode 0600.

    Returns ``False`` only when ``required`` is false and the path does not
    exist.  A dangling symlink is still rejected because ``lstat`` sees it.
    """

    path = Path(path)
    before = _lstat(path, required=required)
    if before is None:
        return False
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise StorageSecurityError(f"private file must be a regular non-link file: {path}")
    if before.st_uid != _current_uid():
        raise StorageSecurityError(f"private file is not owned by the service user: {path}")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StorageSecurityError(f"cannot open private file safely: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise StorageSecurityError(f"private file is not a regular file: {path}")
        if opened.st_uid != _current_uid():
            raise StorageSecurityError(f"private file is not owned by the service user: {path}")
        if stat.S_IMODE(opened.st_mode) != PRIVATE_FILE_MODE:
            try:
                os.fchmod(descriptor, PRIVATE_FILE_MODE)
            except OSError as exc:
                raise StorageSecurityError(f"cannot protect private file: {path}") from exc
        final_descriptor = os.fstat(descriptor)
        final_path = _lstat(path, required=True)
        if stat.S_ISLNK(final_path.st_mode) or not stat.S_ISREG(final_path.st_mode):
            raise StorageSecurityError(f"private file changed type: {path}")
        _verify_identity(
            path,
            final_path,
            final_descriptor,
            PRIVATE_FILE_MODE,
            "file",
        )
    finally:
        os.close(descriptor)
    return True


def secure_private_file_descriptor(descriptor, path):
    """Apply and verify private-file policy on an already-open descriptor."""

    path = Path(path)
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        raise StorageSecurityError(f"private file descriptor is not regular: {path}")
    if opened.st_uid != _current_uid():
        raise StorageSecurityError(f"private file is not owned by the service user: {path}")
    if stat.S_IMODE(opened.st_mode) != PRIVATE_FILE_MODE:
        try:
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
        except OSError as exc:
            raise StorageSecurityError(f"cannot protect private file: {path}") from exc
    final_descriptor = os.fstat(descriptor)
    if stat.S_IMODE(final_descriptor.st_mode) != PRIVATE_FILE_MODE:
        raise StorageSecurityError(
            f"filesystem cannot enforce mode {PRIVATE_FILE_MODE:04o} for private file: {path}"
        )


def _write_all(descriptor, data):
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:  # pragma: no cover - defensive POSIX guard
            raise OSError("short write to private file")
        view = view[written:]


def atomic_write_private(path, data):
    """Atomically replace ``path`` with bytes in a verified mode-0600 file."""

    path = Path(path)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("private file data must be bytes-like")
    ensure_private_directory(path.parent)
    ensure_private_file(path, required=False)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = None
    try:
        descriptor = os.open(temporary, flags, PRIVATE_FILE_MODE)
        secure_private_file_descriptor(descriptor, temporary)
        _write_all(descriptor, bytes(data))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        ensure_private_file(temporary)
        os.replace(temporary, path)
        ensure_private_file(path)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return path


def append_private(path, data):
    """Append bytes without following links, verifying protection before use."""

    path = Path(path)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("private file data must be bytes-like")
    ensure_private_directory(path.parent)
    ensure_private_file(path, required=False)
    flags = (
        os.O_WRONLY
        | os.O_APPEND
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, PRIVATE_FILE_MODE)
    except OSError as exc:
        raise StorageSecurityError(f"cannot open private append file safely: {path}") from exc
    try:
        secure_private_file_descriptor(descriptor, path)
        _write_all(descriptor, bytes(data))
    finally:
        os.close(descriptor)
    ensure_private_file(path)
    return path
