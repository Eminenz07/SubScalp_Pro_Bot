from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseConnector(ABC):
    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def get_historical_data(self, symbol: str, timeframe: str, limit: int): ...

    @abstractmethod
    def place_order(self, symbol: str, side: str, size: float, sl: float, tp: float) -> str: ...

    @abstractmethod
    def close_order(self, order_id: str) -> bool: ...

    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]: ...


def get_connector(broker: str, config: Dict[str, Any], kwargs: Dict[str, Any]) -> BaseConnector:
    broker = broker.lower()
    # Default to MT5 for SubScalpBot
    if broker == "mt5":
        from .mt5_connector import MT5Connector
        return MT5Connector(config, **kwargs)
    # Other connectors remain for future use but are not actively used
    if broker == "binance":
        from .binance_connector import BinanceConnector
        return BinanceConnector(config, **kwargs)
    if broker == "oanda":
        from .oanda_connector import OandaConnector
        return OandaConnector(config, **kwargs)
    # Deriv connector deprecated but kept for reference
    if broker == "deriv":
        from .deriv_connector import DerivConnector
        return DerivConnector(config, **kwargs)
    # Default fallback to MT5
    from .mt5_connector import MT5Connector
    return MT5Connector(config, **kwargs)