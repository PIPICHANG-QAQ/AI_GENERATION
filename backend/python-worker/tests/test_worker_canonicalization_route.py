from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_canonicalization_preview_is_read_only():
    markdown = "1. 第一题\n参考答案与试题解析\n1. 第一题\n【解答】解析"
    answer_start = markdown.rindex("1. 第一题")
    task = {"id": "task-1", "paperOcrJobId": "ocr-1"}
    outputs = {
        "markdown": markdown,
        "questions": [
            {
                "id": "q_1",
                "number": 1,
                "stemMarkdown": "第一题",
                "sourceEvidence": {"start": 0, "end": markdown.index("参考答案")},
            },
            {
                "id": "q_1_2",
                "number": 1,
                "stemMarkdown": "第一题",
                "analysis": "解析",
                "sourceEvidence": {"start": answer_start, "end": len(markdown)},
            },
        ],
    }

    with patch("app.worker_routes.safe_read_job", return_value={"jobId": "ocr-1", "outputs": outputs}):
        with patch("app.worker_routes.load_image_placement_evidence", return_value=[]) as load_layout:
            with patch("app.worker_routes.write_store") as write_store:
                response = client.post(
                    "/worker/import-tasks/canonicalization/preview",
                    json={"task": task},
                )

    assert response.status_code == 200
    body = response.json()
    assert body["applyToken"]
    assert body["summary"] == {
        "beforeQuestionCount": 2,
        "afterQuestionCount": 1,
        "mergedQuestionCount": 1,
    }
    assert len(body["questions"]) == 1
    load_layout.assert_called_once()
    write_store.assert_not_called()
