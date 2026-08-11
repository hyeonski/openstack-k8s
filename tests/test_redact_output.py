import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "redact-output.py"
SPEC = importlib.util.spec_from_file_location("redact_output", MODULE_PATH)
assert SPEC and SPEC.loader
redact_output = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(redact_output)


class RedactOutputTests(unittest.TestCase):
    def test_redacts_supported_secret_shapes(self):
        source = "\n".join(
            (
                "token abc123.0123456789abcdef",
                "kubeadm --certificate-key " + "a" * 64,
                "application_credential_secret: app-secret-value",
                "healthcheck_curl -u openstack:service-password http://127.0.0.1",
                "endpoint https://user:url-password@example.invalid/path",
            )
        )

        result = redact_output.redact(source)

        self.assertNotIn("abc123.0123456789abcdef", result)
        self.assertNotIn("a" * 64, result)
        self.assertNotIn("app-secret-value", result)
        self.assertNotIn("service-password", result)
        self.assertNotIn("url-password", result)
        self.assertIn("<redacted-bootstrap-token>", result)
        self.assertIn("openstack:<redacted-password>", result)

    def test_preserves_non_secret_status_output(self):
        source = "controller | SUCCESS => changed=false\nHTTP status: 200\n"
        self.assertEqual(source, redact_output.redact(source))


if __name__ == "__main__":
    unittest.main()
