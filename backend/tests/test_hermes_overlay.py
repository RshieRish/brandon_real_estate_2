import ast
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

UPSTREAM_COMMIT = "7224d7c1a4dcffe9304f49bc843f55716f5561b4"
HERMES_TAG = "v2026.5.29.2"
HERMES_COMMIT = "77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5"
HERMES_HASHES = {
    "agent/credential_pool.py": "c4b78ca292ebb7072d56c17f3c7b7307cac3a33532cb1bb55f640373c55382e5",
    "agent/agent_init.py": "2fdea13cbce18a3d8eb0d0fae432d6ebb64efb221721ca9a179bcfe76956dfd3",
    "agent/gemini_schema.py": "a34dcdea0e3e017402ba6424fadd62505cb6e10960aef52e8ec8be1ea0163a82",
    "gateway/run.py": "9e3a780cfa36ac8931ad42481a56d4c55d9643efc1f7ec9b595fa886967d0a3f",
    "gateway/platforms/base.py": "de4b50de9920534ad17abbb22e5bffdd72149c2425eea73462e36c992960a078",
    "gateway/platforms/telegram.py": "c8054b03463e50e1eda06d5cafa355896e1cd981fe4f8d8ebabc4568de07fee7",
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
    module_name = name.removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Dataclasses resolves postponed annotations through sys.modules while
    # decorating the class on Python 3.13+.
    sys.modules[module_name] = module
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

    def test_exact_template_ci_checkout_is_a_complete_clone(self):
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/gmail-sydney-task-intake.yml"
        ).read_text()
        self.assertIn(
            "git clone --quiet --no-checkout \\\n"
            "            https://github.com/praveen-ks-2001/hermes-agent-template.git",
            workflow,
        )
        self.assertNotIn("--filter=blob:none", workflow)

    def test_backfill_cli_import_matches_installed_package_layout(self):
        overlay = Path(__file__).resolve().parents[2] / "hermes" / "overlay"
        installer = (overlay / "install_sydney_overlay.py").read_text()
        backfill = (overlay / "sydney_backfill.py").read_text()
        recovery = (overlay / "sydney_recovery.py").read_text()
        gateway = (overlay / "sydney_gateway.py").read_text()

        self.assertIn(
            '"plugins/memory/sydney/__init__.py": "sydney_memory_provider.py"',
            installer,
        )
        self.assertIn("from . import SydneyBackendClient", backfill)
        self.assertNotIn(
            "from .sydney_memory_provider import SydneyBackendClient", backfill
        )
        self.assertIn(
            '"plugins/memory/sydney/sydney_recovery.py": "sydney_recovery.py"',
            installer,
        )
        self.assertIn("from .sydney_backfill import SydneyBackfill", recovery)
        self.assertIn("from .sydney_spool import", recovery)
        self.assertIn(
            "from plugins.memory.sydney import (\n"
            "        SydneyBackendClient,\n"
            "        deliver_control_delivery_record,\n"
            "    )",
            gateway,
        )
        self.assertNotIn(
            "from plugins.memory.sydney.sydney_memory_provider import", gateway
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

    def test_managed_atlas_skill_routes_command_without_stale_fallback(self):
        root = Path(__file__).resolve().parents[2]
        skill = root / "hermes/skills/atlas-backend-operations/SKILL.md"
        text = skill.read_text()
        lowered = text.lower()

        self.assertIn("command_contacts_search", text)
        self.assertIn("command_contact_audience_preview", text)
        self.assertIn("navigation locator", lowered)
        self.assertIn("google contacts only", lowered)
        self.assertIn("review-only", lowered)
        self.assertIn("nothing was sent", lowered)
        self.assertNotIn("always pull and parse this sheet first", lowered)
        self.assertNotIn("/proc/{ppid}/environ", text)
        self.assertNotIn("admin_password", lowered)

    def test_manifest_pins_managed_skill_hash(self):
        root = Path(__file__).resolve().parents[2]
        skill = root / "hermes/skills/atlas-backend-operations/SKILL.md"
        manifest = json.loads((root / "hermes/overlay/manifest.json").read_text())
        managed = manifest["managed_skills"]["atlas-backend-operations"]

        self.assertEqual(
            managed,
            {
                "source": "skills/atlas-backend-operations/SKILL.md",
                "deployed_source": "atlas_backend_operations_skill.md",
                "destination": (
                    "skills/productivity/atlas-backend-operations/SKILL.md"
                ),
                "sha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
            },
        )

    def test_bootstrap_installs_managed_skill_once_and_preserves_other_skills(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "home"
            asset = root / "atlas_backend_operations_skill.md"
            asset.write_text("managed skill\n")
            other = home / "skills/productivity/other/SKILL.md"
            other.parent.mkdir(parents=True)
            other.write_text("keep\n")
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()
            manifest = {
                "managed_skills": {
                    "atlas-backend-operations": {
                        "source": "skills/atlas-backend-operations/SKILL.md",
                        "deployed_source": asset.name,
                        "destination": (
                            "skills/productivity/atlas-backend-operations/SKILL.md"
                        ),
                        "sha256": digest,
                    }
                }
            }

            first = bootstrap.install_managed_skills(home, manifest, asset_root=root)
            second = bootstrap.install_managed_skills(home, manifest, asset_root=root)
            installed = (
                home
                / manifest["managed_skills"]["atlas-backend-operations"]["destination"]
            )

            self.assertEqual(
                first,
                [
                    {
                        "name": "atlas-backend-operations",
                        "sha256": digest,
                        "changed": True,
                    }
                ],
            )
            self.assertEqual(
                second,
                [
                    {
                        "name": "atlas-backend-operations",
                        "sha256": digest,
                        "changed": False,
                    }
                ],
            )
            self.assertEqual(installed.read_bytes(), asset.read_bytes())
            self.assertEqual(other.read_text(), "keep\n")

    def test_bootstrap_rejects_managed_skill_hash_mismatch_without_mutation(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "home"
            destination = home / "skills/productivity/atlas-backend-operations/SKILL.md"
            destination.parent.mkdir(parents=True)
            destination.write_text("known good\n")
            asset = root / "atlas_backend_operations_skill.md"
            asset.write_text("tampered\n")
            manifest = {
                "managed_skills": {
                    "atlas-backend-operations": {
                        "deployed_source": asset.name,
                        "destination": str(destination.relative_to(home)),
                        "sha256": hashlib.sha256(b"expected\n").hexdigest(),
                    }
                }
            }

            with self.assertRaisesRegex(ValueError, "managed skill hash mismatch"):
                bootstrap.install_managed_skills(home, manifest, asset_root=root)

            self.assertEqual(destination.read_text(), "known good\n")

    def test_bootstrap_rejects_managed_skill_destination_outside_home(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "home"
            asset = root / "atlas_backend_operations_skill.md"
            asset.write_text("managed skill\n")
            manifest = {
                "managed_skills": {
                    "atlas-backend-operations": {
                        "deployed_source": asset.name,
                        "destination": "../escaped/SKILL.md",
                        "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                    }
                }
            }

            with self.assertRaisesRegex(ValueError, "destination escapes"):
                bootstrap.install_managed_skills(home, manifest, asset_root=root)

            self.assertFalse((root / "escaped/SKILL.md").exists())

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
                "atlas_backend_operations_skill.md",
                "install_sydney_overlay.py",
                "sydney_spool.py",
                "sydney_memory_provider.py",
                "sydney_retry.py",
                "sydney_backfill.py",
                "sydney_recovery.py",
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
            self.assertIn(
                "COPY atlas_backend_operations_skill.md /app/atlas_backend_operations_skill.md",
                first_dockerfile,
            )
            self.assertIn(
                "COPY sydney_recovery.py /app/sydney_recovery.py", first_dockerfile
            )
            self.assertIn("python /app/atlas_backend_bootstrap.py", first_start)
            self.assertLess(
                first_start.index("python /app/atlas_backend_bootstrap.py"),
                first_start.index("exec python /app/server.py"),
            )
            self.assertTrue((source / "atlas_backend_mcp.py").is_file())
            self.assertTrue((source / "atlas_backend_bootstrap.py").is_file())
            self.assertTrue((source / "atlas_backend_overlay_manifest.json").is_file())
            self.assertEqual(
                (source / "atlas_backend_operations_skill.md").read_bytes(),
                (
                    Path(__file__).resolve().parents[2]
                    / "hermes/skills/atlas-backend-operations/SKILL.md"
                ).read_bytes(),
            )
            for name in (
                "install_sydney_overlay.py",
                "sydney_spool.py",
                "sydney_memory_provider.py",
                "sydney_retry.py",
                "sydney_backfill.py",
                "sydney_recovery.py",
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
                first_dockerfile.index("uv pip install --system --no-cache -e"),
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
            config_path.write_text(
                "gateway:\n"
                "  provider: gemini\n"
                "session_reset:\n"
                "  mode: daily\n"
                "agent:\n"
                "  max_turns: 24\n"
                "compression:\n"
                "  enabled: false\n"
                "tool_guardrails:\n"
                "  enabled: false\n"
            )
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
        self.assertEqual(config["session_reset"], {"mode": "daily"})
        self.assertEqual(config["agent"]["max_turns"], 24)
        self.assertEqual(config["compression"], {"enabled": False})
        self.assertEqual(config["tool_guardrails"], {"enabled": False})
        self.assertNotIn("provider", config.get("memory", {}))

    def test_bootstrap_wires_configured_runtime_limits(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(
                os.environ,
                {
                    "SYDNEY_CONTEXT_PROMPT_COMPRESS_TOKENS": "88000",
                    "SYDNEY_CONTEXT_MAX_TURNS": "9",
                },
                clear=False,
            ),
        ):
            config_path = Path(temporary_directory) / "config.yaml"
            bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
                durable_context_enabled=True,
                external_user_id="brandon-id",
                external_chat_id="brandon-chat",
                allowed_external_user_ids={"brandon-id"},
            )
            config = bootstrap.load_yaml(config_path)

        self.assertEqual(config["agent"]["max_turns"], 9)
        self.assertEqual(config["compression"]["threshold_tokens"], 88_000)
        self.assertEqual(config["session_reset"], {"mode": "none"})
        self.assertTrue(config["tool_guardrails"]["enabled"])

    def test_bootstrap_disable_restores_every_sydney_owned_runtime_setting(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "gateway:\n"
                "  provider: gemini\n"
                "session_reset:\n"
                "  mode: daily\n"
                "agent:\n"
                "  max_turns: 24\n"
                "  unrelated: keep-me\n"
                "compression:\n"
                "  enabled: false\n"
                "  threshold: 0.5\n"
                "tool_guardrails:\n"
                "  enabled: false\n"
                "memory:\n"
                "  provider: legacy\n"
                "  unrelated: keep-me\n"
            )
            original = bootstrap.load_yaml(config_path)

            bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
                durable_context_enabled=True,
                external_user_id="brandon-id",
                external_chat_id="brandon-chat",
                allowed_external_user_ids={"brandon-id"},
            )
            enabled = bootstrap.load_yaml(config_path)
            bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
                durable_context_enabled=False,
                external_user_id="brandon-id",
                external_chat_id="brandon-chat",
                allowed_external_user_ids={"brandon-id"},
            )
            restored = bootstrap.load_yaml(config_path)

        self.assertEqual(enabled["memory"]["provider"], "sydney")
        self.assertEqual(restored["session_reset"], original["session_reset"])
        self.assertEqual(restored["agent"], original["agent"])
        self.assertEqual(restored["compression"], original["compression"])
        self.assertEqual(restored["tool_guardrails"], original["tool_guardrails"])
        self.assertEqual(restored["memory"], original["memory"])
        self.assertEqual(restored["gateway"], original["gateway"])

    def test_bootstrap_disable_restores_sydney_settings_without_bridge_credentials(
        self,
    ):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "session_reset:\n"
                "  mode: daily\n"
                "agent:\n"
                "  max_turns: 24\n"
                "memory:\n"
                "  provider: legacy\n"
            )
            original = bootstrap.load_yaml(config_path)
            bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
                durable_context_enabled=True,
                external_user_id="brandon-id",
                external_chat_id="brandon-chat",
                allowed_external_user_ids={"brandon-id"},
            )

            changed = bootstrap.configure_atlas_backend(
                config_path,
                backend_url="",
                token="",
                durable_context_enabled=False,
                external_user_id="brandon-id",
                external_chat_id="brandon-chat",
                allowed_external_user_ids={"brandon-id"},
            )
            restored = bootstrap.load_yaml(config_path)
            backup_path = config_path.parent / bootstrap._CONFIG_BACKUP_NAME
            backup_exists = backup_path.exists()

        self.assertTrue(changed)
        self.assertEqual(restored["session_reset"], original["session_reset"])
        self.assertEqual(restored["agent"], original["agent"])
        self.assertEqual(restored["memory"], original["memory"])
        self.assertFalse(backup_exists)

    def test_bootstrap_missing_bridge_credentials_restores_even_when_flag_stays_on(
        self,
    ):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "session_reset:\n"
                "  mode: daily\n"
                "agent:\n"
                "  max_turns: 24\n"
                "memory:\n"
                "  provider: legacy\n"
            )
            original = bootstrap.load_yaml(config_path)
            bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
                durable_context_enabled=True,
                external_user_id="brandon-id",
                external_chat_id="brandon-chat",
                allowed_external_user_ids={"brandon-id"},
            )

            changed = bootstrap.configure_atlas_backend(
                config_path,
                backend_url="",
                token="",
                durable_context_enabled=True,
                external_user_id="brandon-id",
                external_chat_id="brandon-chat",
                allowed_external_user_ids={"brandon-id"},
            )
            restored = bootstrap.load_yaml(config_path)
            backup_path = config_path.parent / bootstrap._CONFIG_BACKUP_NAME
            backup_exists = backup_path.exists()

        self.assertTrue(changed)
        self.assertEqual(restored["session_reset"], original["session_reset"])
        self.assertEqual(restored["agent"], original["agent"])
        self.assertEqual(restored["memory"], original["memory"])
        self.assertFalse(backup_exists)

    def test_bootstrap_disable_removes_sydney_containers_that_were_absent(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text("gateway:\n  provider: gemini\n")
            kwargs = {
                "backend_url": "https://backend.example.test",
                "token": "not-a-real-token",
                "external_user_id": "brandon-id",
                "external_chat_id": "brandon-chat",
                "allowed_external_user_ids": {"brandon-id"},
            }
            bootstrap.configure_atlas_backend(
                config_path,
                durable_context_enabled=True,
                **kwargs,
            )
            bootstrap.configure_atlas_backend(
                config_path,
                durable_context_enabled=False,
                **kwargs,
            )
            restored = bootstrap.load_yaml(config_path)

        self.assertNotIn("session_reset", restored)
        self.assertNotIn("agent", restored)
        self.assertNotIn("compression", restored)
        self.assertNotIn("tool_guardrails", restored)
        self.assertNotIn("memory", restored)

    def test_bootstrap_enables_sydney_only_for_master_flag_and_allowlisted_identity(
        self,
    ):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            changed = bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
                durable_context_enabled=True,
                external_user_id="brandon-id",
                external_chat_id="brandon-chat",
                allowed_external_user_ids={"brandon-id"},
            )
            config = bootstrap.load_yaml(config_path)
        self.assertTrue(changed)
        self.assertEqual(config["memory"]["provider"], "sydney")

    def test_bootstrap_preserves_previous_memory_provider_without_chat_id(self):
        bootstrap = _load_overlay_module("atlas_backend_bootstrap.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "session_reset:\n  mode: daily\nmemory:\n  provider: legacy\n"
            )
            bootstrap.configure_atlas_backend(
                config_path,
                backend_url="https://backend.example.test",
                token="not-a-real-token",
                durable_context_enabled=True,
                external_user_id="brandon-id",
                allowed_external_user_ids={"brandon-id"},
            )
            config = bootstrap.load_yaml(config_path)
            backup_path = config_path.parent / bootstrap._CONFIG_BACKUP_NAME

        self.assertEqual(config["memory"]["provider"], "legacy")
        self.assertEqual(config["session_reset"], {"mode": "daily"})
        self.assertFalse(backup_path.exists())

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
                [
                    "git",
                    "-C",
                    str(source),
                    "checkout",
                    "--quiet",
                    "--detach",
                    HERMES_COMMIT,
                ],
                check=True,
            )
            installer.install(source)
            first = {
                str(path.relative_to(source)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in source.rglob("*.py")
                if ".git" not in path.parts
            }
            installer.install(source)
            second = {
                str(path.relative_to(source)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in source.rglob("*.py")
                if ".git" not in path.parts
            }
            self.assertEqual(second, first)
            self.assertIn("plugins/memory/sydney/__init__.py", first)
            self.assertIn("plugins/memory/sydney/sydney_recovery.py", first)
            self.assertIn("agent/sydney_runtime.py", first)
            self.assertIn("gateway/sydney_gateway.py", first)

            credential_pool = (source / "agent/credential_pool.py").read_text()
            agent_init = (source / "agent/agent_init.py").read_text()
            gateway_run = (source / "gateway/run.py").read_text()
            gateway_base = (source / "gateway/platforms/base.py").read_text()
            telegram = (source / "gateway/platforms/telegram.py").read_text()
            conversation_loop = (source / "agent/conversation_loop.py").read_text()
            tool_executor = (source / "agent/tool_executor.py").read_text()
            gemini_schema = (source / "agent/gemini_schema.py").read_text()
            self.assertIn("(?:in|after)", credential_pool)
            self.assertIn("SYDNEY_MEMORY_REGISTRATION", agent_init)
            self.assertIn("SYDNEY_MCP_HISTORY_TOOL_HIDE", agent_init)
            self.assertIn("mcp_atlas_backend_context_history_search", agent_init)
            self.assertIn("SYDNEY_COMPRESSION_TOKEN_LIMIT", agent_init)
            self.assertIn("SYDNEY_INBOUND_SPOOL_BEFORE_MODEL", gateway_run)
            self.assertIn("SYDNEY_RUN_LEASE_GATE", gateway_run)
            self.assertIn("sydney_continuation_watcher", gateway_run)
            self.assertIn("SYDNEY_DURABLE_STREAMING_DISABLED", gateway_run)
            self.assertIn("SYDNEY_DELIVERY_CONFIRMATION", gateway_base)
            self.assertIn("SYDNEY_AMBIGUOUS_DELIVERY_SINGLE_ATTEMPT", telegram)
            self.assertIn('metadata.get("sydney_durable_delivery")', gateway_base)
            self.assertIn("SYDNEY_RETRY_AND_USAGE_GUARD", conversation_loop)
            self.assertIn("SYDNEY_TOOL_BEFORE", tool_executor)
            self.assertIn("SYDNEY_TOOL_AFTER", tool_executor)
            self.assertIn("SYDNEY_GEMINI_CONDITIONAL_UNION_FALLBACK", gemini_schema)
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
                [
                    "git",
                    "-C",
                    str(source),
                    "checkout",
                    "--quiet",
                    "--detach",
                    HERMES_COMMIT,
                ],
                check=True,
            )
            installer.install(source)
            credential_pool = (source / "agent/credential_pool.py").read_text()
            gateway_run = (source / "gateway/run.py").read_text()
            gateway_base = (source / "gateway/platforms/base.py").read_text()
            agent_init = (source / "agent/agent_init.py").read_text()
            conversation_loop = (source / "agent/conversation_loop.py").read_text()
            tool_executor = (source / "agent/tool_executor.py").read_text()
            gemini_schema = (source / "agent/gemini_schema.py").read_text()

            gemini_namespace: dict[str, object] = {}
            exec(gemini_schema, gemini_namespace)
            sanitize_gemini_tool_parameters = gemini_namespace[
                "sanitize_gemini_tool_parameters"
            ]
            conditional_schema = {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "recent_conversations": {"type": "boolean"},
                },
                "anyOf": [
                    {"required": ["query"]},
                    {"required": ["recent_conversations"]},
                ],
            }
            sanitized_conditional = sanitize_gemini_tool_parameters(conditional_schema)
            self.assertNotIn("anyOf", sanitized_conditional)
            self.assertEqual(
                set(sanitized_conditional["properties"]),
                {"query", "recent_conversations"},
            )
            typed_union_schema = {
                "type": "object",
                "properties": {
                    "value": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "integer"},
                        ]
                    }
                },
            }
            sanitized_typed_union = sanitize_gemini_tool_parameters(typed_union_schema)
            self.assertEqual(
                sanitized_typed_union["properties"]["value"]["anyOf"],
                [{"type": "string"}, {"type": "integer"}],
            )

            namespace = {"re": __import__("re"), "Optional": Optional}
            function_source = credential_pool[
                credential_pool.index(
                    "def _extract_retry_delay_seconds"
                ) : credential_pool.index(
                    "\ndef _normalize_error_context",
                    credential_pool.index("def _extract_retry_delay_seconds"),
                )
            ]
            exec(function_source, namespace)
            self.assertEqual(
                namespace["_extract_retry_delay_seconds"]("retry in 47s"), 47
            )
            self.assertLess(
                gateway_run.index("record_inbound_before_model(\n"),
                gateway_run.index("result = agent.run_conversation"),
            )
            gateway_tree = ast.parse(gateway_run)
            run_agent_function = next(
                node
                for node in ast.walk(gateway_tree)
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_agent"
            )
            run_agent_arguments = {
                argument.arg
                for argument in (
                    run_agent_function.args.posonlyargs
                    + run_agent_function.args.args
                    + run_agent_function.args.kwonlyargs
                )
            }
            self.assertIn("_sydney_internal", run_agent_arguments)
            self.assertIn("_sydney_persisted_message", run_agent_arguments)
            self.assertFalse(
                any(
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id == "event"
                    for node in ast.walk(run_agent_function)
                ),
                "_run_agent must not capture the out-of-scope gateway event",
            )
            run_agent_calls = [
                node
                for node in ast.walk(gateway_tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_run_agent"
            ]
            self.assertEqual(len(run_agent_calls), 2)
            for run_agent_call in run_agent_calls:
                keyword_names = {
                    keyword.arg
                    for keyword in run_agent_call.keywords
                    if keyword.arg is not None
                }
                self.assertIn("_sydney_internal", keyword_names)
                self.assertIn("_sydney_persisted_message", keyword_names)
            recursive_run_call = next(
                run_agent_call
                for run_agent_call in run_agent_calls
                if any(
                    keyword.arg == "_interrupt_depth"
                    for keyword in run_agent_call.keywords
                )
            )
            recursive_keywords = {
                keyword.arg: keyword.value
                for keyword in recursive_run_call.keywords
                if keyword.arg is not None
            }
            self.assertEqual(
                getattr(recursive_keywords["_sydney_internal"], "id", None),
                "next_sydney_internal",
            )
            self.assertEqual(
                getattr(recursive_keywords["_sydney_persisted_message"], "id", None),
                "next_sydney_persisted_message",
            )
            self.assertIn('getattr(pending_event, "internal", False)', gateway_run)
            self.assertIn('getattr(pending_event, "text", "")', gateway_run)
            self.assertIn(
                '_sydney_internal=bool(getattr(event, "internal", False))',
                gateway_run,
            )
            self.assertIn(
                '_sydney_persisted_message=str(getattr(event, "text", "") or "")',
                gateway_run,
            )
            self.assertIn(
                '_conversation_kwargs["persist_user_message"] = str(',
                gateway_run,
            )
            self.assertIn('_sydney_persisted_message or ""', gateway_run)
            self.assertNotIn("stage_run_outcome(agent, result)", gateway_run)
            self.assertGreater(
                gateway_run.index("SYDNEY_FINAL_DELIVERY_STAGE"),
                gateway_run.index("result = agent.run_conversation"),
            )
            self.assertIn("SYDNEY_DURABLE_STREAMING_DISABLED", gateway_run)
            self.assertIn("SYDNEY_QUEUED_DELIVERY_CONFIRMATION", gateway_run)
            self.assertIn("record_delivery_by_key", gateway_run)
            self.assertIn(
                "_sydney_first_durable = bool(",
                gateway_run,
            )
            self.assertIn(
                "if _sydney_first_durable:\n"
                "                                _sydney_first_metadata[",
                gateway_run,
            )
            self.assertIn(
                'first_response = str(_sydney_first_result.get("final_response") or "")',
                gateway_run,
            )
            self.assertIn("event._sydney_delivery_key", gateway_run)
            self.assertNotIn("complete_active_run", gateway_run)
            self.assertGreater(
                gateway_base.index("_sydney_delivery_outcome("),
                gateway_base.index("processing_ok ="),
            )
            self.assertIn(
                "release_active_execution_for_event",
                gateway_base,
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
            self.assertIn(
                'compression_target_ratio = float(_compression_cfg.get("target"',
                agent_init,
            )
            self.assertIn(
                'compression_protect_last = int(_compression_cfg.get("protect_last"',
                agent_init,
            )
            self.assertNotIn(
                "    from agent.model_metadata import MINIMUM_CONTEXT_LENGTH",
                agent_init,
            )
            self.assertIn(
                "delivery_succeeded = delivery_succeeded and bool(",
                gateway_base,
            )
            self.assertIn("# SYDNEY_DURABLE_IMAGE_DELIVERY", gateway_base)
            self.assertIn(
                "reserve_input_budget(agent, approx_request_tokens)", conversation_loop
            )
            self.assertIn("defer_retry_if_needed", conversation_loop)
            self.assertIn("defer_compression_exhaustion", gateway_run)
            self.assertIn("# SYDNEY_DURABLE_OUTCOME_PROPAGATION", gateway_run)
            self.assertIn("sydney_continuation_staged", gateway_run)
            self.assertIn("# SYDNEY_LINEAGE_AWARE_COMPRESSION_RESET", gateway_run)
            self.assertIn('reason="compression_exhausted"', gateway_run)
            self.assertIn(
                'if agent_result.get("sydney_continuation_staged"):', gateway_run
            )
            self.assertNotIn("/new", retry.AUTOMATIC_CONTINUATION_MESSAGE)
            self.assertNotIn("/reset", retry.AUTOMATIC_CONTINUATION_MESSAGE)
            self.assertNotIn("/compact", retry.AUTOMATIC_CONTINUATION_MESSAGE)

            process_environment = os.environ.copy()
            process_environment["PYTHONPATH"] = str(source)
            process_environment["HERMES_HOME"] = str(
                Path(temporary_directory) / "hermes-home"
            )
            init_probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "\n".join(  # noqa: FLY002 - explicit subprocess probe lines
                        (
                            "from unittest.mock import MagicMock",
                            "import hermes_cli.config as config",
                            'config.load_config = lambda: {"compression": {"threshold_tokens": 96000}}',
                            "import run_agent",
                            "run_agent.OpenAI = MagicMock",
                            "agent = run_agent.AIAgent(model='test/model', api_key='test-key', base_url='http://localhost:1234/v1', quiet_mode=True, skip_memory=True, skip_context_files=True)",
                            "print(agent.context_compressor.threshold_tokens)",
                        )
                    ),
                ],
                cwd=source,
                env=process_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(init_probe.stdout.strip(), "96000")

            delivery_probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "\n".join(  # noqa: FLY002 - explicit subprocess probe lines
                        (
                            "import asyncio",
                            "from gateway.config import Platform, PlatformConfig",
                            "from gateway.platforms.base import BasePlatformAdapter, MessageEvent, SendResult",
                            "from gateway.session import SessionSource",
                            "import agent.sydney_runtime as runtime",
                            "outcomes = []",
                            "runtime.record_delivery_outcome = lambda event, *, delivered: outcomes.append(delivered)",
                            "class Adapter(BasePlatformAdapter):",
                            "    def __init__(self, image_success):",
                            "        super().__init__(PlatformConfig(), Platform.TELEGRAM)",
                            "        self.image_success = image_success",
                            "    @property",
                            "    def name(self): return 'test'",
                            "    async def connect(self): return True",
                            "    async def disconnect(self): return None",
                            "    async def get_chat_info(self, chat_id): return {}",
                            "    async def send(self, chat_id, content, reply_to=None, metadata=None): return SendResult(success=True)",
                            "    async def send_image(self, chat_id, image_url, caption=None, reply_to=None, metadata=None): return SendResult(success=self.image_success, error=None if self.image_success else 'injected')",
                            "    async def _keep_typing(self, *args, **kwargs): await asyncio.Event().wait()",
                            "    async def _run_processing_hook(self, *args, **kwargs): return None",
                            "    async def _flush_text_debounce_now(self, *args, **kwargs): return None",
                            "    async def stop_typing(self, chat_id): return None",
                            "async def run_case(response, image_success, message_id):",
                            "    adapter = Adapter(image_success)",
                            "    async def handler(event): return response",
                            "    adapter.set_message_handler(handler)",
                            "    source = SessionSource(platform=Platform.TELEGRAM, chat_id='chat')",
                            "    event = MessageEvent(text='go', source=source, message_id=message_id)",
                            "    event._sydney_delivery_key = ('telegram', 'chat', message_id)",
                            "    key = 'session-' + message_id",
                            "    adapter._active_sessions[key] = asyncio.Event()",
                            "    adapter._session_tasks[key] = asyncio.current_task()",
                            "    await adapter._process_message_background(event, key)",
                            "async def main():",
                            "    await run_case('hello\\n![proof](https://example.test/proof.jpg)', False, 'one')",
                            "    await run_case('![proof](https://example.test/proof.jpg)', True, 'two')",
                            "asyncio.run(main())",
                            "print(outcomes)",
                        )
                    ),
                ],
                cwd=source,
                env=process_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(delivery_probe.stdout.strip(), "[False, True]")

            late_delivery_key_probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "\n".join(  # noqa: FLY002 - explicit subprocess probe lines
                        (
                            "import asyncio",
                            "import gateway.platforms.base as base_module",
                            "from gateway.config import Platform, PlatformConfig",
                            "from gateway.platforms.base import BasePlatformAdapter, MessageEvent, SendResult",
                            "from gateway.session import SessionSource",
                            "import agent.sydney_runtime as runtime",
                            "async def no_sleep(*args, **kwargs): return None",
                            "base_module.asyncio.sleep = no_sleep",
                            "outcomes = []",
                            "runtime.record_delivery_outcome = lambda event, *, delivered: outcomes.append(delivered)",
                            "class Adapter(BasePlatformAdapter):",
                            "    def __init__(self, send_success):",
                            "        super().__init__(PlatformConfig(), Platform.TELEGRAM)",
                            "        self.send_success = send_success",
                            "        self.calls = []",
                            "    @property",
                            "    def name(self): return 'test'",
                            "    async def connect(self): return True",
                            "    async def disconnect(self): return None",
                            "    async def get_chat_info(self, chat_id): return {}",
                            "    async def send(self, chat_id, content, reply_to=None, metadata=None):",
                            "        self.calls.append(dict(metadata or {}))",
                            "        return SendResult(success=self.send_success, error=None if self.send_success else 'connection reset', retryable=not self.send_success)",
                            "    async def _keep_typing(self, *args, **kwargs): await asyncio.Event().wait()",
                            "    async def _run_processing_hook(self, *args, **kwargs): return None",
                            "    async def _flush_text_debounce_now(self, *args, **kwargs): return None",
                            "    async def stop_typing(self, chat_id): return None",
                            "async def run_case(response, send_success, message_id):",
                            "    adapter = Adapter(send_success)",
                            "    async def handler(event):",
                            "        event._sydney_delivery_key = ('telegram', 'chat', message_id)",
                            "        return response",
                            "    adapter.set_message_handler(handler)",
                            "    source = SessionSource(platform=Platform.TELEGRAM, chat_id='chat')",
                            "    event = MessageEvent(text='go', source=source, message_id=message_id)",
                            "    key = 'session-' + message_id",
                            "    adapter._active_sessions[key] = asyncio.Event()",
                            "    adapter._session_tasks[key] = asyncio.current_task()",
                            "    before = len(outcomes)",
                            "    await adapter._process_message_background(event, key)",
                            "    return adapter.calls, outcomes[before:]",
                            "async def main():",
                            "    late_calls, late_outcomes = await run_case('final', False, 'late')",
                            "    stale_calls, stale_outcomes = await run_case(None, True, 'stale')",
                            "    print(len(late_calls), late_calls[0].get('sydney_durable_delivery'), late_outcomes, len(stale_calls), stale_outcomes)",
                            "asyncio.run(main())",
                        )
                    ),
                ],
                cwd=source,
                env=process_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                late_delivery_key_probe.stdout.strip(), "1 True [False] 0 [False]"
            )
            self.assertIn(
                "delivered=bool(delivery_attempted and delivery_succeeded)",
                gateway_base,
            )

            ambiguous_retry_probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "\n".join(  # noqa: FLY002 - explicit subprocess probe lines
                        (
                            "import asyncio",
                            "import gateway.platforms.base as base_module",
                            "from gateway.config import Platform, PlatformConfig",
                            "from gateway.platforms.base import BasePlatformAdapter, SendResult",
                            "async def no_sleep(*args, **kwargs): return None",
                            "base_module.asyncio.sleep = no_sleep",
                            "class Adapter(BasePlatformAdapter):",
                            "    def __init__(self):",
                            "        super().__init__(PlatformConfig(), Platform.TELEGRAM)",
                            "        self.calls = 0",
                            "    @property",
                            "    def name(self): return 'test'",
                            "    async def connect(self): return True",
                            "    async def disconnect(self): return None",
                            "    async def get_chat_info(self, chat_id): return {}",
                            "    async def send(self, chat_id, content, reply_to=None, metadata=None):",
                            "        self.calls += 1",
                            "        return SendResult(success=False, error='connection reset', retryable=True)",
                            "async def main():",
                            "    adapter = Adapter()",
                            "    result = await adapter._send_with_retry('123', 'final', metadata={'sydney_durable_delivery': True}, max_retries=2, base_delay=0)",
                            "    print(adapter.calls, result.success)",
                            "asyncio.run(main())",
                        )
                    ),
                ],
                cwd=source,
                env=process_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ambiguous_retry_probe.stdout.strip(), "1 False")

            telegram_retry_probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "\n".join(  # noqa: FLY002 - explicit subprocess probe lines
                        (
                            "import asyncio",
                            "import gateway.platforms.telegram as telegram_module",
                            "from gateway.config import PlatformConfig",
                            "from gateway.platforms.telegram import TelegramAdapter",
                            "async def no_sleep(*args, **kwargs): return None",
                            "telegram_module.asyncio.sleep = no_sleep",
                            "class Bot:",
                            "    def __init__(self): self.calls = 0",
                            "    async def send_message(self, **kwargs):",
                            "        self.calls += 1",
                            "        raise OSError('ambiguous delivery')",
                            "async def main():",
                            "    adapter = TelegramAdapter(PlatformConfig())",
                            "    bot = Bot()",
                            "    adapter._bot = bot",
                            "    result = await adapter.send('123', 'final', metadata={'sydney_durable_delivery': True})",
                            "    print(bot.calls, result.success)",
                            "asyncio.run(main())",
                        )
                    ),
                ],
                cwd=source,
                env=process_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(telegram_retry_probe.stdout.strip(), "1 False")

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
                [
                    "git",
                    "-C",
                    str(source),
                    "checkout",
                    "--quiet",
                    "--detach",
                    UPSTREAM_COMMIT,
                ],
                check=True,
            )
            overlay.apply_overlay(source)
            first = {
                str(path.relative_to(source)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in source.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
            overlay.apply_overlay(source)
            second = {
                str(path.relative_to(source)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
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
                [
                    "git",
                    "-C",
                    str(source),
                    "checkout",
                    "--quiet",
                    "--detach",
                    HERMES_COMMIT,
                ],
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
                [
                    "git",
                    "-C",
                    str(source),
                    "checkout",
                    "--quiet",
                    "--detach",
                    HERMES_COMMIT,
                ],
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
