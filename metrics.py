import logging
from dataclasses import dataclass


@dataclass
class Metrics:
    prefix: str = "work"

    def incr(self, name: str, value: int = 1) -> None:
        key = f"{self.prefix}.{name}"
        # Replace with StatsD/Prometheus if available.
        logging.info("metric_count name=%s value=%d", key, value)


metrics = Metrics()
