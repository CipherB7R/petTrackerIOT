from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseService(ABC):
    """Base class for all services in the pool"""

    def __init__(self):
        self.name = self.__class__.__name__

    @abstractmethod
    def execute(self, data: Dict, dr_type: str = None, attribute: str = None) -> Any:
        """
        Execute the service on provided data
        Args:
            data: Input data in any format. Must contain at least the "digital_replicas" key,
                  which in turn must contain all the data pertaining to the caller DT's DRs.
            dr_type: Type of DR to process
            attribute: Specific attribute to analyze
        Returns:
            Processed data in any format
        """
        pass
