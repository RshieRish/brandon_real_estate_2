import importlib.util
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Optional
import unittest
from unittest.mock import patch


UPSTREAM_COMMIT = "7224d7c1a4dcffe9304f49bc843f55716f5561b4"
HERMES_TAG = "v2026.5.29.2"
HERMES_COMMIT = "77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5"
HERMES_HASHES = {
    "agent/credential_pool.py": "c4b78ca292ebb7072d56c17f3c7b7307cac3a33532cb1bb55f640373c55382e5",
    "agent/agent_init.py": "2fdea13cbce18a3d8eb0d0fae432d6ebb64efb221721ca9a179bcfe76956dfd3",
    "gateway/run.py": "9e3a780cfa36ac8931ad42481a56d4c55d9643efc1f7ec9b595fa886967d0a3f",
    "agent/conversation_loop.py": "b096615e1d21e935c0f8b950cca2f5868f8eecdee6e09244a6e60982817b0b75",
    "agent/tool_executor.py": "4c9f59aa5063520a2d20baec1acbb9640b92a64c7e6dedc92817670158b0ad01",
}
EXISTING_TOOLS = [
    "status_read",
    "actions_list",
    "leads_recent",
    "bookings_recent",
    "workspace_status",
    "drive_search",
    "drive_file_read",
    "gmail_search",
    "gmail_thread_read",
    "gmail_draft_create",
    "gmail_send",
    "docs_create",
    "sheets_append",
    "calendar_events_read",
    "calendar_event_create",
    "contacts_search",
]
CRM_TOOLS = [
    "crm_tasks_read",
    "crm_task_suggestions_read",
    "crm_task_clarifications_answer",
    "crm_task_drafts_create",
    "crm_task_suggestions_approval_link",
    "crm_task_suggestions_dismiss_proposal",
]
NEW_READ_TOOLS = [
    "context_history_search",
    "command_contacts_search",
    "command_contact_audience_preview",
]

TEMPLATE_DOCKERFILE = """\
FROM python:3.12-slim
ARG HERMES_REF=v2026.5.29.2
RUN git clone --depth 1 --branch ${HERMES_REF} https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent && \\
    cd /opt/hermes-agent && \\
    uv pip install --system --no-cache -e \".[all]\"
COPY start.sh /app/start.sh
"""


def _load_overlay_module(name: str):
    root = Path(__file__).resolve().parents[2] / "hermes" / "overlay"
    module_path = root / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HermesOverlayTests(unittest.TestCase):
    def _apply_context(self, overlay, source, *, status=()):
        baseline = {
            "Dockerfile": (source / "Dockerfile").read_text(),
            "start.sh": (source / "start.sh").read_text(),
        }
        return (
            patch.object(overlay, "_checkout_commit", return_value=UPSTREAM_COMMIT),
            patch.object(
                overlay,
                "_baseline_file",
                side_effect=lambda _source, name: baseline[name],
                create=True,
            ),
            patch.object(
                overlay,
                "_working_tree_status",
                return_value=set(status),
                create=True,
            ),
        )

    def test_manifest_pins_the_approved_upstream_commit_and_exact_tool_registry(self):
        manifest_path = (
            Path(__file__).resolve().parents[2] / "hermes" / "overlay" / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text())

        self.assertEqual(manifest["upstream"]["commit"], UPSTREAM_COMMIT)
        self.assertEqual(manifest["hermes_upstream"]["tag"], HERMES_TAG)
        self.assertEqual(manifest["hermes_upstream"]["commit"], HERMES_COMMIT)
        self.assertEqual(
            manifest["hermes_upstream"]["repository"],
            "https://github.com/NousResearch/hermes-agent.git",
        )
        self.assertEqual(manifest["hermes_upstream"]["source_sha256"], HERMES_HASHES)
        self.assertEqual(manifest["tools"]["include"][:16], EXISTING_TOOLS)
        self.assertEqual(manifest["tools"]["include"][16:22], CRM_TOOLS)
        self.assertEqual(manifest["tools"]["include"][22:], NEW_READ_TOOLS)
        self.assertEqual(len(manifest["tools"]["include"]), 25)
        self.assertEqual(len(set(manifest["tools"]["include"])), 25)

    def test_apply_overlay_is_idempotent_for_the_pinned_checkout_contract(self):
        overlay = _load_overlay_module("apply_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            (source / "Dockerfile").write_text(TEMPLATE_DOCKERFILE)
            (source / "start.sh").write_text(
                "#!/bin/bash\nexec python /app/server.py\n"
            )

            initial_context = self._apply_context(overlay, source)
            with initial_context[0], initial_context[1], initial_context[2]:
                overlay.apply_overlay(source)
                first_dockerfile = (source / "Dockerfile").read_text()
                first_start = (source / "start.sh").read_text()

            exact_overlay_status = {
                "Dockerfile",
                "start.sh",
                "atlas_backend_mcp.py",
                "atlas_backend_bootstrap.py",
                "atlas_backend_overlay_manifest.json",
                "install_sydney_overlay.py",
                "sydney_spool.py",
                "sydney_memory_provider.py",
                "sydney_retry.py",
                "sydney_backfill.py",
                "sydney_runtime.py",
                "sydney_gateway.py",
            }
            second_context = self._apply_context(
                overlay,
                source,
                status=exact_overlay_status,
            )
            with second_context[0], second_context[1], second_context[2]:
                overlay.apply_overlay(source)

            self.assertEqual((source / "Dockerfile").read_text(), first_dockerfile)
            self.assertEqual((source / "start.sh").read_text(), first_start)
            self.assertIn(
                "COPY atlas_backend_mcp.py /app/atlas_backend_mcp.py", first_dockerfile
            )
            self.assertIn(
                "COPY atlas_backend_bootstrap.py /app/atlas_backend_bootstrap.py",
                first_dockerfile,
            )
            self.assertIn(
                "COPY atlas_backend_overlay_manifest.json /app/atlas_backend_overlay_manifest.json",
                first_dockerfile,
            )
            self.assertIn("python /app/atlas_backend_bootstrap.py", first_start)
            self.assertLess(
                first_start.index("python /app/atlas_backend_bootstrap.py"),
                first_start.index("exec python /app/server.py"),
            )
            self.assertTrue((source / "atlas_backend_mcp.py").is_file())
            self.assertTrue((source / "atlas_backend_bootstrap.py").is_file())
            self.assertTrue((source / "atlas_backend_overlay_manifest.json").is_file())
            for name in (
                "install_sydney_overlay.py",
                "sydney_spool.py",
                "sydney_memory_provider.py",
                "sydney_retry.py",
                "sydney_backfill.py",
                "sydney_runtime.py",
                "sydney_gateway.py",
            ):
                self.assertTrue((source / name).is_file(), name)
            self.assertIn(
                "python /app/install_sydney_overlay.py --source /opt/hermes-agent",
                first_dockerfile,
            )
            self.assertLess(
                first_dockerfile.index("python /app/install_sydney_overlay.py"),
                first_dockerfile.index('uv pip install --system --no-cache -e'),
            )

    def test_apply_overlay_refuses_unrelated_dirty_source_without_mutation(self):
        overlay = _load_overlay_module("apply_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            (source / "Dockerfile").write_text(TEMPLATE_DOCKERFILE)
            (source / "start.sh").write_text(
                "#!/bin/bash\nexec python /app/server.py\n"
            )
            unrelated = source / "README.md"
            unrelated.write_text("do not touch\n")
            before = {path.name: path.read_bytes() for path in source.iterdir()}
            context = self._apply_context(overlay, source, status={"README.md"})
            with context[0], context[1], context[2], self.assertRaises(ValueError):
                overlay.apply_overlay(source)
            self.assertEqual(
                {path.name: path.read_bytes() for path in source.iterdir()},
                before,
            )

    def test_apply_overlay_validates_all_anchors_before_any_mutation(self):
        overlay = _load_overlay_module("apply_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            (source / "Dockerfile").write_text(TEMPLATE_DOCKERFILE)
            (source / "start.sh").write_text("#!/bin/bash\npython server.py\n")
            before = {path.name: path.read_bytes() for path in source.iterdir()}
            context = self._apply_context(overlay, source)
            with context[0], context[1], context[2], self.assertRaises(ValueError):
                overlay.apply_overlay(source)
            self.assertEqual(
                {path.name: path.read_bytes() for path in source.iterdir()},
                before,
            )

    def test_apply_overlay_rolls_back_injected_replace_failure(self):
        overlay = _load_overlay_module("apply_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            (source / "Dockerfile").write_text(TEMPLATE_DOCKERFILE)
            (source / "start.sh").write_text(
                "#!/bin/bash\nexec python /app/server.py\n"
            )
            before = {path.name: path.read_bytes() for path in source.iterdir()}
            replace = os.replace
            calls = 0

            def fail_third_replace(source_path, target_path):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("injected replace failure")
                replace(source_path, target_path)

            context = self._apply_context(overlay, source)
            with (
                context[0],
                context[1],
                context[2],
                patch("os.replace", side_effect=fail_third_replace),
                self.assertRaises(OSError),
            ):
                overlay.apply_overlay(source)
            self.assertEqual(
                {path.name: path.read_bytes() for path in source.iterdir()},
                before,
            )
            self.assertEqual(list(source.glob(".atlas-overlay-*")), [])

    def test_bootstrap_preserves_existing_config_and_writes_exact_25_tool_contract(
        self,
    ):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text("gateway:\n  provider: gemini\n")
            bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
            )
            config = bootstrap.load_yaml(config_path)

        self.assertEqual(config["gateway"], {"provider": "gemini"})
        atlas = config["mcp_servers"]["atlas_backend"]
        self.assertEqual(atlas["command"], "python")
        self.assertEqual(atlas["args"], ["/app/atlas_backend_mcp.py"])
        self.assertEqual(
            atlas["tools"]["include"],
            EXISTING_TOOLS + CRM_TOOLS + NEW_READ_TOOLS,
        )
        self.assertFalse(atlas["tools"]["resources"])
        self.assertFalse(atlas["tools"]["prompts"])
        self.assertEqual(config["session_reset"], {"mode": "none"})
        self.assertEqual(config["agent"]["max_turns"], 16)
        self.assertEqual(
            config["compression"],
            {
                "enabled": True,
                "threshold": 0.08,
                "target": 0.02,
                "protect_last": 20,
                "abort_on_summary_failure": True,
            },
        )
        self.assertEqual(
            config["tool_guardrails"],
            {
                "enabled": True,
                "exact_failure_limit": 5,
                "same_tool_failure_limit": 8,
                "no_progress_limit": 5,
            },
        )
        self.assertNotIn("provider", config.get("memory", {}))

    def test_bootstrap_enables_sydney_only_for_master_flag_and_allowlisted_identity(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            changed = bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
                durable_context_enabled=True,
                external_user_id="brandon-id",
                allowed_external_user_ids={"brandon-id"},
            )
            config = bootstrap.load_yaml(config_path)
        self.assertTrue(changed)
        self.assertEqual(config["memory"]["provider"], "sydney")

    def test_exact_hermes_installer_applies_twice_without_byte_drift(self):
        checkout = os.environ.get("HERMES_EXACT_CHECKOUT")
        if not checkout:
            self.skipTest("HERMES_EXACT_CHECKOUT is not configured")
        installer = _load_overlay_module("install_sydney_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "hermes"
            subprocess.run(
                ["git", "clone", "--quiet", "--no-checkout", checkout, str(source)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "checkout", "--quiet", "--detach", HERMES_COMMIT],
                check=True,
            )
            installer.install(source)
            first = {
                str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in source.rglob("*.py")
                if ".git" not in path.parts
            }
            installer.install(source)
            second = {
                str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in source.rglob("*.py")
                if ".git" not in path.parts
            }
            self.assertEqual(second, first)
            self.assertIn("plugins/memory/sydney/__init__.py", first)
            self.assertIn("agent/sydney_runtime.py", first)
            self.assertIn("gateway/sydney_gateway.py", first)

            credential_pool = (source / "agent/credential_pool.py").read_text()
            agent_init = (source / "agent/agent_init.py").read_text()
            gateway_run = (source / "gateway/run.py").read_text()
            conversation_loop = (source / "agent/conversation_loop.py").read_text()
            tool_executor = (source / "agent/tool_executor.py").read_text()
            self.assertIn("(?:in|after)", credential_pool)
            self.assertIn("SYDNEY_MEMORY_REGISTRATION", agent_init)
            self.assertIn("SYDNEY_INBOUND_SPOOL_BEFORE_MODEL", gateway_run)
            self.assertIn("sydney_continuation_watcher", gateway_run)
            self.assertIn("SYDNEY_RETRY_AND_USAGE_GUARD", conversation_loop)
            self.assertIn("SYDNEY_TOOL_BEFORE", tool_executor)
            self.assertIn("SYDNEY_TOOL_AFTER", tool_executor)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "compileall",
                    "-q",
                    str(source / "agent"),
                    str(source / "gateway"),
                    str(source / "plugins/memory/sydney"),
                ],
                check=True,
            )

    def test_exact_hermes_patch_preserves_the_runtime_behavior_contract(self):
        checkout = os.environ.get("HERMES_EXACT_CHECKOUT")
        if not checkout:
            self.skipTest("HERMES_EXACT_CHECKOUT is not configured")
        installer = _load_overlay_module("install_sydney_overlay.py")
        retry = _load_overlay_module("sydney_retry.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "hermes"
            subprocess.run(
                ["git", "clone", "--quiet", "--no-checkout", checkout, str(source)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "checkout", "--quiet", "--detach", HERMES_COMMIT],
                check=True,
            )
            installer.install(source)
            credential_pool = (source / "agent/credential_pool.py").read_text()
            gateway_run = (source / "gateway/run.py").read_text()
            agent_init = (source / "agent/agent_init.py").read_text()
            conversation_loop = (source / "agent/conversation_loop.py").read_text()
            tool_executor = (source / "agent/tool_executor.py").read_text()

            namespace = {"re": __import__("re"), "Optional": Optional}
            function_source = credential_pool[
                credential_pool.index("def _extract_retry_delay_seconds") : credential_pool.index(
                    "\ndef _normalize_error_context",
                    credential_pool.index("def _extract_retry_delay_seconds"),
                )
            ]
            exec(function_source, namespace)
            self.assertEqual(namespace["_extract_retry_delay_seconds"]("retry in 47s"), 47)
            self.assertLess(
                gateway_run.index("record_inbound_before_model(\n"),
                gateway_run.index("result = agent.run_conversation"),
            )
            self.assertLess(
                tool_executor.index("# SYDNEY_TOOL_BEFORE\n"),
                tool_executor.index("result = agent._invoke_tool"),
            )
            self.assertGreater(
                tool_executor.index("# SYDNEY_TOOL_AFTER\n"),
                tool_executor.index("is_error, _ = _detect_tool_failure"),
            )
            self.assertIn("SydneyMemoryProvider", agent_init)
            self.assertIn('compression_target_ratio = float(_compression_cfg.get("target"', agent_init)
            self.assertIn('compression_protect_last = int(_compression_cfg.get("protect_last"', agent_init)
            self.assertIn("reserve_input_budget(agent, approx_request_tokens)", conversation_loop)
            self.assertIn("defer_retry_if_needed", conversation_loop)
            self.assertNotIn("/new", retry.AUTOMATIC_CONTINUATION_MESSAGE)
            self.assertNotIn("/reset", retry.AUTOMATIC_CONTINUATION_MESSAGE)
            self.assertNotIn("/compact", retry.AUTOMATIC_CONTINUATION_MESSAGE)

    def test_exact_template_overlay_applies_twice_without_byte_drift(self):
        checkout = os.environ.get("HERMES_TEMPLATE_EXACT_CHECKOUT")
        if not checkout:
            self.skipTest("HERMES_TEMPLATE_EXACT_CHECKOUT is not configured")
        overlay = _load_overlay_module("apply_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "template"
            subprocess.run(
                ["git", "clone", "--quiet", "--no-checkout", checkout, str(source)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "checkout", "--quiet", "--detach", UPSTREAM_COMMIT],
                check=True,
            )
            overlay.apply_overlay(source)
            first = {
                str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in source.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
            overlay.apply_overlay(source)
            second = {
                str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in source.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
            self.assertEqual(second, first)

    def test_exact_hermes_installer_rolls_back_replace_failure(self):
        checkout = os.environ.get("HERMES_EXACT_CHECKOUT")
        if not checkout:
            self.skipTest("HERMES_EXACT_CHECKOUT is not configured")
        installer = _load_overlay_module("install_sydney_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "hermes"
            subprocess.run(
                ["git", "clone", "--quiet", "--no-checkout", checkout, str(source)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "checkout", "--quiet", "--detach", HERMES_COMMIT],
                check=True,
            )
            real_replace = os.replace
            calls = 0

            def fail_third_replace(source_path, target_path):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("injected replace failure")
                real_replace(source_path, target_path)

            with (
                patch.object(installer.os, "replace", side_effect=fail_third_replace),
                self.assertRaises(OSError),
            ):
                installer.install(source)
            status = subprocess.run(
                ["git", "-C", str(source), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertEqual(status, "")
            self.assertFalse((source / "plugins/memory/sydney").exists())

    def test_exact_hermes_installer_rejects_unrelated_dirty_checkout(self):
        checkout = os.environ.get("HERMES_EXACT_CHECKOUT")
        if not checkout:
            self.skipTest("HERMES_EXACT_CHECKOUT is not configured")
        installer = _load_overlay_module("install_sydney_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "hermes"
            subprocess.run(
                ["git", "clone", "--quiet", "--no-checkout", checkout, str(source)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "checkout", "--quiet", "--detach", HERMES_COMMIT],
                check=True,
            )
            (source / "README.md").write_text("unrelated dirty change\n")
            before = (source / "README.md").read_bytes()
            with self.assertRaises(ValueError):
                installer.install(source)
            self.assertEqual((source / "README.md").read_bytes(), before)

    def test_bootstrap_keeps_identical_config_without_replacing_it(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
            )
            before = config_path.read_bytes()
            with (
                patch.object(bootstrap.os, "replace") as replace,
                patch.object(
                    Path, "write_text", side_effect=AssertionError("direct write")
                ),
            ):
                bootstrap.configure_atlas_backend(
                    config_path,
                    backend_url="https://backend.example.test",
                    token="not-a-real-token",
                )
            self.assertEqual(config_path.read_bytes(), before)
            self.assertFalse(replace.called)

    def test_bootstrap_preserves_original_on_atomic_replace_failure(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text("gateway:\n  provider: gemini\n")
            before = config_path.read_bytes()
            with patch.object(
                bootstrap.os, "replace", side_effect=OSError("injected replace failure")
            ):
                with self.assertRaises(OSError):
                    bootstrap.configure_atlas_backend(
                        config_path,
                        backend_url="https://backend.example.test",
                        token="not-a-real-token",
                    )
            self.assertEqual(config_path.read_bytes(), before)
            self.assertEqual(list(config_path.parent.glob(".atlas-bootstrap-*")), [])

    def test_bootstrap_preserves_existing_config_permissions(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text("gateway:\n  provider: gemini\n")
            config_path.chmod(0o640)
            bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
            )
            self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o640)
