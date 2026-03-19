import json
from datetime import datetime, timezone

from db import get_connection


class CampaignTracker:
    def record(
        self,
        campaign_id: str,
        step: str,
        input_snapshot: dict,
        output_snapshot: dict,
        prompt_template: str = "",
        model: str = "",
        input_hash: str = "",
        review_status: str = "",
        review_feedback: str = "",
    ):
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO campaign_steps
                    (campaign_id, step, input_snapshot, output_snapshot,
                     prompt_template, model, input_hash,
                     review_status, review_feedback, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    step,
                    json.dumps(input_snapshot, ensure_ascii=False),
                    json.dumps(output_snapshot, ensure_ascii=False),
                    prompt_template,
                    model,
                    input_hash,
                    review_status,
                    review_feedback,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
