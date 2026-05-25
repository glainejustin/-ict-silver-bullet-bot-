import logging

class SignalAggregator:
    """
    Aggregates signals from multiple strategies and returns the first valid trigger.
    """
    def __init__(self, strategies, min_confidence_threshold: float = 1.0):
        self.strategies = strategies
        self.threshold = min_confidence_threshold

    def aggregate_signals(self, ltf, htf, struct, current_time):
        for strategy in self.strategies:
            if not strategy.enabled:
                continue
            res = strategy.generate_signal(ltf, htf, struct, current_time)
            if res['signal'] != 'HOLD' and res.get('confidence', 1.0) >= self.threshold:
                return res
        return {'signal': 'HOLD'}

    def enable_strategy(self, name: str):
        for strategy in self.strategies:
            if strategy.name == name:
                strategy.enabled = True
                return True
        return False

    def disable_strategy(self, name: str):
        for strategy in self.strategies:
            if strategy.name == name:
                strategy.enabled = False
                return True
        return False
