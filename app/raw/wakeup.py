"""Wake the local worker on committed edits; keep polling as recovery fallback."""
import logging
import time
from .. import planning

log=logging.getLogger(__name__)


class LocalChanges:
    def __init__(self):
        self.connection=None

    def close(self):
        if self.connection is not None:self.connection.close()
        self.connection=None

    def wait(self,timeout=2):
        try:
            if self.connection is None or self.connection.closed:
                self.connection=planning.connect()
                self.connection.autocommit=True
                self.connection.execute('LISTEN planning_raw_changed')
            return bool(list(self.connection.notifies(timeout=timeout,stop_after=1)))
        except Exception:
            log.exception('Local change notifications unavailable; polling retained')
            self.close()
            time.sleep(min(timeout,.5))
            return False
