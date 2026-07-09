import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import Product, ProductType, utcnow

logger = logging.getLogger(__name__)


class ProductManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "business" / "products"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, pid: str) -> Path:
        return self._dir / f"{pid}.json"

    def _save(self, product: Product):
        path = self._path_for(product.product_id)
        path.write_text(json.dumps(product.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def create_product(self, product_type: ProductType, name: str,
                       price: float, cost: float = 0.0,
                       description: str = "") -> Product:
        product = Product(
            product_id=f"prod_{uuid.uuid4().hex[:10]}",
            product_type=product_type,
            name=name,
            price=price,
            cost=cost,
            description=description,
            metadata={"created_at": utcnow()},
        )
        self._save(product)
        return product

    def get_product(self, pid: str) -> Optional[Product]:
        path = self._path_for(pid)
        if not path.exists():
            return None
        try:
            return Product.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def list_products(self, product_type: Optional[ProductType] = None) -> list[Product]:
        results = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                product = Product.from_dict(json.loads(p.read_text(encoding="utf-8")))
                if product_type and product.product_type != product_type:
                    continue
                results.append(product)
            except Exception:
                continue
        return results

    def record_sale(self, pid: str, quantity: int = 1) -> bool:
        product = self.get_product(pid)
        if not product:
            return False
        product.sales_count += quantity
        product.total_revenue = round(product.total_revenue + product.price * quantity, 2)
        self._save(product)
        return True

    def get_total_revenue(self) -> float:
        products = self.list_products()
        return round(sum(p.total_revenue for p in products), 2)

    def get_total_sales(self) -> int:
        products = self.list_products()
        return sum(p.sales_count for p in products)

    def get_avg_margin(self) -> float:
        products = self.list_products()
        if not products:
            return 0.0
        margins = [p.margin_pct for p in products if p.price > 0]
        return round(sum(margins) / len(margins), 1) if margins else 0.0
