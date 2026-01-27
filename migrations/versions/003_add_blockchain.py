"""Add blockchain transaction tracking table

Revision ID: 003_add_blockchain
Revises: 002_add_payment_audit
Create Date: 2026-01-26 10:00:00.000000

This migration introduces the 'blockchain_transactions' table to support:
- Immutable proof of work delivery
- Smart contract interaction logging
- Cross-platform payment verification via blockchain
- GDPR-compliant audit trail with cryptographic integrity

Ensures compatibility with core.security.advanced_crypto_system and services.blockchain_service.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# Revision identifiers
revision = '003_add_blockchain'
down_revision = '002_add_payment_audit'
branch_labels = None
depends_on = None


def upgrade():
    """Apply forward migration: create blockchain_transactions table"""
    # Create table only if not exists (idempotent)
    op.create_table(
        'blockchain_transactions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('job_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('client_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('platform', sa.String(64), nullable=False, index=True),
        sa.Column('transaction_hash', sa.String(256), nullable=False, unique=True),
        sa.Column('blockchain_network', sa.String(32), nullable=False, default='ethereum'),
        # e.g., 'ethereum', 'polygon', 'bitcoin'
        sa.Column('contract_address', sa.String(256), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, default='pending'),  # pending, confirmed, failed, reverted
        sa.Column('confirmations', sa.Integer(), nullable=False, default=0),
        sa.Column('required_confirmations', sa.Integer(), nullable=False, default=12),
        sa.Column('payload_hash', sa.String(256), nullable=True),  # SHA3-256 of delivered work
        sa.Column('metadata', JSONB, nullable=True),  # Arbitrary data: gas_used, block_number, etc.
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('now()'), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),

        # Constraints
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'failed', 'reverted')", name='valid_status'),
        sa.CheckConstraint("blockchain_network IN ('ethereum', 'polygon', 'bitcoin', 'solana', 'arbitrum', 'custom')",
                           name='valid_network'),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    )

    # Add composite index for performance
    op.create_index(
        'ix_blockchain_tx_job_platform',
        'blockchain_transactions',
        ['job_id', 'platform'],
        unique=False
    )

    # Optional: add GIN index for JSONB if needed later
    # op.create_index('ix_blockchain_metadata_gin', 'blockchain_transactions', ['metadata'], postgresql_using='gin')


def downgrade():
    """Rollback migration: drop blockchain_transactions table"""
    # Drop indexes first
    op.drop_index('ix_blockchain_tx_job_platform', table_name='blockchain_transactions')

    # Drop table
    op.drop_table('blockchain_transactions')