"""Add AI models registry table for dynamic model management.

Revision ID: 002_add_ai_models
Revises: 001_initial_schema
Create Date: 2026-01-26 10:00:00.000000

This migration introduces the `ai_models` table to support:
- Multi-provider AI integration (OpenAI, Claude, Llama, etc.)
- Dynamic model loading/unloading
- Performance & cost tracking per model
- Language and task capability metadata
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

# Revision identifiers
revision = '002_add_ai_models'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply forward migration: create ai_models table."""
    op.create_table(
        'ai_models',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, comment='Unique model ID'),
        sa.Column('name', sa.String(128), nullable=False, comment='Model name (e.g., gpt-4-turbo, whisper-large-v3)'),
        sa.Column('provider', sa.String(64), nullable=False, comment='AI provider (openai, anthropic, local, etc.)'),
        sa.Column('model_type', sa.String(32), nullable=False,
                  comment='Task type: transcription|translation|copywriting|editing|proofreading'),
        sa.Column('version', sa.String(32), nullable=True, comment='Model version or tag'),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False,
                  comment='Whether model is available for inference'),
        sa.Column('auto_load', sa.Boolean(), default=True, nullable=False,
                  comment='Load model into memory automatically'),
        sa.Column('supported_languages', ARRAY(sa.String(10)), nullable=True,
                  comment='ISO 639-1 codes, e.g., ["en", "ru", "zh"]'),
        sa.Column('accuracy_estimate', sa.Float(), nullable=True, comment='Estimated accuracy (0.0–1.0)'),
        sa.Column('avg_latency_ms', sa.Integer(), nullable=True, comment='Average inference latency in ms'),
        sa.Column('cost_per_unit', sa.Numeric(precision=10, scale=6), nullable=True,
                  comment='Cost per token/minute/unit'),
        sa.Column('config', JSONB(), nullable=False, server_default='{}',
                  comment='Provider-specific config (API keys excluded!)'),
        sa.Column('metadata', JSONB(), nullable=False, server_default='{}',
                  comment='Dynamic metadata: benchmarks, limits, quirks'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('now()'), nullable=True),

        # Indexes for performance
        sa.Index('idx_ai_models_provider_type', 'provider', 'model_type'),
        sa.Index('idx_ai_models_active', 'is_active'),
        sa.Index('idx_ai_models_name', 'name'),
    )

    # Optional: Insert default models if needed (e.g., for local Whisper)
    # op.bulk_insert(
    #     sa.table('ai_models',
    #         sa.column('name'), sa.column('provider'), sa.column('model_type'), sa.column('is_active')
    #     ),
    #     [
    #         {'name': 'whisper-large-v3', 'provider': 'local', 'model_type': 'transcription', 'is_active': True},
    #         {'name': 'llama-3-70b', 'provider': 'local', 'model_type': 'copywriting', 'is_active': False},
    #     ]
    # )


def downgrade() -> None:
    """Rollback: drop ai_models table."""
    op.drop_index('idx_ai_models_provider_type', table_name='ai_models')
    op.drop_index('idx_ai_models_active', table_name='ai_models')
    op.drop_index('idx_ai_models_name', table_name='ai_models')
    op.drop_table('ai_models')