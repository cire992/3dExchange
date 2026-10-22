"""Requisitions in the window (Roadmap phase 4c): the Requisition to… dialog, presets and last-used
options, the queue view (with a real background run) and Settings › Pipelines and Endpoints."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from exchange.pipelines.registry import install, tool_paths, trust
from exchange.requisitions.presets import last_used, load_presets
from exchange_ui import main_window

from test_editing import action
from test_ui import select_brick

FIXTURES = Path(__file__).parent.parent / "fixtures" / "pipelines"


@pytest.fixture
def win(window):
    trust(install(FIXTURES / "stamp_images"))
    window.service.registry(reload=True)
    return window


def env_id(window, type_id):
    return next(e["id"] for e in window.service.environments() if e["type_id"] == type_id)


def uid_of(window, name):
    return window.service.connection_for_tests().execute("SELECT uid FROM dossier WHERE name = ?", (name,)).fetchone()[0]


def test_dialog_plans_options_presets_and_queues(win, monkeypatch, qtbot):
    barrel = uid_of(win, "Barrel01")
    dialog = win.open_requisition([barrel])
    qtbot.addWidget(dialog)
    dialog.set_environment(env_id(win, "loose_files"))
    routes = [dialog.route.itemData(i) for i in range(dialog.route.count())]
    assert "auto" in routes and ["copy_entry"] in routes and ["stamp_images"] in routes
    dialog.set_route(["stamp_images"])
    top = dialog.tree.topLevelItem(0)
    assert top.text(0) == "Barrel01" and top.text(1) == "Stamp images" and top.checkState(0) == Qt.CheckState.Checked
    assert set(k for p, k in dialog.editors if p == "stamp_images") == {"size", "review", "note"}
    assert "Exchange Conversions" in dialog.endpoint_label.text()

    # Options flow into the plan; a preset remembers them for every pipeline.
    dialog.set_option("stamp_images", "size", 7)
    dialog.set_option("stamp_images", "note", "from a preset")
    assert dialog.plans[0].items[0].params["stamp_images"]["size"] == 7
    monkeypatch.setattr(win, "ask_text", lambda *a, **k: "Tiny stamps")
    dialog.save_preset()
    assert load_presets()["Tiny stamps"].options["stamp_images"] == {"size": 7, "review": False, "note": "from a preset"}
    dialog.set_option("stamp_images", "size", 99)
    dialog.set_preset("Tiny stamps")
    assert dict((k, r()) for (p, k), (_, r) in dialog.editors.items())["size"] == 7

    # Queueing remembers the options as last used; the next dialog starts from them.
    ids = dialog.queue(run=False)
    assert len(ids) == 1 and last_used()["stamp_images"]["size"] == 7
    again = win.open_requisition([barrel])
    qtbot.addWidget(again)
    again.set_environment(env_id(win, "loose_files"))
    again.set_route(["stamp_images"])
    assert dict((k, r()) for (p, k), (_, r) in again.editors.items())["size"] == 7

    # Unchecking the only item leaves nothing to queue.
    again.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert not again.add_button.isEnabled()


def test_batch_and_the_inspector_button(win, qtbot):
    uids = [uid_of(win, "Barrel01"), uid_of(win, "Donut01_Pink")]
    dialog = win.open_requisition(uids)
    qtbot.addWidget(dialog)
    dialog.set_environment(env_id(win, "loose_files"))
    dialog.set_route(["copy_entry"])
    assert len(dialog.plans) == 2 and dialog.add_button.text() == "Add to queue (2)"
    assert len(dialog.queue(run=False)) == 2

    select_brick(win, "Barrel01")
    opened = []
    win.open_requisition = lambda u: opened.append(u)  # the button asks the window
    win.inspector.requisitionRequested.disconnect()
    win.inspector.requisitionRequested.connect(win.open_requisition)
    win.inspector.requisition.click()
    assert opened == [[uid_of(win, "Barrel01")]]


def test_context_menu_and_queue_view(win, qtbot, monkeypatch):
    index = select_brick(win, "Barrel01")
    assert action(win.build_context_menu(index), "Requisition to…").isEnabled()
    plan = win.service.plan(uid_of(win, "Barrel01"), env_id(win, "loose_files"), pipelines=["copy_entry"])
    [first] = win.service.queue([plan])
    plan = win.service.plan(uid_of(win, "Barrel01"), env_id(win, "loose_files"), pipelines=["stamp_images"],
                            params={"review": True})
    [second] = win.service.queue([plan])
    win.tree.setCurrentIndex(win._find_sidebar(("queue", "Requisitions")))
    panel = win.queue_panel
    assert win.stack.currentWidget() is panel and win.title.text() == "Requisitions"
    assert [r["id"] for r in panel.rows][:2] == [first, second]

    panel.select(second)
    panel._act("up")
    assert [r["id"] for r in panel.rows][:2] == [second, first]
    panel._act("hold")
    assert next(r for r in panel.rows if r["id"] == second)["state"] == "held"
    panel.select(second)
    panel._act("release")

    # A real run in the background: the stamp pauses at its checkpoint, the copy finishes.
    with qtbot.waitSignal(win.runner.finished, timeout=120_000):
        panel.run_button.click()
        assert not panel.run_button.isEnabled()
    states = {r["id"]: r["state"] for r in panel.rows}
    assert states == {second: "needs_attention", first: "fulfilled"}, panel.rows
    assert "Queue finished" in win.status.text()
    panel.select(second)
    assert "look at the shrunken images" in panel.items.item(0, 2).text()
    assert "waiting for you" in panel.log.toPlainText()
    panel._act("resume", None)
    assert next(r for r in panel.rows if r["id"] == second)["state"] == "queued"

    # Removing output runs in the background too.
    monkeypatch.setattr(win, "confirm", lambda *a: True)
    panel.select(first)
    win._on_queue_action("remove", first, None)
    qtbot.waitUntil(lambda: getattr(win, "queue_job", None) is None, timeout=120_000)
    assert next(r for r in win.service.requisitions() if r["id"] == first)["state"] == "removed"


def test_settings_pipelines_and_endpoints(window, monkeypatch, qtbot, tmp_path):
    dialog = window.open_settings()
    qtbot.addWidget(dialog)
    page = dialog.pipelines
    monkeypatch.setattr(window, "ask_folder", lambda *a: str(FIXTURES / "bridge_demo"))
    page._install()
    assert page.current_id() == "bridge_demo" and "not trusted" in page.list.currentItem().text()
    asked = []
    monkeypatch.setattr(window, "confirm", lambda title, text: asked.append(text) or True)
    page._trust("bridge_demo")
    assert "Runs: blender" in asked[0]
    assert window.service.registry().get("bridge_demo").trusted
    tool = tmp_path / "blender.exe"
    tool.write_bytes(b"MZ")
    monkeypatch.setattr(window, "ask_file", lambda *a: str(tool))
    page._set_tool("blender")
    assert tool_paths()["blender"] == str(tool) and "ready" in page.list.currentItem().text()

    endpoints = dialog.endpoints
    loose = env_id(window, "loose_files")
    monkeypatch.setattr(window, "ask_folder", lambda *a: str(tmp_path / "Out"))
    endpoints._choose(loose)
    config = next(e for e in window.service.environments() if e["id"] == loose)["user_config"]
    assert config["endpoint"] == str(tmp_path / "Out")
    endpoints.rows[loose][1].setCurrentText("publishable")
    assert next(e for e in window.service.environments() if e["id"] == loose)["user_config"]["visibility"] == "publishable"
    assert str(tmp_path / "Out") in endpoints.rows[loose][0].text()
