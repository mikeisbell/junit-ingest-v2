# Feature map fixture for graph ingestion tests.
# Maps test case names in tests/fixtures/test.xml to feature names
# that match the seed_data fixture below.
FIXTURE_FEATURE_MAP = {
    "test_user_login": "user_profile",
    "test_add_to_cart": "shopping_cart",
    "test_checkout_flow": "checkout_flow",
    "test_payment_gateway": "payment_gateway",
    "test_order_processing": "order_processing",
    "test_cart_concurrent_updates": "shopping_cart",
    "test_update_cart_quantity": "shopping_cart",
    "test_legacy_payment_flow": "payment_gateway",
}
