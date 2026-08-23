import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


UPSTREAM_COMMIT = "7224d7c1a4dcffe9304f49bc843f55716f5561b4"
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
        self.assertEqual(manifest["tools"]["include"][:16], EXISTING_TOOLS)
        self.assertEqual(manifest["tools"]["include"][16:], CRM_TOOLS)
        self.assertEqual(len(manifest["tools"]["include"]), 22)
        self.assertEqual(len(set(manifest["tools"]["include"])), 22)

    def test_apply_overlay_is_idempotent_for_the_pinned_checkout_contract(self):
        overlay = _load_overlay_module("apply_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            (source / "Dockerfile").write_text("COPY start.sh /app/start.sh\n")
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

    def test_apply_overlay_refuses_unrelated_dirty_source_without_mutation(self):
        overlay = _load_overlay_module("apply_overlay.py")
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            (source / "Dockerfile").write_text("COPY start.sh /app/start.sh\n")
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
            (source / "Dockerfile").write_text("COPY start.sh /app/start.sh\n")
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
            (source / "Dockerfile").write_text("COPY start.sh /app/start.sh\n")
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

    def test_bootstrap_preserves_existing_config_and_writes_exact_22_tool_contract(
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
        self.assertEqual(atlas["tools"]["include"], EXISTING_TOOLS + CRM_TOOLS)
        self.assertFalse(atlas["tools"]["resources"])
        self.assertFalse(atlas["tools"]["prompts"])

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
