"""add Sydney task clarification and review persistence

Revision ID: 84d7a5f9b2c3
Revises: 83c6f4e8a1b2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "84d7a5f9b2c3"
down_revision: Union[str, None] = "83c6f4e8a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNED_TABLES = (
    "gmail_sync_accounts",
    "gmail_sync_runs",
    "gmail_sync_page_checkpoints",
    "gmail_missing_message_incidents",
    "gmail_message_receipts",
    "gmail_message_origins",
    "gmail_extraction_attempts",
    "gmail_extracted_obligations",
    "crm_task_suggestions",
    "crm_task_suggestion_sources",
    "crm_task_suggestion_suppressions",
    "gmail_backfill_requests",
    "crm_task_clarifications",
    "sydney_question_outbox",
    "crm_task_suggestion_approval_nonces",
    "crm_task_suggestion_events",
)


def _uuid_id() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _now(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _backfill_task4_authority() -> None:
    op.execute(
        sa.text(
            "LOCK TABLE crm_task_suggestions, gmail_extracted_obligations, "
            "crm_contacts IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    op.add_column(
        "gmail_extracted_obligations",
        sa.Column(
            "owner_ambiguous",
            sa.Boolean(),
            nullable=True,
        ),
    )
    op.add_column(
        "crm_task_suggestions",
        sa.Column(
            "owner_clarification_pending",
            sa.Boolean(),
            nullable=True,
        ),
    )
    op.add_column(
        "crm_task_suggestions",
        sa.Column(
            "task_details_clarification_pending",
            sa.Boolean(),
            nullable=True,
        ),
    )
    op.add_column(
        "crm_task_suggestions",
        sa.Column(
            "contact_resolution_state",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "crm_task_suggestions",
        sa.Column("contact_resolution_hash", sa.String(length=64), nullable=True),
    )

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM gmail_extracted_obligations
                    WHERE NOT (evaluator_result_json IS JSON OBJECT WITH UNIQUE KEYS)
                       OR NOT (evaluator_result_json::jsonb ? 'owner_ambiguous')
                       OR jsonb_typeof(evaluator_result_json::jsonb ->
                            'owner_ambiguous') <> 'boolean'
                       OR NOT (evaluator_result_json::jsonb ? 'owner_state')
                       OR jsonb_typeof(evaluator_result_json::jsonb ->
                            'owner_state') <> 'string'
                       OR (
                            (evaluator_result_json::jsonb ->>
                                'owner_ambiguous')::boolean
                            <> ((evaluator_result_json::jsonb ->>
                                'owner_state') = 'ambiguous')
                       )
                       OR (
                            (evaluator_result_json::jsonb ->>
                                'owner_state') = 'implicit_brandon'
                            AND requested_owner IS NOT NULL
                       )
                       OR (
                            (evaluator_result_json::jsonb ->>
                                'owner_state') = 'explicit'
                            AND requested_owner IS NULL
                       )
                       OR (evaluator_result_json::jsonb ->> 'owner_state')
                            NOT IN ('ambiguous', 'implicit_brandon', 'explicit')
                       OR (
                            taxonomy_fallback
                            AND evaluator_result_json::jsonb ->
                                'taxonomy_fallback' <> 'true'::jsonb
                       )
                       OR (
                            NOT taxonomy_fallback
                            AND evaluator_result_json::jsonb ?
                                'taxonomy_fallback'
                       )
                ) THEN
                    RAISE EXCEPTION
                        'revision 84 owner ambiguity backfill refused';
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            DROP TRIGGER trg_gmail_extracted_obligations_append_only
            ON gmail_extracted_obligations
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE gmail_extracted_obligations
            SET owner_ambiguous =
                (evaluator_result_json::jsonb ->> 'owner_ambiguous')::boolean
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_gmail_extracted_obligations_append_only
            BEFORE UPDATE OR DELETE ON gmail_extracted_obligations
            FOR EACH ROW
            EXECUTE FUNCTION gmail_task_intake_reject_evidence_mutation()
            """
        )
    )
    op.alter_column(
        "gmail_extracted_obligations",
        "owner_ambiguous",
        existing_type=sa.Boolean(),
        nullable=False,
    )
    op.create_index(
        "ix_gmail_extracted_obligations_suggestion_owner_ambiguous",
        "gmail_extracted_obligations",
        ["reconciled_suggestion_id", "owner_ambiguous", "id"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            UPDATE crm_task_suggestions AS suggestion
            SET owner_clarification_pending = EXISTS (
                    SELECT 1
                    FROM gmail_extracted_obligations AS obligation
                    WHERE obligation.reconciled_suggestion_id = suggestion.id
                      AND obligation.owner_ambiguous
                ),
                task_details_clarification_pending = EXISTS (
                    SELECT 1
                    FROM gmail_extracted_obligations AS obligation
                    WHERE obligation.reconciled_suggestion_id = suggestion.id
                      AND obligation.taxonomy_fallback
                )
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM crm_task_suggestions
                    WHERE ('missing_required_field' = ANY(blocker_codes))
                        <> (owner_clarification_pending OR
                            task_details_clarification_pending)
                ) THEN
                    RAISE EXCEPTION
                        'revision 84 clarification cause backfill refused';
                END IF;
            END
            $$;
            """
        )
    )

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM crm_task_suggestions AS suggestion
                    LEFT JOIN crm_contacts AS selected
                      ON selected.id = suggestion.contact_id
                    WHERE suggestion.contact_id IS NOT NULL
                      AND (
                        'ambiguous_contact' = ANY(suggestion.blocker_codes)
                        OR selected.id IS NULL
                        OR selected.email IS NULL
                        OR selected.normalized_email IS NULL
                        OR lower(btrim(selected.email)) <>
                            selected.normalized_email
                        OR selected.normalized_email !~
                            '^[^[:space:]@]+@[^[:space:]@]+$'
                        OR 1 <> (
                            SELECT count(*)
                            FROM crm_contacts AS candidate
                            WHERE candidate.normalized_email =
                                selected.normalized_email
                        )
                      )
                ) THEN
                    RAISE EXCEPTION
                        'revision 84 contact resolution backfill refused';
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE crm_task_suggestions AS suggestion
            SET contact_resolution_state = CASE
                    WHEN suggestion.contact_id IS NOT NULL THEN 'inferred_unique'
                    WHEN 'ambiguous_contact' = ANY(suggestion.blocker_codes)
                        THEN 'unresolved'
                    ELSE 'not_provided'
                END,
                contact_resolution_hash = CASE
                    WHEN suggestion.contact_id IS NULL THEN NULL
                    ELSE (
                        SELECT encode(
                            sha256(
                                convert_to(
                                    'sws:crm-contact-resolution:v1', 'UTF8'
                                ) || decode('00', 'hex') ||
                                convert_to(selected.id::text, 'UTF8') ||
                                decode('00', 'hex') ||
                                convert_to(selected.normalized_email, 'UTF8')
                            ),
                            'hex'
                        )
                        FROM crm_contacts AS selected
                        WHERE selected.id = suggestion.contact_id
                    )
                END
            """
        )
    )
    op.alter_column(
        "crm_task_suggestions",
        "owner_clarification_pending",
        existing_type=sa.Boolean(),
        nullable=False,
    )
    op.alter_column(
        "crm_task_suggestions",
        "task_details_clarification_pending",
        existing_type=sa.Boolean(),
        nullable=False,
    )
    op.alter_column(
        "crm_task_suggestions",
        "contact_resolution_state",
        existing_type=sa.String(length=32),
        nullable=False,
    )

    op.create_check_constraint(
        "ck_crm_task_suggestions_clarification_pending_cause",
        "crm_task_suggestions",
        "('missing_required_field' = ANY(blocker_codes)) = "
        "(owner_clarification_pending OR task_details_clarification_pending)",
    )
    op.create_check_constraint(
        "ck_crm_task_suggestions_contact_resolution",
        "crm_task_suggestions",
        "(contact_resolution_state IN ('not_provided', 'explicit_none') AND "
        "contact_id IS NULL AND contact_resolution_hash IS NULL AND NOT "
        "('ambiguous_contact' = ANY(blocker_codes))) OR "
        "(contact_resolution_state = 'unresolved' AND contact_id IS NULL AND "
        "contact_resolution_hash IS NULL AND "
        "'ambiguous_contact' = ANY(blocker_codes)) OR "
        "(contact_resolution_state IN ('inferred_unique', 'clarified_unique') "
        "AND contact_id IS NOT NULL AND contact_resolution_hash ~ "
        "'^[0-9a-f]{64}$' AND NOT "
        "('ambiguous_contact' = ANY(blocker_codes)))",
    )


def _create_revision_83_write_compatibility() -> None:
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_compat_suggestion_overlay()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            repair_cause boolean := false;
            repair_contact boolean := false;
            compatible_core_update boolean := false;
            selected_email text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.owner_clarification_pending IS NULL AND
                   NEW.task_details_clarification_pending IS NULL AND
                   NEW.contact_resolution_state IS NULL THEN
                    NEW.owner_clarification_pending := false;
                    NEW.task_details_clarification_pending := false;
                    NEW.contact_resolution_state := 'not_provided';
                    repair_cause := (
                        'missing_required_field' = ANY(NEW.blocker_codes)
                    );
                    repair_contact := (
                        NEW.contact_id IS NOT NULL OR
                        'ambiguous_contact' = ANY(NEW.blocker_codes)
                    );
                ELSE
                    RETURN NEW;
                END IF;
            ELSE
                compatible_core_update := (
                    (NEW.blocker_codes IS DISTINCT FROM OLD.blocker_codes OR
                     NEW.contact_id IS DISTINCT FROM OLD.contact_id) AND
                    NEW.owner_clarification_pending IS NOT DISTINCT FROM
                        OLD.owner_clarification_pending AND
                    NEW.task_details_clarification_pending IS NOT DISTINCT FROM
                        OLD.task_details_clarification_pending AND
                    NEW.contact_resolution_state IS NOT DISTINCT FROM
                        OLD.contact_resolution_state AND
                    NEW.contact_resolution_hash IS NOT DISTINCT FROM
                        OLD.contact_resolution_hash
                );
                repair_cause := compatible_core_update AND (
                    ('missing_required_field' = ANY(NEW.blocker_codes)) <>
                    (NEW.owner_clarification_pending OR
                     NEW.task_details_clarification_pending)
                );
                repair_contact := compatible_core_update AND (
                    NEW.contact_id IS DISTINCT FROM OLD.contact_id OR NOT (
                        (NEW.contact_resolution_state IN
                            ('not_provided', 'explicit_none') AND
                         NEW.contact_id IS NULL AND
                         NEW.contact_resolution_hash IS NULL AND NOT
                         ('ambiguous_contact' = ANY(NEW.blocker_codes))) OR
                        (NEW.contact_resolution_state = 'unresolved' AND
                         NEW.contact_id IS NULL AND
                         NEW.contact_resolution_hash IS NULL AND
                         'ambiguous_contact' = ANY(NEW.blocker_codes)) OR
                        (NEW.contact_resolution_state IN
                            ('inferred_unique', 'clarified_unique') AND
                         NEW.contact_id IS NOT NULL AND
                         NEW.contact_resolution_hash ~ '^[0-9a-f]{64}$' AND NOT
                         ('ambiguous_contact' = ANY(NEW.blocker_codes)))
                    )
                );
            END IF;
            IF NOT repair_cause AND NOT repair_contact THEN
                RETURN NEW;
            END IF;

            IF repair_cause THEN
                IF 'missing_required_field' = ANY(NEW.blocker_codes) THEN
                    IF NOT (NEW.owner_clarification_pending OR
                            NEW.task_details_clarification_pending) THEN
                        NEW.task_details_clarification_pending := true;
                    END IF;
                ELSE
                    NEW.owner_clarification_pending := false;
                    NEW.task_details_clarification_pending := false;
                END IF;
            END IF;

            IF repair_contact THEN
                PERFORM pg_advisory_xact_lock(3892649629032444829);
                IF NEW.contact_id IS NOT NULL THEN
                    SELECT selected.normalized_email INTO selected_email
                    FROM crm_contacts AS selected
                    WHERE selected.id = NEW.contact_id
                      AND selected.email IS NOT NULL
                      AND selected.normalized_email IS NOT NULL
                      AND lower(btrim(selected.email)) =
                          selected.normalized_email
                      AND selected.normalized_email ~
                          '^[^[:space:]@]+@[^[:space:]@]+$'
                      AND 1 = (
                          SELECT count(*)
                          FROM crm_contacts AS candidate
                          WHERE candidate.normalized_email =
                              selected.normalized_email
                      );
                    IF selected_email IS NULL THEN
                        RAISE EXCEPTION 'contact_authority_invalid'
                            USING ERRCODE = '23514';
                    END IF;
                    NEW.contact_resolution_state := 'inferred_unique';
                    NEW.contact_resolution_hash := encode(
                        sha256(
                            convert_to(
                                'sws:crm-contact-resolution:v1', 'UTF8'
                            ) ||
                            decode('00', 'hex') ||
                            convert_to(NEW.contact_id::text, 'UTF8') ||
                            decode('00', 'hex') ||
                            convert_to(selected_email, 'UTF8')
                        ),
                        'hex'
                    );
                ELSIF 'ambiguous_contact' = ANY(NEW.blocker_codes) THEN
                    NEW.contact_resolution_state := 'unresolved';
                    NEW.contact_resolution_hash := NULL;
                ELSIF NEW.contact_resolution_state <> 'explicit_none' THEN
                    NEW.contact_resolution_state := 'not_provided';
                    NEW.contact_resolution_hash := NULL;
                END IF;
            END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_crm_task_suggestions_revision_83_compat BEFORE INSERT OR UPDATE ON crm_task_suggestions FOR EACH ROW EXECUTE FUNCTION sydney_task_review_compat_suggestion_overlay()"))
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_compat_obligation_overlay()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE evaluated_owner_ambiguous boolean;
        BEGIN
            IF NEW.evaluator_result_json IS JSON OBJECT WITH UNIQUE KEYS AND
               jsonb_typeof(NEW.evaluator_result_json::jsonb ->
                   'owner_ambiguous') = 'boolean' THEN
                evaluated_owner_ambiguous := (
                    NEW.evaluator_result_json::jsonb ->>
                    'owner_ambiguous'
                )::boolean;
                IF NEW.owner_ambiguous IS NULL THEN
                    NEW.owner_ambiguous := evaluated_owner_ambiguous;
                ELSIF NEW.owner_ambiguous <> evaluated_owner_ambiguous THEN
                    RAISE EXCEPTION 'obligation_owner_authority_invalid'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_gmail_extracted_obligations_revision_83_compat BEFORE INSERT ON gmail_extracted_obligations FOR EACH ROW EXECUTE FUNCTION sydney_task_review_compat_obligation_overlay()"))
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_sync_obligation_cause()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.reconciled_suggestion_id IS NOT NULL AND
               (NEW.owner_ambiguous OR NEW.taxonomy_fallback) THEN
                UPDATE crm_task_suggestions
                SET owner_clarification_pending =
                        owner_clarification_pending OR NEW.owner_ambiguous,
                    task_details_clarification_pending =
                        task_details_clarification_pending OR
                        NEW.taxonomy_fallback
                WHERE id = NEW.reconciled_suggestion_id
                  AND 'missing_required_field' = ANY(blocker_codes);
            END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_gmail_extracted_obligations_sync_task4_cause AFTER INSERT ON gmail_extracted_obligations FOR EACH ROW EXECUTE FUNCTION sydney_task_review_sync_obligation_cause()"))


def _create_contact_identity_serialization() -> None:
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_lock_contact_identity_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(3892649629032444829);
            RETURN NULL;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_crm_contacts_task_review_identity_insert_delete BEFORE INSERT OR DELETE ON crm_contacts FOR EACH STATEMENT EXECUTE FUNCTION sydney_task_review_lock_contact_identity_mutation()"))
    op.execute(sa.text("CREATE TRIGGER trg_crm_contacts_task_review_identity_update BEFORE UPDATE OF email, normalized_email ON crm_contacts FOR EACH STATEMENT EXECUTE FUNCTION sydney_task_review_lock_contact_identity_mutation()"))


def _create_tables() -> None:
    op.create_table(
        "crm_task_clarifications",
        _uuid_id(),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion_version", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("code_key_version", sa.Integer(), nullable=False),
        sa.Column("options_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("state", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("answer_json", sa.Text(), nullable=True),
        sa.Column("deadline_anchor_kind", sa.String(length=32), nullable=False),
        sa.Column("deadline_anchored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("suggestion_version > 0", name="ck_crm_task_clarifications_version_positive"),
        sa.CheckConstraint("round_number BETWEEN 1 AND 5", name="ck_crm_task_clarifications_round"),
        sa.CheckConstraint("field_name IN ('action_scope', 'contact', 'due_at', 'owner', 'task_details')", name="ck_crm_task_clarifications_field"),
        sa.CheckConstraint("state IN ('pending', 'answered', 'timed_out', 'superseded')", name="ck_crm_task_clarifications_state"),
        sa.CheckConstraint("octet_length(code_hash) = 32", name="ck_crm_task_clarifications_code_hash_length"),
        sa.CheckConstraint("code_key_version BETWEEN 1 AND 32767", name="ck_crm_task_clarifications_key_version"),
        sa.CheckConstraint("CASE WHEN telegram_chat_id ~ '^-?[1-9][0-9]*$' THEN telegram_chat_id::numeric > -4503599627370496 AND telegram_chat_id::numeric < 4503599627370496 ELSE false END", name="ck_crm_task_clarifications_chat_id"),
        sa.CheckConstraint("(state = 'pending' AND resolved_at IS NULL AND answer_json IS NULL) OR (state = 'answered' AND resolved_at IS NOT NULL AND answer_json IS NOT NULL) OR (state IN ('timed_out', 'superseded') AND resolved_at IS NOT NULL AND answer_json IS NULL)", name="ck_crm_task_clarifications_resolution_shape"),
        sa.CheckConstraint("options_json IS JSON OBJECT WITH UNIQUE KEYS AND octet_length(options_json) <= 4096", name="ck_crm_task_clarifications_options_json"),
        sa.CheckConstraint("answer_json IS NULL OR (answer_json IS JSON OBJECT WITH UNIQUE KEYS AND octet_length(answer_json) <= 8192)", name="ck_crm_task_clarifications_answer_json"),
        sa.CheckConstraint("slot_deadline_at = deadline_anchored_at + interval '48 hours' AND ((deadline_anchor_kind = 'created' AND first_attempt_at IS NULL AND deadline_anchored_at = created_at) OR (deadline_anchor_kind = 'first_attempt' AND first_attempt_at IS NOT NULL AND deadline_anchored_at = first_attempt_at) OR (deadline_anchor_kind = 'initial_sent' AND first_attempt_at IS NOT NULL AND deadline_anchored_at >= first_attempt_at))", name="ck_crm_task_clarifications_deadline"),
        sa.ForeignKeyConstraint(["suggestion_id"], ["crm_task_suggestions.id"], name="fk_crm_task_clarifications_suggestion_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("suggestion_id", "suggestion_version", "field_name", name="uq_crm_task_clarifications_suggestion_version_field"),
        sa.UniqueConstraint("suggestion_id", "round_number", name="uq_crm_task_clarifications_suggestion_round"),
        sa.UniqueConstraint("code_hash", name="uq_crm_task_clarifications_code_hash"),
    )
    op.create_index("uq_crm_task_clarifications_active_chat", "crm_task_clarifications", ["telegram_chat_id"], unique=True, postgresql_where=sa.text("state = 'pending'"))
    op.create_index("uq_crm_task_clarifications_active_suggestion", "crm_task_clarifications", ["suggestion_id"], unique=True, postgresql_where=sa.text("state = 'pending'"))
    op.create_index("ix_crm_task_clarifications_suggestion_field_state", "crm_task_clarifications", ["suggestion_id", "field_name", "state", "id"], unique=False)
    op.create_index("ix_crm_task_clarifications_due", "crm_task_clarifications", ["state", "slot_deadline_at", "id"], unique=False)

    op.create_table(
        "sydney_question_outbox",
        _uuid_id(),
        sa.Column("clarification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_kind", sa.String(length=32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("parent_initial_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reply_to_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("template_id", sa.String(length=64), nullable=False),
        sa.Column("question_context_json", sa.Text(), nullable=False),
        sa.Column("rendered_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=32), nullable=True),
        sa.Column("telegram_message_id", sa.String(length=32), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_outcome", sa.String(length=32), nullable=True),
        sa.Column("reconciliation_reason", sa.String(length=500), nullable=True),
        sa.Column("reconciliation_audit_id", sa.Integer(), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("attempt_kind IN ('initial', 'initial_retry', 'reminder')", name="ck_sydney_question_outbox_attempt_kind"),
        sa.CheckConstraint("attempt_number > 0", name="ck_sydney_question_outbox_attempt_number"),
        sa.CheckConstraint("template_id IN ('clarification_initial_v1', 'clarification_reminder_v1')", name="ck_sydney_question_outbox_template"),
        sa.CheckConstraint("(attempt_kind = 'reminder' AND template_id = 'clarification_reminder_v1') OR (attempt_kind IN ('initial', 'initial_retry') AND template_id = 'clarification_initial_v1')", name="ck_sydney_question_outbox_template_kind"),
        sa.CheckConstraint("question_context_json IS JSON OBJECT WITH UNIQUE KEYS AND octet_length(question_context_json) <= 4096", name="ck_sydney_question_outbox_context"),
        sa.CheckConstraint("state IN ('pending', 'sending', 'sent', 'failed', 'delivery_uncertain')", name="ck_sydney_question_outbox_state"),
        sa.CheckConstraint("(attempt_kind = 'initial' AND attempt_number = 1 AND parent_initial_attempt_id IS NULL AND reply_to_attempt_id IS NULL) OR (attempt_kind = 'initial_retry' AND attempt_number > 0 AND parent_initial_attempt_id IS NOT NULL AND reply_to_attempt_id IS NULL) OR (attempt_kind = 'reminder' AND attempt_number = 1 AND parent_initial_attempt_id IS NULL AND reply_to_attempt_id IS NOT NULL)", name="ck_sydney_question_outbox_attempt_parent_shape"),
        sa.CheckConstraint("rendered_payload_hash ~ '^[0-9a-f]{64}$'", name="ck_sydney_question_outbox_rendered_hash"),
        sa.CheckConstraint("telegram_chat_id IS NULL OR CASE WHEN telegram_chat_id ~ '^-?[1-9][0-9]*$' THEN telegram_chat_id::numeric > -4503599627370496 AND telegram_chat_id::numeric < 4503599627370496 ELSE false END", name="ck_sydney_question_outbox_chat_id"),
        sa.CheckConstraint("telegram_message_id IS NULL OR telegram_message_id ~ '^[1-9][0-9]*$'", name="ck_sydney_question_outbox_message_id"),
        sa.CheckConstraint("(state = 'pending' AND attempted_at IS NULL AND sent_at IS NULL AND telegram_chat_id IS NULL AND telegram_message_id IS NULL AND failure_category IS NULL) OR (state = 'sending' AND attempted_at IS NOT NULL AND sent_at IS NULL AND telegram_chat_id IS NOT NULL AND telegram_message_id IS NULL AND failure_category IS NULL) OR (state = 'sent' AND attempted_at IS NOT NULL AND sent_at IS NOT NULL AND telegram_chat_id IS NOT NULL AND telegram_message_id IS NOT NULL AND failure_category IS NULL) OR (state = 'failed' AND failure_category IN ('pre_send_resolved', 'pre_send_superseded', 'pre_send_expired') AND attempted_at IS NULL AND sent_at IS NULL AND telegram_chat_id IS NULL AND telegram_message_id IS NULL) OR (state IN ('failed', 'delivery_uncertain') AND attempted_at IS NOT NULL AND sent_at IS NULL AND telegram_chat_id IS NOT NULL AND failure_category IS NOT NULL AND (telegram_message_id IS NULL OR reconciled_outcome = 'delivered'))", name="ck_sydney_question_outbox_delivery_shape"),
        sa.CheckConstraint("(reconciled_outcome IS NULL AND reconciliation_reason IS NULL AND reconciliation_audit_id IS NULL AND reconciled_at IS NULL) OR (reconciliation_reason IS NOT NULL AND reconciliation_audit_id IS NOT NULL AND reconciled_at IS NOT NULL AND (((state = 'failed' AND reconciled_outcome = 'not_delivered') OR (state = 'delivery_uncertain' AND reconciled_outcome IN ('delivered', 'not_delivered'))) AND ((reconciled_outcome = 'delivered' AND telegram_chat_id IS NOT NULL AND telegram_message_id IS NOT NULL) OR (reconciled_outcome = 'not_delivered' AND telegram_message_id IS NULL))))", name="ck_sydney_question_outbox_reconciliation_shape"),
        sa.ForeignKeyConstraint(["clarification_id"], ["crm_task_clarifications.id"], name="fk_sydney_question_outbox_clarification_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_initial_attempt_id", "clarification_id"], ["sydney_question_outbox.id", "sydney_question_outbox.clarification_id"], name="fk_sydney_question_outbox_parent_initial", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reply_to_attempt_id", "clarification_id"], ["sydney_question_outbox.id", "sydney_question_outbox.clarification_id"], name="fk_sydney_question_outbox_reply_to", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reconciliation_audit_id"], ["agent_action_audits.id"], name="fk_sydney_question_outbox_reconciliation_audit", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_sydney_question_outbox_dedupe_key"),
        sa.UniqueConstraint("clarification_id", "attempt_kind", "attempt_number", name="uq_sydney_question_outbox_attempt"),
        sa.UniqueConstraint("id", "clarification_id", name="uq_sydney_question_outbox_id_clarification"),
    )
    op.create_index("ix_sydney_question_outbox_dispatch", "sydney_question_outbox", ["state", "created_at", "id"], unique=False)
    op.create_index("ix_sydney_question_outbox_delivery_correlation", "sydney_question_outbox", ["clarification_id", "state", "telegram_chat_id", "sent_at", "id"], unique=False)
    op.create_index("ix_sydney_question_outbox_reconciled_delivery", "sydney_question_outbox", ["clarification_id", "state", "reconciled_outcome", "telegram_chat_id", "reconciled_at", "id"], unique=False)
    op.create_index("ix_sydney_question_outbox_kind_history", "sydney_question_outbox", ["clarification_id", "attempt_kind", "state", "sent_at", "attempt_number", "id"], unique=False)

    op.create_table(
        "crm_task_suggestion_approval_nonces",
        _uuid_id(),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion_version", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("issuance_path", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("administrator_id", sa.Integer(), nullable=True),
        sa.Column("parent_nonce_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="ck_crm_task_suggestion_approval_nonces_token_hash"),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="ck_crm_task_suggestion_approval_nonces_payload_hash"),
        sa.CheckConstraint("(kind = 'handoff' AND issuance_path = 'approval_link' AND administrator_id IS NULL AND parent_nonce_id IS NULL AND expires_at = issued_at + interval '15 minutes') OR (kind = 'approval' AND issuance_path = 'handoff_exchange' AND administrator_id IS NOT NULL AND parent_nonce_id IS NOT NULL AND expires_at = issued_at + interval '5 minutes') OR (kind = 'approval' AND issuance_path = 'command_prepare' AND administrator_id IS NOT NULL AND parent_nonce_id IS NULL AND expires_at = issued_at + interval '5 minutes')", name="ck_crm_task_suggestion_approval_nonces_shape"),
        sa.CheckConstraint("consumed_at IS NULL OR (consumed_at >= issued_at AND consumed_at <= expires_at)", name="ck_crm_task_suggestion_approval_nonces_consumption"),
        sa.CheckConstraint("suggestion_version > 0", name="ck_crm_task_suggestion_approval_nonces_version"),
        sa.CheckConstraint("parent_nonce_id IS NULL OR parent_nonce_id <> id", name="ck_crm_task_suggestion_approval_nonces_not_self"),
        sa.ForeignKeyConstraint(["suggestion_id"], ["crm_task_suggestions.id"], name="fk_crm_task_suggestion_approval_nonces_suggestion_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["administrator_id"], ["admin_users.id"], name="fk_crm_task_suggestion_approval_nonces_administrator_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_nonce_id", "suggestion_id", "suggestion_version", "payload_hash"], ["crm_task_suggestion_approval_nonces.id", "crm_task_suggestion_approval_nonces.suggestion_id", "crm_task_suggestion_approval_nonces.suggestion_version", "crm_task_suggestion_approval_nonces.payload_hash"], name="fk_crm_task_suggestion_approval_nonces_parent_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_crm_task_suggestion_approval_nonces_token_hash"),
        sa.UniqueConstraint("parent_nonce_id", name="uq_crm_task_suggestion_approval_nonces_parent"),
        sa.UniqueConstraint("id", "suggestion_id", "suggestion_version", "payload_hash", name="uq_crm_task_suggestion_approval_nonces_resource_identity"),
    )

    op.create_table(
        "crm_task_suggestion_events",
        _uuid_id(),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=False),
        sa.Column("event_data_json", sa.Text(), nullable=False),
        sa.Column("action_audit_id", sa.Integer(), nullable=True),
        _now("created_at"),
        sa.CheckConstraint("suggestion_version > 0", name="ck_crm_task_suggestion_events_version"),
        sa.CheckConstraint("event_type IN ('edit', 'clarification_asked', 'clarification_answered', 'clarification_timed_out', 'clarification_superseded', 'clarification_delivery_retry', 'dismiss', 'preview', 'approve', 'apply', 'reprocess', 'dismiss_proposed')", name="ck_crm_task_suggestion_events_type"),
        sa.CheckConstraint("actor_type IN ('system', 'sydney', 'command_admin', 'untrusted_hermes_input')", name="ck_crm_task_suggestion_events_actor"),
        sa.CheckConstraint("event_data_json IS JSON OBJECT WITH UNIQUE KEYS AND octet_length(event_data_json) <= 8192", name="ck_crm_task_suggestion_events_data"),
        sa.ForeignKeyConstraint(["suggestion_id"], ["crm_task_suggestions.id"], name="fk_crm_task_suggestion_events_suggestion_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["action_audit_id"], ["agent_action_audits.id"], name="fk_crm_task_suggestion_events_action_audit_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_guards() -> None:
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_guard_clarification_identity()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.id IS DISTINCT FROM NEW.id OR OLD.suggestion_id IS DISTINCT FROM NEW.suggestion_id OR OLD.suggestion_version IS DISTINCT FROM NEW.suggestion_version OR OLD.field_name IS DISTINCT FROM NEW.field_name OR OLD.round_number IS DISTINCT FROM NEW.round_number OR OLD.telegram_chat_id IS DISTINCT FROM NEW.telegram_chat_id OR OLD.code_hash IS DISTINCT FROM NEW.code_hash OR OLD.code_key_version IS DISTINCT FROM NEW.code_key_version OR OLD.options_json IS DISTINCT FROM NEW.options_json OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION 'clarification_identity_immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.state <> 'pending' AND (OLD.state IS DISTINCT FROM NEW.state OR OLD.answer_json IS DISTINCT FROM NEW.answer_json OR OLD.resolved_at IS DISTINCT FROM NEW.resolved_at) THEN
                RAISE EXCEPTION 'clarification_resolution_immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.state = 'pending' AND NEW.state = 'timed_out' AND NEW.resolved_at < OLD.slot_deadline_at THEN
                RAISE EXCEPTION 'clarification_resolution_early' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_crm_task_clarifications_identity_immutable BEFORE UPDATE ON crm_task_clarifications FOR EACH ROW EXECUTE FUNCTION sydney_task_review_guard_clarification_identity()"))
    op.execute(sa.text("CREATE FUNCTION sydney_task_review_reject_clarification_delete() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'clarification_append_only' USING ERRCODE = '23514'; END; $$"))
    op.execute(sa.text("CREATE TRIGGER trg_crm_task_clarifications_no_delete BEFORE DELETE ON crm_task_clarifications FOR EACH ROW EXECUTE FUNCTION sydney_task_review_reject_clarification_delete()"))
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_guard_clarification_deadline()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.state <> 'pending' AND (OLD.deadline_anchor_kind IS DISTINCT FROM NEW.deadline_anchor_kind OR OLD.deadline_anchored_at IS DISTINCT FROM NEW.deadline_anchored_at OR OLD.slot_deadline_at IS DISTINCT FROM NEW.slot_deadline_at OR OLD.first_attempt_at IS DISTINCT FROM NEW.first_attempt_at) THEN
                RAISE EXCEPTION 'clarification_deadline_immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.deadline_anchor_kind = 'created' AND NEW.deadline_anchor_kind NOT IN ('created', 'first_attempt') THEN
                RAISE EXCEPTION 'clarification_deadline_invalid' USING ERRCODE = '23514';
            END IF;
            IF OLD.deadline_anchor_kind = 'first_attempt' AND NEW.deadline_anchor_kind NOT IN ('first_attempt', 'initial_sent') THEN
                RAISE EXCEPTION 'clarification_deadline_invalid' USING ERRCODE = '23514';
            END IF;
            IF OLD.deadline_anchor_kind = 'first_attempt' AND (
                OLD.first_attempt_at IS DISTINCT FROM NEW.first_attempt_at OR
                (
                    NEW.deadline_anchor_kind = 'first_attempt' AND (
                        OLD.deadline_anchored_at IS DISTINCT FROM NEW.deadline_anchored_at OR
                        OLD.slot_deadline_at IS DISTINCT FROM NEW.slot_deadline_at
                    )
                )
            ) THEN
                RAISE EXCEPTION 'clarification_deadline_immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.deadline_anchor_kind = 'initial_sent' AND (OLD.deadline_anchor_kind IS DISTINCT FROM NEW.deadline_anchor_kind OR OLD.deadline_anchored_at IS DISTINCT FROM NEW.deadline_anchored_at OR OLD.slot_deadline_at IS DISTINCT FROM NEW.slot_deadline_at OR OLD.first_attempt_at IS DISTINCT FROM NEW.first_attempt_at) THEN
                RAISE EXCEPTION 'clarification_deadline_immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_crm_task_clarifications_deadline_guard BEFORE UPDATE ON crm_task_clarifications FOR EACH ROW EXECUTE FUNCTION sydney_task_review_guard_clarification_deadline()"))

    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_guard_outbox_payload()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.id IS DISTINCT FROM NEW.id OR OLD.clarification_id IS DISTINCT FROM NEW.clarification_id OR OLD.attempt_kind IS DISTINCT FROM NEW.attempt_kind OR OLD.attempt_number IS DISTINCT FROM NEW.attempt_number OR OLD.parent_initial_attempt_id IS DISTINCT FROM NEW.parent_initial_attempt_id OR OLD.reply_to_attempt_id IS DISTINCT FROM NEW.reply_to_attempt_id OR OLD.dedupe_key IS DISTINCT FROM NEW.dedupe_key OR OLD.template_id IS DISTINCT FROM NEW.template_id OR OLD.question_context_json IS DISTINCT FROM NEW.question_context_json OR OLD.rendered_payload_hash IS DISTINCT FROM NEW.rendered_payload_hash OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION 'outbox_payload_immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_sydney_question_outbox_payload_immutable BEFORE UPDATE ON sydney_question_outbox FOR EACH ROW EXECUTE FUNCTION sydney_task_review_guard_outbox_payload()"))
    op.execute(sa.text("CREATE FUNCTION sydney_task_review_reject_outbox_delete() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'outbox_append_only' USING ERRCODE = '23514'; END; $$"))
    op.execute(sa.text("CREATE TRIGGER trg_sydney_question_outbox_no_delete BEFORE DELETE ON sydney_question_outbox FOR EACH ROW EXECUTE FUNCTION sydney_task_review_reject_outbox_delete()"))
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_guard_outbox_parent()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_row sydney_question_outbox%ROWTYPE;
        BEGIN
            IF NEW.attempt_kind = 'initial' THEN RETURN NEW; END IF;
            SELECT * INTO parent_row FROM sydney_question_outbox WHERE id = COALESCE(NEW.parent_initial_attempt_id, NEW.reply_to_attempt_id) AND clarification_id = NEW.clarification_id FOR KEY SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'outbox_parent_invalid' USING ERRCODE = '23514'; END IF;
            IF NEW.attempt_kind = 'initial_retry' AND NOT (
                parent_row.attempt_kind = 'initial' AND
                parent_row.state IN ('failed', 'delivery_uncertain') AND
                parent_row.reconciled_outcome IS NOT DISTINCT FROM 'not_delivered'
            ) THEN RAISE EXCEPTION 'outbox_parent_invalid' USING ERRCODE = '23514'; END IF;
            IF NEW.attempt_kind = 'reminder' AND NOT (parent_row.attempt_kind IN ('initial', 'initial_retry') AND (parent_row.state = 'sent' OR (parent_row.state = 'delivery_uncertain' AND parent_row.reconciled_outcome = 'delivered'))) THEN RAISE EXCEPTION 'outbox_parent_invalid' USING ERRCODE = '23514'; END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_sydney_question_outbox_parent_guard BEFORE INSERT ON sydney_question_outbox FOR EACH ROW EXECUTE FUNCTION sydney_task_review_guard_outbox_parent()"))
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_guard_outbox_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE clarification_state text; clarification_deadline timestamptz; clarification_resolved timestamptz;
        BEGIN
            IF OLD.state = 'pending' AND NEW.state = 'failed' AND NEW.attempted_at IS NULL THEN
                SELECT state, slot_deadline_at, resolved_at INTO clarification_state, clarification_deadline, clarification_resolved FROM crm_task_clarifications WHERE id = OLD.clarification_id FOR KEY SHARE;
                IF NOT ((NEW.failure_category = 'pre_send_resolved' AND clarification_state = 'answered') OR (NEW.failure_category = 'pre_send_superseded' AND clarification_state = 'superseded') OR (NEW.failure_category = 'pre_send_expired' AND clarification_state = 'timed_out' AND clarification_resolved >= clarification_deadline)) THEN RAISE EXCEPTION 'outbox_transition_invalid' USING ERRCODE = '23514'; END IF;
                RETURN NEW;
            END IF;
            IF OLD.state = 'pending' AND NEW.state <> 'sending' THEN RAISE EXCEPTION 'outbox_transition_invalid' USING ERRCODE = '23514'; END IF;
            IF OLD.state = 'sending' AND NEW.state NOT IN ('sent', 'failed', 'delivery_uncertain') THEN RAISE EXCEPTION 'outbox_transition_invalid' USING ERRCODE = '23514'; END IF;
            IF OLD.state IN ('sent', 'failed', 'delivery_uncertain') THEN
                IF OLD.state IS DISTINCT FROM NEW.state OR OLD.attempted_at IS DISTINCT FROM NEW.attempted_at OR OLD.sent_at IS DISTINCT FROM NEW.sent_at OR OLD.telegram_chat_id IS DISTINCT FROM NEW.telegram_chat_id OR (OLD.telegram_message_id IS DISTINCT FROM NEW.telegram_message_id AND NOT (OLD.state = 'delivery_uncertain' AND OLD.reconciled_outcome IS NULL AND NEW.reconciled_outcome = 'delivered' AND OLD.telegram_message_id IS NULL AND NEW.telegram_message_id IS NOT NULL)) OR OLD.failure_category IS DISTINCT FROM NEW.failure_category THEN RAISE EXCEPTION 'outbox_transition_immutable' USING ERRCODE = '23514'; END IF;
                IF OLD.reconciled_outcome IS NOT NULL AND (OLD.reconciled_outcome IS DISTINCT FROM NEW.reconciled_outcome OR OLD.reconciliation_reason IS DISTINCT FROM NEW.reconciliation_reason OR OLD.reconciliation_audit_id IS DISTINCT FROM NEW.reconciliation_audit_id OR OLD.reconciled_at IS DISTINCT FROM NEW.reconciled_at) THEN RAISE EXCEPTION 'outbox_reconciliation_immutable' USING ERRCODE = '23514'; END IF;
            END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_sydney_question_outbox_transition_guard BEFORE UPDATE ON sydney_question_outbox FOR EACH ROW EXECUTE FUNCTION sydney_task_review_guard_outbox_transition()"))

    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_guard_nonce_parent()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_row crm_task_suggestion_approval_nonces%ROWTYPE;
        BEGIN
            IF NEW.parent_nonce_id IS NULL THEN RETURN NEW; END IF;
            SELECT * INTO parent_row FROM crm_task_suggestion_approval_nonces WHERE id = NEW.parent_nonce_id FOR KEY SHARE;
            IF NOT FOUND OR parent_row.kind <> 'handoff' OR parent_row.issuance_path <> 'approval_link' OR parent_row.consumed_at IS NULL OR parent_row.consumed_at > NEW.issued_at OR parent_row.expires_at < NEW.issued_at THEN RAISE EXCEPTION 'nonce_parent_invalid' USING ERRCODE = '23514'; END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_crm_task_suggestion_approval_nonces_parent_guard BEFORE INSERT ON crm_task_suggestion_approval_nonces FOR EACH ROW EXECUTE FUNCTION sydney_task_review_guard_nonce_parent()"))
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_guard_nonce_identity()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR OLD.id IS DISTINCT FROM NEW.id OR OLD.suggestion_id IS DISTINCT FROM NEW.suggestion_id OR OLD.suggestion_version IS DISTINCT FROM NEW.suggestion_version OR OLD.payload_hash IS DISTINCT FROM NEW.payload_hash OR OLD.kind IS DISTINCT FROM NEW.kind OR OLD.issuance_path IS DISTINCT FROM NEW.issuance_path OR OLD.token_hash IS DISTINCT FROM NEW.token_hash OR OLD.administrator_id IS DISTINCT FROM NEW.administrator_id OR OLD.parent_nonce_id IS DISTINCT FROM NEW.parent_nonce_id OR OLD.issued_at IS DISTINCT FROM NEW.issued_at OR OLD.expires_at IS DISTINCT FROM NEW.expires_at THEN RAISE EXCEPTION 'nonce_identity_immutable' USING ERRCODE = '23514'; END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_crm_task_suggestion_approval_nonces_identity_immutable BEFORE UPDATE ON crm_task_suggestion_approval_nonces FOR EACH ROW EXECUTE FUNCTION sydney_task_review_guard_nonce_identity()"))
    op.execute(sa.text("CREATE TRIGGER trg_crm_task_suggestion_approval_nonces_no_delete BEFORE DELETE ON crm_task_suggestion_approval_nonces FOR EACH ROW EXECUTE FUNCTION sydney_task_review_guard_nonce_identity()"))
    op.execute(sa.text("""
        CREATE FUNCTION sydney_task_review_guard_nonce_consumption()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.consumed_at IS NOT NULL AND OLD.consumed_at IS DISTINCT FROM NEW.consumed_at THEN RAISE EXCEPTION 'nonce_consumption_immutable' USING ERRCODE = '23514'; END IF;
            RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_crm_task_suggestion_approval_nonces_one_time BEFORE UPDATE ON crm_task_suggestion_approval_nonces FOR EACH ROW EXECUTE FUNCTION sydney_task_review_guard_nonce_consumption()"))
    op.execute(sa.text("CREATE FUNCTION sydney_task_review_reject_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'event_append_only' USING ERRCODE = '23514'; END; $$"))
    op.execute(sa.text("CREATE TRIGGER trg_crm_task_suggestion_events_append_only BEFORE UPDATE OR DELETE ON crm_task_suggestion_events FOR EACH ROW EXECUTE FUNCTION sydney_task_review_reject_event_mutation()"))


def upgrade() -> None:
    _backfill_task4_authority()
    _create_revision_83_write_compatibility()
    _create_contact_identity_serialization()
    _create_tables()
    _create_guards()


def downgrade() -> None:
    op.execute(sa.text("LOCK TABLE " + ", ".join(_OWNED_TABLES) + " IN ACCESS EXCLUSIVE MODE"))
    predicates = " OR ".join(f"EXISTS (SELECT 1 FROM {table} LIMIT 1)" for table in _OWNED_TABLES)
    op.execute(sa.text("DO $$ BEGIN IF " + predicates + " THEN RAISE EXCEPTION 'revision 84 downgrade refused: Sydney task review evidence exists'; END IF; END $$;"))

    op.execute(sa.text("DROP TRIGGER trg_crm_task_suggestion_events_append_only ON crm_task_suggestion_events"))
    op.execute(sa.text("DROP TRIGGER trg_crm_task_suggestion_approval_nonces_one_time ON crm_task_suggestion_approval_nonces"))
    op.execute(sa.text("DROP TRIGGER trg_crm_task_suggestion_approval_nonces_no_delete ON crm_task_suggestion_approval_nonces"))
    op.execute(sa.text("DROP TRIGGER trg_crm_task_suggestion_approval_nonces_identity_immutable ON crm_task_suggestion_approval_nonces"))
    op.execute(sa.text("DROP TRIGGER trg_crm_task_suggestion_approval_nonces_parent_guard ON crm_task_suggestion_approval_nonces"))
    op.execute(sa.text("DROP TRIGGER trg_sydney_question_outbox_transition_guard ON sydney_question_outbox"))
    op.execute(sa.text("DROP TRIGGER trg_sydney_question_outbox_parent_guard ON sydney_question_outbox"))
    op.execute(sa.text("DROP TRIGGER trg_sydney_question_outbox_no_delete ON sydney_question_outbox"))
    op.execute(sa.text("DROP TRIGGER trg_sydney_question_outbox_payload_immutable ON sydney_question_outbox"))
    op.execute(sa.text("DROP TRIGGER trg_crm_task_clarifications_deadline_guard ON crm_task_clarifications"))
    op.execute(sa.text("DROP TRIGGER trg_crm_task_clarifications_no_delete ON crm_task_clarifications"))
    op.execute(sa.text("DROP TRIGGER trg_crm_task_clarifications_identity_immutable ON crm_task_clarifications"))
    op.drop_table("crm_task_suggestion_events")
    op.drop_table("crm_task_suggestion_approval_nonces")
    op.drop_index("ix_sydney_question_outbox_kind_history", table_name="sydney_question_outbox")
    op.drop_index("ix_sydney_question_outbox_reconciled_delivery", table_name="sydney_question_outbox")
    op.drop_index("ix_sydney_question_outbox_delivery_correlation", table_name="sydney_question_outbox")
    op.drop_index("ix_sydney_question_outbox_dispatch", table_name="sydney_question_outbox")
    op.drop_table("sydney_question_outbox")
    op.drop_index("ix_crm_task_clarifications_due", table_name="crm_task_clarifications")
    op.drop_index("ix_crm_task_clarifications_suggestion_field_state", table_name="crm_task_clarifications")
    op.drop_index("uq_crm_task_clarifications_active_suggestion", table_name="crm_task_clarifications")
    op.drop_index("uq_crm_task_clarifications_active_chat", table_name="crm_task_clarifications")
    op.drop_table("crm_task_clarifications")
    op.execute(sa.text("DROP TRIGGER trg_gmail_extracted_obligations_sync_task4_cause ON gmail_extracted_obligations"))
    op.execute(sa.text("DROP FUNCTION sydney_task_review_sync_obligation_cause()"))
    op.execute(sa.text("DROP TRIGGER trg_gmail_extracted_obligations_revision_83_compat ON gmail_extracted_obligations"))
    op.execute(sa.text("DROP FUNCTION sydney_task_review_compat_obligation_overlay()"))
    op.execute(sa.text("DROP TRIGGER trg_crm_task_suggestions_revision_83_compat ON crm_task_suggestions"))
    op.execute(sa.text("DROP FUNCTION sydney_task_review_compat_suggestion_overlay()"))
    op.execute(sa.text("DROP TRIGGER trg_crm_contacts_task_review_identity_update ON crm_contacts"))
    op.execute(sa.text("DROP TRIGGER trg_crm_contacts_task_review_identity_insert_delete ON crm_contacts"))
    op.execute(sa.text("DROP FUNCTION sydney_task_review_lock_contact_identity_mutation()"))
    op.drop_constraint("ck_crm_task_suggestions_contact_resolution", "crm_task_suggestions", type_="check")
    op.drop_constraint("ck_crm_task_suggestions_clarification_pending_cause", "crm_task_suggestions", type_="check")
    op.drop_column("crm_task_suggestions", "contact_resolution_hash")
    op.drop_column("crm_task_suggestions", "contact_resolution_state")
    op.drop_column("crm_task_suggestions", "task_details_clarification_pending")
    op.drop_column("crm_task_suggestions", "owner_clarification_pending")
    op.drop_index("ix_gmail_extracted_obligations_suggestion_owner_ambiguous", table_name="gmail_extracted_obligations")
    op.drop_column("gmail_extracted_obligations", "owner_ambiguous")
    for function in (
        "sydney_task_review_reject_event_mutation",
        "sydney_task_review_guard_nonce_consumption",
        "sydney_task_review_guard_nonce_identity",
        "sydney_task_review_guard_nonce_parent",
        "sydney_task_review_guard_outbox_transition",
        "sydney_task_review_guard_outbox_parent",
        "sydney_task_review_reject_outbox_delete",
        "sydney_task_review_guard_outbox_payload",
        "sydney_task_review_guard_clarification_deadline",
        "sydney_task_review_reject_clarification_delete",
        "sydney_task_review_guard_clarification_identity",
    ):
        op.execute(sa.text(f"DROP FUNCTION {function}()"))
