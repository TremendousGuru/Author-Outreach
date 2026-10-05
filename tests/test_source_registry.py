import unittest

from pipeline.sources import REGISTRY, get_adapter


class SourceRegistryTests(unittest.TestCase):
    def test_deferred_sources_are_enabled_for_browser_crawling(self):
        for key in ("smashwords", "allauthor", "reedsy", "wattpad"):
            with self.subTest(key=key):
                self.assertTrue(REGISTRY[key]["built"], f"{key} should be enabled")
                self.assertIsNotNone(get_adapter(key))


if __name__ == "__main__":
    unittest.main()
