"""R4d: what can go wrong as a walk queues its requisition: the claim file, and remembering the options."""

import pytest

pytest.importorskip("fastapi")

from exchange import claims  # noqa: E402
from exchange.requisitions import presets  # noqa: E402
from test_claim_paths import world  # noqa: E402,F401  (the fixture)
from test_service_claim_walk import barrel, rows, use, walk  # noqa: E402
from test_service_claims import V1, api, ok  # noqa: E402,F401  (the fixture)


def refuse(src, dst):
    raise OSError("refused")


def test_a_claim_that_cant_be_recorded_queues_nothing(api, monkeypatch):
    use(api, "stamp_images")
    claim, before = barrel(api), rows(api)
    with monkeypatch.context() as patch:
        patch.setattr(claims.os, "replace", refuse)
        response = walk(api, claim)
    assert response.status_code == 409 and "nothing was queued" in response.json()["detail"]
    assert rows(api) == before
    assert rows(api, "SELECT count(*) FROM requisition_item") == 0

    walked = ok(walk(api, claim))  # the retry is the first and only requisition
    assert rows(api) == before + 1
    assert [r["id"] for r in ok(api["client"].get(f"{V1}/claims/{claim['id']}"))["requisitions"]] == \
        [walked["requisition"]["id"]]


def test_the_cli_is_told_the_same(world, monkeypatch):
    from test_claim_paths import registry_with

    registry = registry_with("stamp_images")
    claim = claims.new(world["conn"], world["barrel"], world["envs"]["loose_files"]["id"])
    monkeypatch.setattr(claims.os, "replace", refuse)
    with pytest.raises(claims.ClaimError, match="nothing was queued"):
        claims.walk(world["conn"], world["definitions"], registry, claim.id)
    assert world["conn"].execute("SELECT count(*) FROM requisition").fetchone()[0] == 0


def test_a_failed_remember_keeps_what_was_remembered(api, monkeypatch):
    presets.remember({"stamp_images": {"size": 64}})
    with monkeypatch.context() as patch:
        patch.setattr(presets.os, "replace", refuse)
        presets.remember({"stamp_images": {"size": 128}})
    assert presets.last_used() == {"stamp_images": {"size": 64}}
    assert [p.name for p in presets._last_file().parent.glob("last_options*")] == ["last_options.json"]


def test_a_value_that_cant_be_written_keeps_the_rest(api):
    presets.remember({"stamp_images": {"size": 64}, "other": {"a": 1}})
    presets.remember({"stamp_images": {"label": "\ud800"}})  # a lone surrogate has no UTF-8
    assert presets.last_used() == {"stamp_images": {"size": 64}, "other": {"a": 1}}
    assert [p.name for p in presets._last_file().parent.glob("last_options*")] == ["last_options.json"]


def test_a_walk_outlives_a_failed_remember(api):
    use(api, "stamp_images")
    claim = barrel(api)
    presets._last_file().mkdir(parents=True)  # nothing can be moved over a folder
    walked = ok(walk(api, claim))
    assert walked["problem"] is None and walked["requisition"]["state"] == "queued"
    assert walked["requisition"]["uid"] in (claims.claims_dir() / f"{claim['id']}.md").read_text(encoding="utf-8")
