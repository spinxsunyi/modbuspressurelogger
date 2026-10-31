"""OS-backed lock: released automatically even after a crash."""
import os


class InstanceLock:
    def __init__(self, path):
        # The lock primitive locks a byte range; the file does not need contents.
        # Avoid initializing a byte here: concurrent Windows opens can deny the
        # second handle's write before it reaches the lock operation.
        self.file = open(path, "a+b")
        try:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError(
                "Another PMS Logger is already using this data folder."
            ) from exc

    def close(self):
        self.file.close()
