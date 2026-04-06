from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "ansible" / "inventories" / "production" / "hosts.yml"
GROUP_VARS = ROOT / "ansible" / "inventories" / "production" / "group_vars" / "all.yml"


class InventoryTests(unittest.TestCase):
    def test_inventory_declares_all_servers(self) -> None:
        content = INVENTORY.read_text()
        for name in ["acer", "zimaboard-0", "zimaboard-1", "zimaboard-2"]:
            self.assertIn(name, content)

    def test_inventory_declares_expected_ips(self) -> None:
        content = INVENTORY.read_text()
        for ip in ["10.1.0.199", "10.1.0.200", "10.1.0.201", "10.1.0.202"]:
            self.assertIn(ip, content)
        for tailscale_ip in ["100.119.126.81", "100.94.104.7", "100.102.247.126", "100.78.60.65"]:
            self.assertIn(tailscale_ip, content)

    def test_group_vars_match_bootstrap_expectation(self) -> None:
        content = GROUP_VARS.read_text()
        self.assertIn("homelab_bootstrap_expect: 3", content)
        self.assertIn('consul_bootstrap_expect: "{{ homelab_bootstrap_expect }}"', content)
        self.assertIn('nomad_bootstrap_expect: "{{ homelab_bootstrap_expect }}"', content)
        self.assertIn("- 10.1.0.199", content)
        self.assertIn("- 10.1.0.201", content)

    def test_inventory_declares_an_ingress_node(self) -> None:
        content = INVENTORY.read_text()
        self.assertIn("nomad_node_class: ingress", content)
        self.assertIn("nomad_node_name: nomad-primary", content)
        self.assertIn("tailscale_funnel_mounts:", content)
        self.assertIn("path: /", content)
        self.assertIn("target: http://127.0.0.1:18080", content)
        self.assertIn("tailscale_advertise_routes:", content)
        self.assertIn("10.1.0.0/24", content)

    def test_group_vars_do_not_accept_tailscale_routes_by_default(self) -> None:
        content = GROUP_VARS.read_text()
        self.assertIn("tailscale_accept_routes: false", content)
        self.assertNotIn("  - --accept-routes", content)
        self.assertNotIn("--advertise-tags=tag:homelab", content)
