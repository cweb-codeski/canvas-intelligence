from unittest.mock import patch

from models import Course, SourceSnapshot

PARSE_RESULT = {
    "items": [
        {
            "item_type": "assignment",
            "title": "Homework 1",
            "subtype": "homework",
            "confidence": 0.95,
        }
    ],
    "metadata": {
        "course_id": "isolation-test-key",
        "source": "manual",
        "extraction_confidence": 0.95,
    },
}


@patch("main.parse", return_value=PARSE_RESULT)
def test_manual_syllabus_post_uses_isolated_db(mock_parse, client, db_session):
    course_key = "isolation-test-key"

    response = client.post(
        "/manual/syllabus",
        json={
            "course_key": course_key,
            "course_name": "Isolation Course",
            "text": "Homework 1 due Friday\n",
            "sync_to_notion": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["changed"] is True
    mock_parse.assert_called_once()

    course = db_session.query(Course).filter_by(canvas_course_id=course_key).one()
    snapshots = db_session.query(SourceSnapshot).filter_by(course_id=course.id).all()
    assert len(snapshots) == 1
    assert snapshots[0].source_type == "manual_text"
