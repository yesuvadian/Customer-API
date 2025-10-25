from sqlalchemy.orm import Session
from sqlalchemy import func
from models import Product, ProductCategory, ProductSubCategory, User, Plan, UserRole, Role

class DashboardService:

    @classmethod
    def total_products(cls, db: Session) -> int:
        return db.query(func.count(Product.id)).scalar()

    @classmethod
    def total_users(cls, db: Session) -> int:
        return db.query(func.count(User.id)).scalar()

    @classmethod
    def total_users_with_plan(cls, db: Session) -> int:
        return db.query(func.count(User.id)).filter(User.plan_id.isnot(None)).scalar()

    @classmethod
    def users_by_plan(cls, db: Session) -> dict:
        result = db.query(
            Plan.planname,
            func.count(User.id).label("user_count")
        ).join(User, User.plan_id == Plan.id) \
         .group_by(Plan.planname) \
         .all()
        return {row.planname: row.user_count for row in result}

    @classmethod
    def total_vendors(cls, db: Session) -> int:
        vendor_role = db.query(Role).filter_by(name="Vendor").first()
        if not vendor_role:
            return 0
        return db.query(func.count(UserRole.user_id)) \
                 .filter(UserRole.role_id == vendor_role.id) \
                 .scalar()

    @classmethod
    def vendors_by_plan(cls, db: Session) -> dict:
        vendor_role = db.query(Role).filter_by(name="Vendor").first()
        if not vendor_role:
            return {}
        result = db.query(
            Plan.planname,
            func.count(User.id).label("vendor_count")
        ).join(User, User.plan_id == Plan.id) \
         .join(UserRole, UserRole.user_id == User.id) \
         .filter(UserRole.role_id == vendor_role.id) \
         .group_by(Plan.planname) \
         .all()
        return {row.planname: row.vendor_count for row in result}

    @classmethod
    def products_by_category(cls, db: Session) -> dict:
        result = db.query(
            ProductCategory.name,
            func.count(Product.id).label("product_count")
        ).join(Product, Product.category_id == ProductCategory.id) \
         .group_by(ProductCategory.name) \
         .all()
        return {row.name: row.product_count for row in result}

    @classmethod
    def products_by_subcategory(cls, db: Session) -> dict:
        result = db.query(
            ProductSubCategory.name,
            func.count(Product.id).label("product_count")
        ).join(Product, Product.subcategory_id == ProductSubCategory.id) \
         .group_by(ProductSubCategory.name) \
         .all()
        return {row.name: row.product_count for row in result}
