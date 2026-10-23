# Link Pack listing photo save repair

Date: 2026-10-23. Base: `origin/main` at `58574cc`.

## Observed failure

The live public snapshot has a working PNG for item 26, “Christian Hill Gem,” and no thumbnail URL for item 28, “Dracut Expanded Ranch,” matching Brandon's screenshot. The attachment is a photograph of the screen, not the original listing image; the rejected upload's format and size are unknown.

The editor awaited thumbnail/PDF upload requests without checking their HTTP status, then closed and reported completion even on rejection. The server rejected images above 5 MB. The links tab also retained old item objects whenever refreshed items had the same count. Together, these paths could hide upload failures and make successful edits appear to revert.

## Repair

- Check every save/upload response and show the server's error without closing the form or clearing its selected file. Non-JSON errors have a readable fallback.
- Retain a newly created item's ID across upload retries. Refresh the draft when cancelling a partial save so committed items or edits remain visible.
- Show selected and saved thumbnail previews, including the persisted image when reopening an editor. Release temporary preview URLs on replacement/unmount.
- Render refreshed draft objects even when the number of links is unchanged, while retaining optimistic drag ordering.
- Accept still listing photos up to 20 MB; validate and normalize them in a backend worker thread to WebP, at most 1600 pixels per side. Preserve EXIF orientation and transparency. Reject images above 40 megapixels before decoding their pixels.
- Preserve accepted animated GIF/WebP bytes and MIME within their existing 5 MB limit. Reject larger animations explicitly without replacing a saved photo. Profile and background uploads retain their existing 5 MB limits.
- Include a content hash in thumbnail URLs so replacing an image does not reuse a browser's cached photo.

## Verification

- Regression tests failed before the repair for ignored upload errors, missing saved previews, retry duplication, stale draft refreshes, oversized photos, invalid image replacement, and unchanged image URLs. Review follow-ups reproduced cancellation and animation failures before their fixes.
- Focused backend suite: **31 passed**, exercising real multipart requests and independent committed SQLite sessions through save, reload, publish and public image retrieval. Includes JPG/PNG/WebP/GIF, EXIF rotation, alpha, invalid files, oversized files, animation preservation and replacement cache invalidation.
- Final frontend suite: **730 passed across 33 files**. TypeScript and targeted ESLint pass. The Next.js production build passes.
- Real Chrome browser check against a disposable local database passed: upload a 5,257,731-byte photo, reopen its saved preview, reject a malformed replacement without closing the editor, retry successfully, reload, publish and retrieve the public image. The generated still image was 3,130 bytes at 1600 pixels wide. The public card also rendered at 390 pixels without horizontal overflow; no page errors were observed. The fixture was a synthetic image, not Brandon's missing photograph.
- Independent review verified the focused backend/component tests and found no remaining actionable issues after the two follow-ups.

## Broader backend baseline

The final full offline backend suite reports **3,322 passed, 16 failed, 752 skipped, three deselected and three passed subtests**. Every failure below also reproduced against the unchanged `58574cc` source snapshot under the same isolated environment. They cover notification scheduling assertions, missing local OAuth/test dependencies, a local PostgreSQL TLS dependency, and a pre-existing branding source scan. None of these failures exercises the changed Link Pack paths; there are no new failure names relative to that baseline comparison.

```text
tests/test_booking_calendar.py::CreateBookingTests::test_create_booking_enqueues_attempt_and_confirmation_notifications
tests/test_calendar_oauth.py::CalendarOAuthTests::test_exchange_code_persists_refresh_token_and_updates_runtime_settings
tests/test_calendar_oauth.py::CalendarOAuthTests::test_get_auth_url_requests_offline_access_with_consent_prompt
tests/test_evaluator_router.py::EvaluatorRouterTests::test_evaluate_returns_calculation_id_and_stores_event
tests/test_evaluator_router.py::EvaluatorRouterTests::test_submit_rating_stores_linked_rating_event
tests/test_exp_branding_migration.py::test_active_sources_and_current_contract_do_not_reintroduce_old_brokerage
tests/test_investor_notifications.py::InvestorNotificationTests::test_full_analysis_enqueues_report_requested_notification
tests/test_leads_notifications.py::LeadNotificationRouteTests::test_capture_chat_lead_enqueues_chat_notification
tests/test_leads_notifications.py::LeadNotificationRouteTests::test_create_lead_enqueues_lead_notification
tests/test_leads_notifications.py::LeadNotificationRouteTests::test_funnel_register_enqueues_registration_notification
tests/test_notification_service.py::NotificationQueueModelTests::test_notification_job_table_has_retry_fields
tests/test_sydney_memory_provider.py::test_history_tool_schema_requires_one_backend_valid_search_mode
tests/test_workspace_oauth.py::WorkspaceOAuthTests::test_exchange_code_returns_credential_bundle_without_side_effects
tests/test_workspace_oauth.py::WorkspaceOAuthTests::test_get_auth_url_requests_offline_access_with_full_consent_prompt
tests/test_workspace_oauth.py::test_oauth_exchange_and_identity_verification_run_off_event_loop
tests/test_workspace_token_persistence.py::WorkspaceTokenPersistenceTests::test_load_workspace_refresh_token_from_db_sets_runtime_value
```

## Release status

Code repair is prepared on `codex/link-pack-photo-fix`; production has not been changed. Install the new Pillow dependency with the backend release, then release the frontend. No database migration is required. Brandon must re-upload the missing listing photo and publish the Link Pack after deployment; the screenshot does not contain the original upload bytes.

The pre-existing behavior whereby draft image replacements can affect existing public image URLs before publishing is outside this repair.
