"""The add-environment wizard, driven end to end against fake environments."""

import pytest

from builders import copy_fixture, unreal_project
from exchange.autodiscover import Places
from exchange.db import repository as repo
from exchange.environments import excluded_roots
from exchange_ui.service import LibraryService
from exchange_ui.wizard import mo2_profiles


@pytest.fixture
def setup(qtbot, tmp_path, definitions):
    from exchange_ui.app import make_app
    from exchange_ui.main_window import MainWindow

    assets = tmp_path / "scan" / "Assets"
    copy_fixture("fake_daz_library", assets / "DAZ Library")
    unreal_project(assets / "UE" / "Kitbash")
    copy_fixture("loose_files", assets / "props")
    local = tmp_path / "Local"
    copy_fixture("fake_mo2", local / "ModOrganizer" / "Skyrim SE")
    starfield = copy_fixture("fake_mo2", local / "ModOrganizer" / "Starfield")
    (starfield / "profiles" / "Testing").mkdir()
    (starfield / "ModOrganizer.ini").write_text("[General]\ngameName=Starfield\n")

    make_app([])
    service = LibraryService(tmp_path / "lib" / "library.db", definitions)
    window = MainWindow(service)
    qtbot.addWidget(window)
    dialog = window.add_environment(Places(local_appdata=local, registry=lambda key: {}))
    qtbot.waitUntil(lambda: bool(dialog.sources.found), timeout=10_000)
    yield window, dialog, assets, service
    service.close()


def detect(qtbot, dialog, assets):
    dialog.sources.add_folder(assets)
    assert dialog.primary.isEnabled()
    dialog._primary()
    qtbot.waitUntil(lambda: not dialog.review.busy, timeout=60_000)


def test_sources_step(setup):
    _, dialog, assets, _ = setup
    names = [f.name for f in dialog.sources.found]
    assert names == ["Skyrim SE (Skyrim Special Edition)", "Starfield (Starfield)"]
    assert dialog.sources.summary() == "2 found environments + 0 folders selected"
    dialog.sources.add_folder(assets)
    dialog.sources.add_folder(assets)  # added once
    assert dialog.sources.summary() == "2 found environments + 1 folder selected"


def test_review_step_detects_and_splits(qtbot, setup):
    _, dialog, assets, _ = setup
    detect(qtbot, dialog, assets)
    found = {c.type_id: c for c in dialog.review.candidates}
    assert set(found) == {"loose_files", "daz_studio", "unreal_project"}
    assert found["daz_studio"].files == 16 and found["daz_studio"].confidence == 1.0
    assert "5 environments to add" in dialog.summary.text()


def test_full_flow(qtbot, setup):
    window, dialog, assets, service = setup
    detect(qtbot, dialog, assets)
    rows = {c.type_id: c for c in dialog.review.candidates}
    rows["unreal_project"].selected = False  # not wanted: excluded from now on
    rows["loose_files"].type_id = "loose_files"
    dialog._primary()
    plans = {p.name: p for p in dialog.configure.plans}
    assert set(plans) == {"Loose files (Assets)", "Daz Studio", "Skyrim Special Edition (Skyrim SE)",
                          "Mod Organizer 2 instance (Starfield)"}

    # Starfield has two profiles and none selected: it must be chosen first.
    assert not dialog.primary.isEnabled()
    assert "needs a profile" in dialog.summary.text()
    index = list(plans).index("Mod Organizer 2 instance (Starfield)")
    form = dialog.configure.forms[index]
    form.profile.setCurrentIndex(form.profile.findData("Testing"))
    form.name.setText("Starfield")
    form.ignore.setPlainText("*.bak\n\nBodySlide/**\n")
    skyrim = dialog.configure.forms[list(plans).index("Skyrim Special Edition (Skyrim SE)")]
    assert skyrim.profile.currentData() == "Default"  # the instance's selected profile
    assert dialog.primary.isEnabled()

    with qtbot.waitSignal(window.runner.finished, timeout=180_000):
        dialog._primary()
    assert dialog.primary.text() == "Done"
    statuses = [row.status.text() for row in dialog.scan_page.rows]
    assert all(s.startswith("Done") for s in statuses), statuses
    assert "products found so far" in dialog.summary.text()

    conn = service.connection_for_tests()
    envs = {e["name"]: e for e in repo.list_environments(conn)}
    assert set(envs) == {"Loose files (Assets)", "Daz Studio", "Skyrim Special Edition (Skyrim SE)", "Starfield"}
    starfield = envs["Starfield"]
    assert repo.user_config(conn, starfield["id"]) == {
        "mo2_profile": "Testing", "visibility": "personal", "ignore": ["*.bak", "BodySlide/**"],
        "endpoint": {"mode": "new_container", "value": "Exchange – {dossier}"}}
    assert excluded_roots(conn) == [str(assets / "UE" / "Kitbash")]
    assert conn.execute("SELECT count(*) FROM file WHERE rel_path LIKE 'UE/%'").fetchone()[0] == 0

    review = []
    dialog.reviewUnidentified.connect(lambda: review.append(True))
    dialog._secondary()
    assert review and window.unidentified_button.isChecked()


def test_changed_type_is_kept(qtbot, setup):
    window, dialog, assets, service = setup
    for box, _ in dialog.sources.found_boxes:
        box.setChecked(False)
    detect(qtbot, dialog, assets)
    for c in dialog.review.candidates:
        c.selected = c.type_id == "loose_files"
        if c.selected:
            c.type_id = "mo2_generic"
    dialog._primary()
    assert [p.type_id for p in dialog.configure.plans] == ["mo2_generic"]
    dialog.configure.forms[0].profile.setCurrentIndex(0)
    assert not dialog.primary.isEnabled()  # an MO2 environment without profiles needs one


def test_busy_runner_blocks_adding(qtbot, setup, loose_folder):
    window, dialog, assets, _ = setup
    for box, _ in dialog.sources.found_boxes:
        box.setChecked(False)
    detect(qtbot, dialog, assets)
    dialog._primary()
    with qtbot.waitSignal(window.runner.finished, timeout=120_000):
        window.scan_folder(loose_folder)
        dialog._update()
        assert not dialog.primary.isEnabled()
        assert "Another scan is running" in dialog.summary.text()
    assert dialog.primary.isEnabled()


def test_mo2_profiles(tmp_path):
    root = copy_fixture("fake_mo2", tmp_path / "mo2")
    (root / "profiles" / "Alt").mkdir()
    assert mo2_profiles(str(root)) == (["Alt", "Default"], "Default")
    assert mo2_profiles(str(tmp_path)) == ([], None)


def test_empty_sources(qtbot, tmp_path, definitions):
    from exchange_ui.app import make_app
    from exchange_ui.main_window import MainWindow

    make_app([])
    service = LibraryService(tmp_path / "lib" / "library.db", definitions)
    window = MainWindow(service)
    qtbot.addWidget(window)
    dialog = window.add_environment(Places())
    qtbot.wait(200)
    assert not dialog.primary.isEnabled()
    dialog._secondary()  # Cancel
    assert not dialog.isVisible()
    service.close()
