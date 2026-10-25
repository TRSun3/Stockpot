"""Kitchen notes: one free-text note per account, kept as written and seen only by its owner."""


def test_notes_start_empty_are_kept_per_account_and_can_be_cleared(neal, tianyue):
    assert neal.get("/api/preferences").json() == {"notes": ""}
    assert neal.put("/api/preferences", json={"notes": "  No scallions.  "}).json() == {"notes": "No scallions."}
    assert neal.get("/api/preferences").json() == {"notes": "No scallions."}
    assert tianyue.get("/api/preferences").json() == {"notes": ""}
    assert neal.put("/api/preferences", json={"notes": ""}).json() == {"notes": ""}
    assert neal.get("/api/preferences").json() == {"notes": ""}


def test_notes_over_a_thousand_characters_are_refused(neal):
    response = neal.put("/api/preferences", json={"notes": "x" * 1001})
    assert response.status_code == 422
    assert neal.get("/api/preferences").json() == {"notes": ""}
