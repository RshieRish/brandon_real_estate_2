"""add blogs table

Revision ID: a1b2c3d4e5f6
Revises: c7648221316c
Create Date: 2026-05-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, TEXT

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'c7648221316c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.create_table(
        'blogs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('title', sa.Text, nullable=False),
        sa.Column('slug', sa.Text, nullable=False, unique=True),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('excerpt', sa.Text, nullable=True),
        sa.Column('image_url', sa.Text, nullable=True),
        sa.Column('category', sa.Text, nullable=True),
        sa.Column('tags', ARRAY(TEXT), nullable=True),
        sa.Column('author', sa.Text, server_default='Stephanie Mitchell'),
        sa.Column('author_role', sa.Text, server_default='Real Estate Content Director'),
        sa.Column('author_bio', sa.Text, nullable=True),
        sa.Column('author_image_url', sa.Text, nullable=True),
        sa.Column('is_posted', sa.Boolean, server_default=sa.text('FALSE'), nullable=False),
        sa.Column('featured', sa.Boolean, server_default=sa.text('FALSE'), nullable=False),
        sa.Column('read_time_mins', sa.Integer, nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_blogs_slug', 'blogs', ['slug'], unique=True)
    op.create_index('idx_blogs_is_posted', 'blogs', ['is_posted'])
    op.create_index('idx_blogs_created_at', 'blogs', ['created_at'])


def downgrade() -> None:
    op.drop_index('idx_blogs_created_at', table_name='blogs')
    op.drop_index('idx_blogs_is_posted', table_name='blogs')
    op.drop_index('idx_blogs_slug', table_name='blogs')
    op.drop_table('blogs')
