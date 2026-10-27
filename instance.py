"""OS-backed lock: released automatically even after a crash."""
import os
class InstanceLock:
    def __init__(self,path):
        self.file=open(path,'a+b');self.file.seek(0)
        if not self.file.read(1):self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('Another PMS Logger is already using this data folder.')
    def close(self):self.file.close()
