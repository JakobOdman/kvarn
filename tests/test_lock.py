"""A locked template can't be changed or deleted until it is unlocked."""
from tests.conftest import TEMPLATE, add_read_document


def test_a_locked_template_cant_be_changed_or_deleted(anna):
    template = anna.put("/templates", json=TEMPLATE).json()
    assert anna.patch(f"/templates/{template['id']}", json={"locked": True}).json()["locked"] is True

    changed = anna.put("/templates", json=template | {"prompt": "Något annat."})
    assert changed.status_code == 409 and changed.json()["detail"] == "Mallen är låst. Lås upp den för att ändra den."
    assert anna.delete(f"/templates/{template['id']}").status_code == 409
    assert anna.get(f"/templates/{template['id']}").json()["prompt"] == "Hitta bolagen."


def test_unlocked_it_can_be_changed_again(anna):
    template = anna.put("/templates", json=TEMPLATE).json()
    anna.patch(f"/templates/{template['id']}", json={"locked": True})
    assert anna.patch(f"/templates/{template['id']}", json={"locked": False}).json()["locked"] is False
    assert anna.put("/templates", json=template | {"prompt": "Något annat."}).status_code == 200
    assert anna.delete(f"/templates/{template['id']}").status_code == 200


def test_locking_is_not_a_change_of_the_template(anna):
    """The folder's live extraction does not say that its template has changed."""
    template = anna.put("/templates", json=TEMPLATE).json()["id"]
    folder = anna.post("/folders", json={"name": "Fonder"}).json()["id"]
    add_read_document(folder)
    anna.patch(f"/folders/{folder}", json={"template_id": template, "auto_extract": True})
    anna.patch(f"/templates/{template}", json={"locked": True})
    [live] = anna.get("/extractions").json()
    assert live["live"] and live["template_changed"] is False


def test_unknown_template_is_404(anna):
    assert anna.patch("/templates/finns-inte", json={"locked": True}).status_code == 404


def test_saving_can_lock_it_at_the_same_time(anna):
    """Spara och lås: the changes and the lock in one save."""
    template = anna.put("/templates", json=TEMPLATE).json()
    saved = anna.put("/templates", json=template | {"prompt": "Klar.", "locked": True}).json()
    assert (saved["prompt"], saved["locked"]) == ("Klar.", True)
    assert anna.put("/templates", json=saved | {"prompt": "Igen."}).status_code == 409
