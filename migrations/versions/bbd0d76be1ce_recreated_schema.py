"""Recreated schema

Revision ID: bbd0d76be1ce
Revises: 79adedfd2b34
Create Date: 2025-06-23 13:47:16.553048

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bbd0d76be1ce'
down_revision = '79adedfd2b34'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('api_key',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('company',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('referral_code', sa.String(length=50), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('referral_code')
    )
    op.create_table('postback_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tracking_id', sa.String(length=100), nullable=False),
    sa.Column('transaction_id', sa.String(length=100), nullable=True),
    sa.Column('username', sa.String(length=100), nullable=True),
    sa.Column('user_id', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=True),
    sa.Column('payout', sa.Float(), nullable=True),
    sa.Column('response_json', sa.Text(), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('ip_address', sa.String(length=50), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=512), nullable=True),
    sa.Column('is_admin', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('form',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('is_closed', sa.Boolean(), nullable=True),
    sa.Column('requires_consent', sa.Boolean(), nullable=True),
    sa.Column('is_quiz', sa.Boolean(), nullable=True),
    sa.Column('passing_score', sa.Integer(), nullable=True),
    sa.Column('show_score', sa.Boolean(), nullable=True),
    sa.Column('merged_url', sa.String(length=255), nullable=True),
    sa.Column('external_url', sa.String(length=500), nullable=True),
    sa.Column('is_external', sa.Boolean(), nullable=True),
    sa.Column('external_webhook_secret', sa.String(length=100), nullable=True),
    sa.Column('allowed_countries', sa.Text(), nullable=True),
    sa.Column('blocked_countries', sa.Text(), nullable=True),
    sa.Column('offer_name', sa.String(length=255), nullable=True),
    sa.Column('offer_description', sa.Text(), nullable=True),
    sa.Column('offer_status', sa.String(length=50), nullable=True),
    sa.Column('offer_credit', sa.Float(), nullable=True),
    sa.Column('offer_preview_url', sa.String(length=500), nullable=True),
    sa.Column('offer_country', sa.String(length=255), nullable=True),
    sa.Column('offer_date', sa.Date(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name='fk_form_company'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_form_user'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_webhook_secret')
    )
    op.create_table('form_template',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('questions', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=True),
    sa.Column('preview_image', sa.String(length=255), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('template_data', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('postback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('postback_tester_job',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('url_template', sa.Text(), nullable=False),
    sa.Column('interval', sa.Integer(), nullable=False),
    sa.Column('duration', sa.Integer(), nullable=False),
    sa.Column('parameters', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('form_view',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('form_id', sa.Integer(), nullable=False),
    sa.Column('viewed_at', sa.DateTime(), nullable=True),
    sa.Column('ip_address', sa.String(length=50), nullable=True),
    sa.Column('session_id', sa.String(length=100), nullable=True),
    sa.ForeignKeyConstraint(['form_id'], ['form.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('pdf_upload',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('form_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['form_id'], ['form.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('postback_tester_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=True),
    sa.Column('response_code', sa.Integer(), nullable=True),
    sa.Column('response_text', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['job_id'], ['postback_tester_job.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('postback_tracking',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('form_id', sa.Integer(), nullable=False),
    sa.Column('tracking_id', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('last_updated', sa.DateTime(), nullable=True),
    sa.Column('transaction_count', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['form_id'], ['form.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tracking_id')
    )
    op.create_table('question',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('form_id', sa.Integer(), nullable=False),
    sa.Column('question_text', sa.String(length=500), nullable=False),
    sa.Column('question_type', sa.String(length=20), nullable=False),
    sa.Column('options', sa.Text(), nullable=True),
    sa.Column('required', sa.Boolean(), nullable=True),
    sa.Column('order', sa.Integer(), nullable=False),
    sa.Column('is_quiz_question', sa.Boolean(), nullable=True),
    sa.Column('correct_answer', sa.Text(), nullable=True),
    sa.Column('points', sa.Integer(), nullable=True),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['form_id'], ['form.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('response',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('form_id', sa.Integer(), nullable=False),
    sa.Column('submitted_at', sa.DateTime(), nullable=True),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.String(length=100), nullable=True),
    sa.Column('company_name', sa.String(length=200), nullable=True),
    sa.Column('utm_source', sa.String(length=100), nullable=True),
    sa.Column('utm_medium', sa.String(length=100), nullable=True),
    sa.Column('utm_campaign', sa.String(length=100), nullable=True),
    sa.Column('utm_content', sa.String(length=100), nullable=True),
    sa.Column('utm_term', sa.String(length=100), nullable=True),
    sa.Column('device_type', sa.String(length=20), nullable=True),
    sa.Column('has_consent', sa.Boolean(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('max_score', sa.Integer(), nullable=True),
    sa.Column('passed', sa.Boolean(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=True),
    sa.Column('session_id', sa.String(length=100), nullable=True),
    sa.Column('complete_id', sa.String(length=100), nullable=True),
    sa.Column('browser', sa.Text(), nullable=True),
    sa.Column('date_time_clicked', sa.String(length=50), nullable=True),
    sa.Column('date_time_completed', sa.String(length=50), nullable=True),
    sa.Column('time_spent', sa.String(length=50), nullable=True),
    sa.Column('time_per_question', sa.Text(), nullable=True),
    sa.Column('is_suspicious', sa.Boolean(), nullable=True),
    sa.Column('actual_ip', sa.String(length=50), nullable=True),
    sa.Column('session_ip', sa.String(length=50), nullable=True),
    sa.Column('conversion_ip', sa.String(length=50), nullable=True),
    sa.Column('is_rejected', sa.Boolean(), nullable=True),
    sa.Column('sub1', sa.String(length=100), nullable=True),
    sa.Column('sts', sa.String(length=100), nullable=True),
    sa.Column('form_score', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name='fk_response_company'),
    sa.ForeignKeyConstraint(['form_id'], ['form.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('answer',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('response_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('answer_text', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], ),
    sa.ForeignKeyConstraint(['response_id'], ['response.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('geolocation',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('response_id', sa.Integer(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('region', sa.String(length=100), nullable=True),
    sa.Column('country', sa.String(length=100), nullable=True),
    sa.Column('ip_address', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['response_id'], ['response.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sub_question',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('parent_option', sa.String(length=255), nullable=False),
    sa.Column('question_text', sa.String(length=500), nullable=False),
    sa.Column('question_type', sa.String(length=20), nullable=False),
    sa.Column('options', sa.Text(), nullable=True),
    sa.Column('required', sa.Boolean(), nullable=True),
    sa.Column('order', sa.Integer(), nullable=False),
    sa.Column('nesting_level', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sub_question_answer',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('response_id', sa.Integer(), nullable=False),
    sa.Column('subquestion_id', sa.Integer(), nullable=False),
    sa.Column('selected_option', sa.String(length=255), nullable=True),
    sa.Column('answer_text', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['response_id'], ['response.id'], ),
    sa.ForeignKeyConstraint(['subquestion_id'], ['sub_question.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('sub_question_answer')
    op.drop_table('sub_question')
    op.drop_table('geolocation')
    op.drop_table('answer')
    op.drop_table('response')
    op.drop_table('question')
    op.drop_table('postback_tracking')
    op.drop_table('postback_tester_log')
    op.drop_table('pdf_upload')
    op.drop_table('form_view')
    op.drop_table('postback_tester_job')
    op.drop_table('postback')
    op.drop_table('form_template')
    op.drop_table('form')
    op.drop_table('user')
    op.drop_table('postback_log')
    op.drop_table('company')
    op.drop_table('api_key')
    # ### end Alembic commands ###
