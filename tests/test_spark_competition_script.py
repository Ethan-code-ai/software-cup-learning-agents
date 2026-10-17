import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run-competition-spark.ps1"
LOCAL_SCRIPT_PATH = REPO_ROOT / "scripts" / "run-local.ps1"
DEPLOYMENT_README = REPO_ROOT / "deployment" / "README.md"


class SparkCompetitionScriptTests(unittest.TestCase):
    def test_script_configures_the_control_plane_maas_service(self) -> None:
        script = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn('"https://maas-api.cn-huabei-1.xf-yun.com/v2"', script)
        self.assertIn('[string]$Model = "xop3qwen1b7"', script)
        self.assertIn('"XFYUN_SPARK_API_KEY"', script)
        self.assertIn('$env:LLM_PROVIDER = "openai_compatible"', script)
        self.assertIn('$env:LLM_FALLBACK_MODE = "rule_based"', script)

    def test_script_uses_a_non_vite_default_frontend_port(self) -> None:
        script = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn('[int]$FrontendPort = 5174', script)
        self.assertNotIn('[int]$FrontendPort = 5173', script)

    def test_local_runner_selects_the_final_frontend_port_before_asserting_it(self) -> None:
        script = LOCAL_SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("[switch]$AutoSelectFrontendPort", script)
        selection = script.index("if ($AutoSelectFrontendPort)")
        assertion = script.index("Assert-PortFree -Port $FrontendPort")
        self.assertLess(selection, assertion)

    def test_competition_script_delegates_auto_port_selection_to_local_runner(self) -> None:
        script = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("AutoSelectFrontendPort = $true", script)
        self.assertNotIn("function Find-AvailableTcpPort", script)

    def test_script_enables_every_current_and_planned_llm_purpose(self) -> None:
        script = SCRIPT_PATH.read_text(encoding="utf-8")

        for purpose in (
            "TUTOR",
            "RESOURCE",
            "EVALUATOR",
            "PROFILE_UPDATER",
            "PROFILE_BUILDER",
            "PLANNER",
            "QUIZ",
        ):
            self.assertIn(f'$env:LLM_ENABLE_FOR_{purpose} = "true"', script)

    def test_script_sets_purpose_specific_latency_and_token_budgets(self) -> None:
        script = SCRIPT_PATH.read_text(encoding="utf-8")

        expected = {
            "PLANNER": (18, 0, 600),
            "PROFILE_UPDATER": (12, 0, 700),
            "PROFILE_BUILDER": (15, 0, 900),
            "EVALUATOR": (15, 0, 900),
            "TUTOR": (25, 0, 800),
            "QUIZ": (20, 0, 1400),
            "RESOURCE": (30, 0, 1200),
        }
        for purpose, (timeout, retries, max_tokens) in expected.items():
            self.assertIn(f'$env:LLM_{purpose}_TIMEOUT_SECONDS = "{timeout}"', script)
            self.assertIn(f'$env:LLM_{purpose}_MAX_RETRIES = "{retries}"', script)
            self.assertIn(f'$env:LLM_{purpose}_MAX_TOKENS = "{max_tokens}"', script)

    def test_script_fails_for_a_missing_secret_before_starting_services(self) -> None:
        script = SCRIPT_PATH.read_text(encoding="utf-8")

        missing_secret_guard = script.index("Missing XFYUN_SPARK_API_KEY")
        local_runner_call = script.index('"scripts/run-local.ps1"')
        self.assertLess(missing_secret_guard, local_runner_call)
        self.assertIn("UseRemoteTutorLLM = $true", script)

    def test_deployment_readme_declares_the_spark_script_as_competition_default(self) -> None:
        readme = DEPLOYMENT_README.read_text(encoding="utf-8")

        self.assertIn("run-competition-spark.ps1", readme)
        self.assertIn("XFYUN_SPARK_API_KEY", readme)
        self.assertIn("比赛默认", readme)

    def test_script_passes_maas_configuration_to_the_local_runner(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("powershell.exe")
        if powershell is None:
            self.skipTest("Windows PowerShell is not available.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            scripts_dir = temp_root / "scripts"
            scripts_dir.mkdir()
            shutil.copy2(SCRIPT_PATH, scripts_dir / SCRIPT_PATH.name)
            (scripts_dir / "run-local.ps1").write_text(
                """
param(
    [string]$BackendHost,
    [int]$BackendPort,
    [string]$FrontendHost,
    [int]$FrontendPort,
    [string]$DatabaseUrl,
    [switch]$UseRemoteTutorLLM,
    [switch]$AutoSelectFrontendPort,
    [switch]$SmokeOnly
)
[pscustomobject]@{
    Provider = $env:LLM_PROVIDER
    BaseUrl = $env:LLM_BASE_URL
    Model = $env:LLM_MODEL
    Tutor = $env:LLM_ENABLE_FOR_TUTOR
    Resource = $env:LLM_ENABLE_FOR_RESOURCE
    Evaluator = $env:LLM_ENABLE_FOR_EVALUATOR
    ProfileUpdater = $env:LLM_ENABLE_FOR_PROFILE_UPDATER
    ProfileBuilder = $env:LLM_ENABLE_FOR_PROFILE_BUILDER
    Planner = $env:LLM_ENABLE_FOR_PLANNER
    Quiz = $env:LLM_ENABLE_FOR_QUIZ
    Remote = [bool]$UseRemoteTutorLLM
    AutoSelectFrontendPort = [bool]$AutoSelectFrontendPort
    FrontendPort = $FrontendPort
} | ConvertTo-Json -Compress
""".strip(),
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["XFYUN_SPARK_API_KEY"] = "test-only-key"
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied_socket:
                occupied_socket.bind(("127.0.0.1", 0))
                occupied_socket.listen()
                occupied_port = occupied_socket.getsockname()[1]
                result = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(scripts_dir / SCRIPT_PATH.name),
                        "-FrontendPort",
                        str(occupied_port),
                        "-SmokeOnly",
                    ],
                    cwd=temp_root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"Provider":"openai_compatible"', result.stdout)
        self.assertIn('"BaseUrl":"https://maas-api.cn-huabei-1.xf-yun.com/v2"', result.stdout)
        self.assertIn('"Model":"xop3qwen1b7"', result.stdout)
        for purpose in ("Tutor", "Resource", "Evaluator", "ProfileUpdater", "ProfileBuilder", "Planner", "Quiz"):
            self.assertIn(f'"{purpose}":"true"', result.stdout)
        self.assertIn('"Remote":true', result.stdout)
        self.assertIn('"AutoSelectFrontendPort":true', result.stdout)
        output = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(output["FrontendPort"], occupied_port)


if __name__ == "__main__":
    unittest.main()
