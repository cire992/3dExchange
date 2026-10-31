"""R5a: a requisition says where its steps keep their files, for a client to show a paused step."""

import pytest

pytest.importorskip("fastapi")

from exchange.requisitions.runner import work_dir  # noqa: E402
from test_service_requisitions import V1, finish, installed, ok, setup  # noqa: E402,F401  (the fixture)


def queue(setup, review):
    request = {"uids": [setup["barrel"]], "environment": setup["env"], "processes": ["stamp_images"],
               "options": {"stamp_images": {"review": review}}}
    return ok(setup["client"].post(f"{V1}/requisitions/queue", json=request))["ids"][0]


def test_a_paused_requisition_shows_its_work_folder_until_it_is_done(setup):
    client = setup["client"]
    installed(client)
    rid = queue(setup, True)
    assert ok(client.get(f"{V1}/requisitions/{rid}"))["work_folder"] is None  # queued: nothing there yet

    finish(client, ok(client.post(f"{V1}/jobs/requisitions", json={"ids": [rid]})))
    waiting = ok(client.get(f"{V1}/requisitions/{rid}"))
    assert waiting["state"] == "needs_attention"
    assert waiting["work_folder"] == str(work_dir(waiting["uid"])) and work_dir(waiting["uid"]).is_dir()

    ok(client.post(f"{V1}/requisitions/{rid}/resume", json={"on_collision": "overwrite"}))
    finish(client, ok(client.post(f"{V1}/jobs/requisitions", json={})))
    done = ok(client.get(f"{V1}/requisitions/{rid}"))
    assert done["state"] == "fulfilled" and done["work_folder"] is None
