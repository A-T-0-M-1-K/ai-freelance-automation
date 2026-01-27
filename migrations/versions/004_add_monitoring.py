"""Add comprehensive monitoring system tables

Revision ID: 004_add_monitoring
Revises: 003_add_payment_system
Create Date: 2026-01-26 10:00:00.000000

This migration introduces the core tables for the Intelligent Monitoring System,
which collects 100+ real-time metrics across system, business, AI, and client dimensions.
Supports anomaly detection, predictive analytics, and automated reporting.

Tables added:
- system_metrics
- business_metrics
- ai_performance_metrics
- monitoring_alerts
- metric_series (for time-series aggregation)

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime

# Revision identifiers
revision = '004_add_monitoring'
down_revision = '003_add_payment_system'
branch_labels = None
depends_on = None


def upgrade():
    # Create enum types if not exists (PostgreSQL-specific)
    op.execute("CREATE TYPE metric_category AS ENUM ('system', 'business', 'ai', 'client');")
    op.execute("CREATE TYPE alert_severity AS ENUM ('low', 'medium', 'high', 'critical');")

    # 1. system_metrics — CPU, RAM, disk, network, uptime, etc.
    op.create_table(
        'system_metrics',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, default=datetime.utcnow),
        sa.Column('component', sa.String(128), nullable=False, index=True),
        sa.Column('cpu_usage_percent', sa.Float, nullable=True),
        sa.Column('memory_usage_mb', sa.Float, nullable=True),
        sa.Column('disk_usage_percent', sa.Float, nullable=True),
        sa.Column('network_io_kbps', sa.Float, nullable=True),
        sa.Column('uptime_seconds', sa.Integer, nullable=True),
        sa.Column('active_jobs_count', sa.Integer, nullable=False, default=0),
        sa.Column('error_count_5min', sa.Integer, nullable=False, default=0),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Index('idx_system_metrics_ts', 'timestamp'),
        sa.Index('idx_system_metrics_component', 'component'),
    )

    # 2. business_metrics — orders, revenue, conversion, client retention
    op.create_table(
        'business_metrics',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, default=datetime.utcnow),
        sa.Column('metric_name', sa.String(128), nullable=False, index=True),
        sa.Column('value', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('currency', sa.String(3), nullable=True, default='USD'),
        sa.Column('platform', sa.String(64), nullable=True),
        sa.Column('client_id', UUID(as_uuid=True), nullable=True),
        sa.Column('job_id', UUID(as_uuid=True), nullable=True),
        sa.Column('tags', sa.ARRAY(sa.String), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Index('idx_business_metrics_name_ts', 'metric_name', 'timestamp'),
        sa.Index('idx_business_metrics_client', 'client_id'),
    )

    # 3. ai_performance_metrics — model accuracy, latency, quality scores
    op.create_table(
        'ai_performance_metrics',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, default=datetime.utcnow),
        sa.Column('model_name', sa.String(128), nullable=False, index=True),
        sa.Column('task_type', sa.String(64), nullable=False),  # e.g., 'transcription', 'translation'
        sa.Column('latency_ms', sa.Integer, nullable=False),
        sa.Column('accuracy_score', sa.Float, nullable=True),  # 0.0 - 1.0
        sa.Column('quality_rating', sa.Float, nullable=True),  # client-rated or auto-rated
        sa.Column('input_tokens', sa.Integer, nullable=True),
        sa.Column('output_tokens', sa.Integer, nullable=True),
        sa.Column('error_code', sa.String(32), nullable=True),
        sa.Column('job_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Index('idx_ai_metrics_model_ts', 'model_name', 'timestamp'),
        sa.Index('idx_ai_metrics_task', 'task_type'),
    )

    # 4. monitoring_alerts — anomalies, failures, predictions
    op.create_table(
        'monitoring_alerts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, default=datetime.utcnow),
        sa.Column('category', sa.Enum('system', 'business', 'ai', 'client', name='metric_category'), nullable=False),
        sa.Column('severity', sa.Enum('low', 'medium', 'high', 'critical', name='alert_severity'), nullable=False),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('source_component', sa.String(128), nullable=True),
        sa.Column('related_job_id', UUID(as_uuid=True), nullable=True),
        sa.Column('auto_resolved', sa.Boolean, nullable=False, default=False),
        sa.Column('resolution_action', sa.Text, nullable=True),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Index('idx_alerts_severity_ts', 'severity', 'timestamp'),
        sa.Index('idx_alerts_auto_resolved', 'auto_resolved'),
    )

    # 5. metric_series — aggregated time-series for dashboards & analytics
    op.create_table(
        'metric_series',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('series_key', sa.String(256), nullable=False, index=True),  # e.g., "system.cpu.avg.5m"
        sa.Column('bucket_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('bucket_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('avg_value', sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column('min_value', sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column('max_value', sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column('count', sa.Integer, nullable=False, default=0),
        sa.Column('last_value', sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column('tags', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('series_key', 'bucket_start', name='uq_series_bucket'),
        sa.Index('idx_metric_series_key_time', 'series_key', 'bucket_start'),
    )

    # Add foreign key constraints (optional, can be deferred for performance)
    op.create_foreign_key(
        'fk_alerts_job', 'monitoring_alerts', 'jobs',
        ['related_job_id'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_ai_metrics_job', 'ai_performance_metrics', 'jobs',
        ['job_id'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_business_metrics_job', 'business_metrics', 'jobs',
        ['job_id'], ['id'], ondelete='SET NULL'
    )


def downgrade():
    # Drop foreign keys first
    op.drop_constraint('fk_alerts_job', 'monitoring_alerts', type_='foreignkey')
    op.drop_constraint('fk_ai_metrics_job', 'ai_performance_metrics', type_='foreignkey')
    op.drop_constraint('fk_business_metrics_job', 'business_metrics', type_='foreignkey')

    # Drop tables
    op.drop_table('metric_series')
    op.drop_table('monitoring_alerts')
    op.drop_table('ai_performance_metrics')
    op.drop_table('business_metrics')
    op.drop_table('system_metrics')

    # Drop enums
    op.execute("DROP TYPE IF EXISTS alert_severity;")
    op.execute("DROP TYPE IF EXISTS metric_category;")