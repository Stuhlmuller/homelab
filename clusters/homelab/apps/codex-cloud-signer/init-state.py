"""Protect the dedicated local directory before the nonroot daemon starts."""
import os
from pathlib import Path
import stat

path = Path('/state')
assert stat.S_ISDIR(path.lstat().st_mode), 'state must be a real directory'
os.chown(path, 65532, 65532)
os.chmod(path, 0o700)
assert path.stat().st_uid == 65532 and stat.S_IMODE(path.stat().st_mode) == 0o700
