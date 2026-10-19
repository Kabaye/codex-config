import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "manage.py"
SPEC = importlib.util.spec_from_file_location("codex_config_manage_routing", SCRIPT)
assert SPEC and SPEC.loader
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)


class RoutingMarkerTests(unittest.TestCase):
    def test_canonical_routing_block_is_preserved_during_adoption(self) -> None:
        routing = """<!-- codex-profiles:begin -->
canonical routing
<!-- codex-profiles:end -->"""

        result = manage.build_global_text(
            f"base rules\n\n{routing}\n",
            "managed base",
            "base rules",
            "<!-- codex-config:begin -->",
            "<!-- codex-config:end -->",
            False,
        )

        self.assertEqual(f"managed base\n\n{routing}\n", result)


if __name__ == "__main__":
    unittest.main()
