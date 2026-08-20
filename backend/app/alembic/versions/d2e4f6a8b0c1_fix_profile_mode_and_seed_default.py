"""Fix metric profile mode storage and seed the single-turn default.

Revision ID: d2e4f6a8b0c1
Revises: c8f1a2b3d4e5
"""

import sqlalchemy as sa
from alembic import op

revision = "d2e4f6a8b0c1"
down_revision = "c8f1a2b3d4e5"
branch_labels = None
depends_on = None

DEFAULT_PROFILE_ID = "25d9e375-431f-4a08-9658-483fab711a61"


def upgrade() -> None:
    # SQLAlchemy Enum historically persisted member names. Normalize both
    # representations before constraining this VARCHAR column to enum values.
    op.execute(
        sa.text("""
        UPDATE evaluationmetricprofile
        SET evaluation_mode = CASE evaluation_mode
          WHEN 'SINGLE_TURN' THEN 'single_turn'
          WHEN 'MULTI_TURN' THEN 'multi_turn'
          ELSE lower(evaluation_mode)
        END
        """)
    )
    op.create_check_constraint(
        "ck_metric_profile_evaluation_mode",
        "evaluationmetricprofile",
        "evaluation_mode IN ('single_turn', 'multi_turn')",
    )

    # Seed only a database that has no active single-turn profile. The CTE
    # ensures profile items are added only when this migration inserted it.
    op.execute(
        sa.text(f"""
        WITH inserted AS (
          INSERT INTO evaluationmetricprofile
            (id, name, description, is_active, version, evaluation_mode,
             created_at, updated_at)
          SELECT
            '{DEFAULT_PROFILE_ID}'::uuid,
            '기본 단일턴 품질 프로필',
            '정확성 50%, 답변 관련성 30%, 전문성 20%',
            true,
            1,
            'single_turn',
            now(),
            now()
          WHERE NOT EXISTS (
            SELECT 1 FROM evaluationmetricprofile
            WHERE is_active = true AND evaluation_mode = 'single_turn'
          )
          RETURNING id
        )
        INSERT INTO evaluationmetricprofileitem
          (id, profile_id, position, key, display_name, criteria,
           weight_percent, evaluation_params, config, custom_instruction)
        SELECT seed.id::uuid, inserted.id, seed.position, seed.key,
               seed.display_name, seed.criteria, seed.weight_percent,
               seed.evaluation_params::json, '{{}}'::json, NULL
        FROM inserted
        CROSS JOIN (VALUES
          ('89c80bd6-6ad0-44ad-8ad0-d34c0a459607', 0,
           'geval_correctness', '정확성 (G-Eval)',
           '실제 응답이 기대 응답과 사실적·의미적으로 일치하는지 평가합니다.',
           50, '["actual_output", "expected_output"]'),
          ('a040377d-4ad0-4fa2-8742-60a9842bd077', 1,
           'answer_relevancy', '답변 관련성',
           '실제 응답의 진술이 사용자 입력과 관련되는 비율을 평가합니다.',
           30, '["input", "actual_output"]'),
          ('e5c37b0e-96a1-4526-ae86-fe9ded68cbaf', 2,
           'geval_professionalism', '전문성 (G-Eval)',
           '실제 응답이 전문적이고 존중하는 어조를 유지하는지 평가합니다.',
           20, '["actual_output"]')
        ) AS seed(id, position, key, display_name, criteria, weight_percent,
                  evaluation_params)
        """)
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_metric_profile_evaluation_mode",
        "evaluationmetricprofile",
        type_="check",
    )
    # The seeded profile is an ordinary editable/deletable profile. Downgrade
    # therefore preserves it rather than deleting potentially modified data.
