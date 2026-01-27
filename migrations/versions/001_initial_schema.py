"""Initial database schema for AI Freelance Automation System.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-01-26 00:00:00.000000

This migration creates the foundational tables required for:
- Autonomous job processing
- Client & project management
- Secure payment handling
- AI task execution
- Audit logging & compliance (GDPR, PCI DSS)
- Self-healing & monitoring metadata

All timestamps are in UTC.
All sensitive data is marked for encryption at application layer.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import text

# Revision identifiers
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # --- Helper: UUID with default gen ---
    uuid_gen = text("gen_random_uuid()")

    # ==============================
    # 1. SECURITY & IDENTITY
    # ==============================

    # Users (internal system identities, e.g., AI agents, admin)
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=uuid_gen),
        sa.Column('username', sa.String(128), unique=True, nullable=False),
        sa.Column('hashed_password', sa.String(256), nullable=False),  # Argon2 hash
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('role', sa.String(32), nullable=False),  # 'ai_agent', 'admin', 'system'
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('now()')),
    )
    op.create_index('ix_users_username', 'users', ['username'])

    # API Keys (for platform integrations)
    op.create_table(
        'api_keys',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=uuid_gen),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform_name', sa.String(64), nullable=False),  # e.g., 'upwork', 'fiverr'
        sa.Column('encrypted_key', sa.Text, nullable=False),  # Encrypted via AdvancedCryptoSystem
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('last_used', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_api_keys_user_platform', 'api_keys', ['user_id', 'platform_name'])

    # ==============================
    # 2. CLIENTS & PROJECTS
    # ==============================

    op.create_table(
        'clients',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=uuid_gen),
        sa.Column('external_id', sa.String(128), nullable=True),  # Platform-specific client ID
        sa.Column('platform', sa.String(64), nullable=False),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('email', sa.String(256), nullable=True),
        sa.Column('rating', sa.Float, nullable=True),
        sa.Column('total_spent', sa.Numeric(15, 2), default=0.00),
        sa.Column('is_trusted', sa.Boolean, default=False),
        sa.Column('risk_score', sa.Float, default=0.0),  # From RiskAnalyzer
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('last_contact_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_clients_external_platform', 'clients', ['external_id', 'platform'])
    op.create_index('ix_clients_risk_score', 'clients', ['risk_score'])

    op.create_table(
        'projects',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=uuid_gen),
        sa.Column('external_job_id', sa.String(128), unique=True, nullable=False),
        sa.Column('platform', sa.String(64), nullable=False),
        sa.Column('client_id', UUID(as_uuid=True), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.Text, nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('budget_min', sa.Numeric(12, 2)),
        sa.Column('budget_max', sa.Numeric(12, 2)),
        sa.Column('currency', sa.String(3), default='USD'),
        sa.Column('deadline', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(32), default='discovered'),  # discovered, bidding, active, delivered, paid, closed
        sa.Column('assigned_ai_agent_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('metadata', JSONB, default={}),  # Raw platform data, tags, etc.
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('now()')),
    )
    op.create_index('ix_projects_status', 'projects', ['status'])
    op.create_index('ix_projects_deadline', 'projects', ['deadline'])
    op.create_index('ix_projects_platform', 'projects', ['platform'])

    # ==============================
    # 3. TASKS & AI EXECUTION
    # ==============================

    op.create_table(
        'tasks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=uuid_gen),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_type', sa.String(32), nullable=False),  # 'transcription', 'translation', 'copywriting', etc.
        sa.Column('input_data_ref', sa.Text, nullable=False),  # Encrypted S3/GCS path or blob ref
        sa.Column('output_data_ref', sa.Text, nullable=True),
        sa.Column('status', sa.String(32), default='pending'),  # pending, processing, completed, failed, reviewed
        sa.Column('ai_model_used', sa.String(128), nullable=True),
        sa.Column('quality_score', sa.Float, nullable=True),
        sa.Column('retries', sa.Integer, default=0),
        sa.Column('max_retries', sa.Integer, default=3),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('error_log', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_tasks_status', 'tasks', ['status'])
    op.create_index('ix_tasks_project_id', 'tasks', ['project_id'])

    # ==============================
    # 4. COMMUNICATION & MESSAGES
    # ==============================

    op.create_table(
        'messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=uuid_gen),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('direction', sa.String(16), nullable=False),  # 'incoming', 'outgoing'
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('sentiment_score', sa.Float, nullable=True),  # From SentimentAnalyzer
        sa.Column('platform_message_id', sa.String(128), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True)),
        sa.Column('read_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_messages_project_id', 'messages', ['project_id'])
    op.create_index('ix_messages_created_at', 'messages', ['created_at'])

    # ==============================
    # 5. PAYMENTS & FINANCES
    # ==============================

    op.create_table(
        'invoices',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=uuid_gen),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD'),
        sa.Column('status', sa.String(32), default='issued'),  # issued, paid, overdue, disputed
        sa.Column('payment_provider', sa.String(64), nullable=True),
        sa.Column('transaction_id', sa.String(256), nullable=True),
        sa.Column('due_date', sa.DateTime(timezone=True)),
        sa.Column('paid_at', sa.DateTime(timezone=True)),
        sa.Column('tax_amount', sa.Numeric(12, 2), default=0.00),
        sa.Column('metadata', JSONB, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_invoices_status', 'invoices', ['status'])
    op.create_index('ix_invoices_project_id', 'invoices', ['project_id'])

    # ==============================
    # 6. AUDIT & MONITORING
    # ==============================

    op.create_table(
        'audit_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=uuid_gen),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('source', sa.String(64), nullable=False),  # e.g., 'decision_engine', 'payment_orchestrator'
        sa.Column('severity', sa.String(16), nullable=False),  # info, warning, error, critical
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('context', JSONB, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_audit_logs_event_type', 'audit_logs', ['event_type'])
    op.create_index('ix_audit_logs_severity', 'audit_logs', ['severity'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])

    op.create_table(
        'system_health',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=uuid_gen),
        sa.Column('component', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),  # healthy, degraded, failed
        sa.Column('metrics', JSONB, default={}),
        sa.Column('last_check', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_system_health_component', 'system_health', ['component'])


def downgrade():
    """Reverse the initial schema creation."""
    tables = [
        'system_health',
        'audit_logs',
        'invoices',
        'messages',
        'tasks',
        'projects',
        'clients',
        'api_keys',
        'users',
    ]
    for table in tables:
        op.drop_table(table)