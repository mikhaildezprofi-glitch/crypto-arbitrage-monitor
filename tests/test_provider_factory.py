import unittest

from arbitrage_monitor.providers.collection import REQUIRED_PROVIDER_KEYS
from arbitrage_monitor.providers.factory import build_default_providers


class ProviderFactoryTests(unittest.TestCase):
    def test_factory_configures_exactly_all_five_route_sources(self):
        providers = build_default_providers()
        self.assertEqual(tuple(providers), REQUIRED_PROVIDER_KEYS)
        self.assertEqual(set(providers), {
            "money_storage",
            "blackbit",
            "winance",
            "sberkassa_sell",
            "sberkassa_exchange",
        })


if __name__ == "__main__":
    unittest.main()
