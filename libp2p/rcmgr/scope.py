# Base Resource Scope that will be inherited by all the other scopes. 
from typing import Dict,List, Optional, Any
from .limits import Limits
from .metrics import Metrics

class ResourceScope:
    def __init__(self,name:str, limits: Limits, metrics: Metrics, parentscopes: List['ResourceScope']) -> None:
        self.name = name
        self.limits = limits
        self.metrics = metrics
        self.parentscopes = parentscopes


    def check_memory():
        pass
    
    def resever_memory():
        pass

    def release_memory(self):
        pass

    def addstream():
        pass




class SystemScope:
    pass

class TransientScope:
    pass

class ServiceScope:
    pass

class PeerScope:
    pass

class ConnectionScope():
    pass

class StreamScope():
    def __init__(self):
        pass