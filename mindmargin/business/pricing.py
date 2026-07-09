import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PricingRule:
    rule_id: str = ""
    product_type: str = ""
    base_price: float = 0.0
    min_price: float = 0.0
    max_price: float = 0.0
    discount_pct: float = 0.0
    bundle_discount_pct: float = 0.0
    volume_threshold: int = 0
    volume_discount_pct: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class PricingEngine:
    def __init__(self):
        self._rules: list[PricingRule] = []
        self._load_defaults()

    def _load_defaults(self):
        self._rules = [
            PricingRule(rule_id="pr_course", product_type="course",
                        base_price=99.0, min_price=49.0, max_price=299.0,
                        discount_pct=0.0, bundle_discount_pct=15.0),
            PricingRule(rule_id="pr_ebook", product_type="ebook",
                        base_price=19.99, min_price=9.99, max_price=49.99,
                        discount_pct=0.0, bundle_discount_pct=10.0),
            PricingRule(rule_id="pr_template", product_type="template",
                        base_price=29.99, min_price=14.99, max_price=79.99,
                        discount_pct=0.0, volume_threshold=3, volume_discount_pct=20.0),
            PricingRule(rule_id="pr_tool", product_type="tool",
                        base_price=49.0, min_price=29.0, max_price=149.0,
                        discount_pct=0.0, bundle_discount_pct=10.0),
            PricingRule(rule_id="pr_community", product_type="community",
                        base_price=9.99, min_price=4.99, max_price=29.99,
                        discount_pct=0.0, volume_discount_pct=0.0),
            PricingRule(rule_id="pr_consulting", product_type="consulting",
                        base_price=200.0, min_price=100.0, max_price=500.0,
                        discount_pct=0.0, bundle_discount_pct=0.0),
        ]

    def get_price(self, product_type: str, quantity: int = 1,
                  custom_discount: float = 0.0) -> dict:
        rule = next((r for r in self._rules if r.product_type == product_type), None)
        if not rule:
            return {"base_price": 0.0, "final_price": 0.0, "discount_applied": 0.0}

        base = rule.base_price
        discount = custom_discount or rule.discount_pct

        if quantity > 1 and rule.volume_threshold > 0 and quantity >= rule.volume_threshold:
            discount = max(discount, rule.volume_discount_pct)

        final = base * (1 - discount / 100)
        final = max(final, rule.min_price)
        final = min(final, rule.max_price)

        return {
            "base_price": base,
            "final_price": round(final, 2),
            "discount_applied": discount,
            "quantity": quantity,
            "total": round(final * quantity, 2),
        }

    def get_bundle_price(self, product_types: list[str]) -> dict:
        prices = [self.get_price(pt) for pt in product_types]
        total_base = sum(p["base_price"] for p in prices)
        avg_discount = max((r.bundle_discount_pct for r in self._rules
                           if r.product_type in product_types), default=0.0)
        total_final = total_base * (1 - avg_discount / 100)
        return {
            "products": product_types,
            "total_base": round(total_base, 2),
            "bundle_discount_pct": avg_discount,
            "total_final": round(total_final, 2),
            "savings": round(total_base - total_final, 2),
        }

    def suggest_price(self, product_type: str, competitor_price: float = 0.0,
                      target_margin: float = 0.6) -> dict:
        rule = next((r for r in self._rules if r.product_type == product_type), None)
        if not rule:
            return {"suggested_price": 0.0, "rationale": "Unknown product type"}

        base = rule.base_price
        if competitor_price > 0:
            suggested = competitor_price * 0.9
            suggested = max(suggested, rule.min_price)
            suggested = min(suggested, rule.max_price)
            return {
                "suggested_price": round(suggested, 2),
                "rationale": f"10% below competitor ${competitor_price:.2f}",
                "floor": rule.min_price,
                "ceiling": rule.max_price,
            }

        suggested = base * target_margin
        suggested = max(suggested, rule.min_price)
        suggested = min(suggested, rule.max_price)
        return {
            "suggested_price": round(suggested, 2),
            "rationale": f"Based on {target_margin:.0%} target margin",
            "floor": rule.min_price,
            "ceiling": rule.max_price,
        }

    def list_rules(self) -> list[PricingRule]:
        return list(self._rules)
