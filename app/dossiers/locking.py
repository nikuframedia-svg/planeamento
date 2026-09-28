"""Locks de ficheiro para o servidor Linux e para a instalação Windows."""
import errno
import os

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def acquire(file):
    if os.name != "nt":
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    file.seek(0, os.SEEK_END)
    if file.tell() == 0:
        file.write("\0")
        file.flush()
    file.seek(0)
    try:
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            raise BlockingIOError() from None
        raise


def release(file):
    if os.name != "nt":
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)
    else:
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
