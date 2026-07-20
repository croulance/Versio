from abc import ABC, abstractmethod


class MergerInterface(ABC):
    """
    Base contract for all format mergers.
    Single responsibility: merge a job's per-chunk output files into one final file.
    """

    @abstractmethod
    def merge(self, keys: list[str], metadata: dict) -> bytes:
        """Read and concatenate the given storage chunk keys into one output file."""
