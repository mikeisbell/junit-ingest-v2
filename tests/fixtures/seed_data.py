# Minimal graph seed data for unit and integration tests.
# Uses a small realistic dataset that exercises all node types and relationships.
FIXTURE_SEED_DATA = {
    "modules": [
        {"name": "payment_processor", "path": "app/payments/processor.py"},
        {"name": "cart_service", "path": "app/cart/service.py"},
        {"name": "order_service", "path": "app/orders/service.py"},
        {"name": "user_auth", "path": "app/auth/user.py"},
    ],
    "features": [
        {"name": "checkout_flow", "description": "End-to-end purchase checkout"},
        {"name": "user_profile", "description": "User account and profile management"},
        {"name": "shopping_cart", "description": "Cart add, remove, and update"},
        {"name": "order_processing", "description": "Order creation and fulfillment"},
        {"name": "payment_gateway", "description": "Payment processing and validation"},
    ],
    "feature_module_edges": [
        {"feature": "checkout_flow", "module": "payment_processor"},
        {"feature": "checkout_flow", "module": "cart_service"},
        {"feature": "shopping_cart", "module": "cart_service"},
        {"feature": "order_processing", "module": "order_service"},
        {"feature": "payment_gateway", "module": "payment_processor"},
        {"feature": "user_profile", "module": "user_auth"},
    ],
    "bugs": [
        {"id": "BUG-001", "title": "Checkout fails when cart has more than 10 items",
         "severity": "high", "escaped": True},
        {"id": "BUG-002", "title": "User profile email not updated after change",
         "severity": "medium", "escaped": True},
    ],
    "bug_feature_edges": [
        {"bug_id": "BUG-001", "feature": "checkout_flow"},
        {"bug_id": "BUG-001", "feature": "shopping_cart"},
        {"bug_id": "BUG-002", "feature": "user_profile"},
    ],
}
