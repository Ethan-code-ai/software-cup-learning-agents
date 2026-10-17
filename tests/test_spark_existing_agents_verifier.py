import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_SCRIPT = REPO_ROOT / "scripts" / "verify-spark-existing-agents.ps1"
ONLINE_TEST = REPO_ROOT / "tests" / "test_spark_existing_agents_online.py"


class SparkExistingAgentsVerifierTests(unittest.TestCase):
    def test_verifier_requires_external_secret_and_enables_existing_purposes(self) -> None:
        script = POWERSHELL_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("XFYUN_SPARK_API_KEY", script)
        self.assertIn("Missing XFYUN_SPARK_API_KEY", script)
        self.assertIn('$env:LLM_API_KEY = $apiKey', script)
        self.assertIn('[int]$MaxRetries = 1', script)
        self.assertIn('$env:LLM_MAX_RETRIES = [string]$MaxRetries', script)
        for purpose in ("TUTOR", "RESOURCE", "EVALUATOR", "PROFILE_UPDATER"):
            self.assertIn(f'$env:LLM_ENABLE_FOR_{purpose} = "true"', script)
        self.assertIn("tests.test_spark_existing_agents_online", script)

    def test_online_acceptance_reuses_existing_factories_and_defines_no_agent(self) -> None:
        source = ONLINE_TEST.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for factory_module in ("resource_factory", "tutor_factory", "evaluator_factory"):
            self.assertIn(f"app.agents.{factory_module}", source)
        self.assertIn("ProfileUpdaterService", source)
        agent_classes = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name.lower().endswith("agent")
        ]
        self.assertEqual(agent_classes, [])

    def test_online_acceptance_is_opt_in_and_does_not_print_model_content(self) -> None:
        source = ONLINE_TEST.read_text(encoding="utf-8")

        self.assertIn("RUN_SPARK_ONLINE_TESTS", source)
        self.assertNotIn("result.content, flush=True", source)
        self.assertNotIn("result.answer, flush=True", source)
        self.assertNotIn("LLM_API_KEY", source)


if __name__ == "__main__":
    unittest.main()
