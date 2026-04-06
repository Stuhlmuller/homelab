from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class AnsibleTemplateTests(unittest.TestCase):
    def test_nomad_template_configures_server_join(self) -> None:
        content = (
            ROOT / "ansible" / "roles" / "nomad" / "templates" / "nomad.hcl.j2"
        ).read_text()
        self.assertIn("server_join", content)
        self.assertIn("retry_join", content)
        self.assertIn('node_class        = "{{ nomad_node_class }}"', content)
        self.assertIn('cni_path          = "{{ nomad_cni_path }}"', content)

    def test_consul_template_keeps_retry_join(self) -> None:
        content = (
            ROOT / "ansible" / "roles" / "consul" / "templates" / "consul.hcl.j2"
        ).read_text()
        self.assertIn("retry_join", content)
