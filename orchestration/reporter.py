import logging
import time

logger = logging.getLogger(__name__)


class ResultReporter:

    def __init__(self, results) -> None:
        self.results = results

    def add_result(self, result):
        self.results.put_nowait(result)

    def monitor(self, kill_switch):
        while not kill_switch.is_set():
            if self.results.empty():
                time.sleep(0.5)
                continue
            self.on_result()

    def on_result(self):
        output = self.results.get_nowait()
        if 'error' in output:
            logger.error(output)
        else:
            logger.info(output)
