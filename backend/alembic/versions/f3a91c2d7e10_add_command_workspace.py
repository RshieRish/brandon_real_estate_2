"""add command workspace

Revision ID: f3a91c2d7e10
Revises: e2f4a6b8c901
"""
from alembic import op
import sqlalchemy as sa

revision = "f3a91c2d7e10"
down_revision = "e2f4a6b8c901"
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now())]


def upgrade():
    op.create_table("crm_contacts", sa.Column("id", sa.Integer, primary_key=True), sa.Column("lead_id", sa.Integer, sa.ForeignKey("leads.id"), unique=True), sa.Column("first_name", sa.String(120), nullable=False), sa.Column("last_name", sa.String(120), server_default=""), sa.Column("email", sa.String(255)), sa.Column("phone", sa.String(50)), sa.Column("stage", sa.String(50), server_default="lead"), *_timestamps())
    op.create_table("crm_activities", sa.Column("id", sa.Integer, primary_key=True), sa.Column("contact_id", sa.Integer, sa.ForeignKey("crm_contacts.id")), sa.Column("kind", sa.String(50), nullable=False), sa.Column("summary", sa.Text, nullable=False), sa.Column("metadata", sa.Text, server_default="{}"), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("crm_tasks", sa.Column("id", sa.Integer, primary_key=True), sa.Column("contact_id", sa.Integer, sa.ForeignKey("crm_contacts.id")), sa.Column("title", sa.String(255), nullable=False), sa.Column("description", sa.Text, server_default=""), sa.Column("status", sa.String(32), server_default="open"), sa.Column("priority", sa.String(32), server_default="normal"), sa.Column("due_at", sa.DateTime(timezone=True)), *_timestamps())
    op.create_table("crm_notes", sa.Column("id", sa.Integer, primary_key=True), sa.Column("contact_id", sa.Integer, sa.ForeignKey("crm_contacts.id"), nullable=False), sa.Column("body", sa.Text, nullable=False), *_timestamps())
    op.create_table("crm_smart_plans", sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("description", sa.Text, server_default=""), sa.Column("status", sa.String(32), server_default="active"), *_timestamps())
    op.create_table("crm_smart_plan_steps", sa.Column("id", sa.Integer, primary_key=True), sa.Column("smart_plan_id", sa.Integer, sa.ForeignKey("crm_smart_plans.id"), nullable=False), sa.Column("position", sa.Integer, nullable=False), sa.Column("action_type", sa.String(50), nullable=False), sa.Column("payload", sa.Text, server_default="{}"))
    op.create_table("crm_smart_plan_enrollments", sa.Column("id", sa.Integer, primary_key=True), sa.Column("smart_plan_id", sa.Integer, sa.ForeignKey("crm_smart_plans.id"), nullable=False), sa.Column("contact_id", sa.Integer, sa.ForeignKey("crm_contacts.id"), nullable=False), sa.Column("status", sa.String(32), server_default="active"), *_timestamps())
    op.create_table("crm_opportunities", sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("stage", sa.String(50), server_default="cultivate"), sa.Column("value_cents", sa.Integer), *_timestamps())
    op.create_table("crm_listing_records", sa.Column("id", sa.Integer, primary_key=True), sa.Column("address", sa.String(500), nullable=False), sa.Column("latitude", sa.String(32)), sa.Column("longitude", sa.String(32)), sa.Column("status", sa.String(32), server_default="active"), *_timestamps())
    op.create_table("crm_agreement_templates", sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("body", sa.Text, server_default=""), *_timestamps())
    op.create_table("crm_agreements", sa.Column("id", sa.Integer, primary_key=True), sa.Column("template_id", sa.Integer, sa.ForeignKey("crm_agreement_templates.id")), sa.Column("contact_id", sa.Integer, sa.ForeignKey("crm_contacts.id")), sa.Column("title", sa.String(255), nullable=False), sa.Column("status", sa.String(32), server_default="draft"), *_timestamps())
    op.create_table("crm_agreement_events", sa.Column("id", sa.Integer, primary_key=True), sa.Column("agreement_id", sa.Integer, sa.ForeignKey("crm_agreements.id"), nullable=False), sa.Column("event_type", sa.String(50), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("crm_file_assets", sa.Column("id", sa.Integer, primary_key=True), sa.Column("filename", sa.String(500), nullable=False), sa.Column("storage_key", sa.String(500), nullable=False), sa.Column("content_type", sa.String(120), server_default="application/octet-stream"), *_timestamps())


def downgrade():
    for table in ("crm_file_assets", "crm_agreement_events", "crm_agreements", "crm_agreement_templates", "crm_listing_records", "crm_opportunities", "crm_smart_plan_enrollments", "crm_smart_plan_steps", "crm_smart_plans", "crm_notes", "crm_tasks", "crm_activities", "crm_contacts"):
        op.drop_table(table)
