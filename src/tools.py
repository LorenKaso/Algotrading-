from __future__ import annotations


class FairValueTool:
    name = "fair_value_score"
    description = "Compute undervaluation score given price and fair value"

    def run(self, price: float, fair: float) -> float:
        if price <= 0:
            return float("-inf")
        return (fair - price) / price
