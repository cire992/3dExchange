import os

import pytest

from exchange.scanner.discovery import discover


def test_discovery_records_files_with_posix_relative_paths(daz_library):
    (daz_library / "Thumbs.db").write_bytes(b"clutter")
    (daz_library / ".git").mkdir()
    (daz_library / ".git" / "HEAD").write_text("ref")
    result = discover(daz_library)

    rels = [f.rel for f in result.files]
    assert "People/Genesis 9/Characters/Marius/Marius HD-8K.duf" in rels
    assert "Thumbs.db" not in rels
    assert not any(r.startswith(".git") for r in rels)
    assert all("\\" not in r for r in rels)
    assert rels == sorted(rels)
    boots = next(f for f in result.files if f.rel.endswith("Loose Boots.duf"))
    st = (daz_library / boots.rel).stat()
    assert (boots.size, boots.mtime_ns) == (st.st_size, st.st_mtime_ns)
    assert "Runtime/Support" in result.dirs


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_junctions_are_recorded_not_followed(tmp_path, daz_library):
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.glb").write_bytes(b"x")
    _winapi.CreateJunction(str(outside), str(daz_library / "linked"))

    result = discover(daz_library)
    assert result.links == ["linked"]
    assert not any("secret" in f.rel for f in result.files)


def test_symlinks_are_recorded_not_followed(tmp_path, loose_folder):
    target = tmp_path / "elsewhere.glb"
    target.write_bytes(b"x")
    try:
        os.symlink(target, loose_folder / "link.glb")
    except OSError:
        pytest.skip("creating symlinks needs Developer Mode or admin rights on Windows")
    result = discover(loose_folder)
    assert result.links == ["link.glb"]
    assert "link.glb" not in [f.rel for f in result.files]


def test_long_paths(tmp_path):
    from exchange.paths import os_path

    root = tmp_path / "long"
    deep = root
    for i in range(12):
        deep = deep / f"folder_with_a_rather_long_name_{i:02d}"
    os.makedirs(os_path(deep))
    with open(os_path(deep / "asset.glb"), "wb") as fh:
        fh.write(b"glb")
    assert len(str(deep / "asset.glb")) > 260

    result = discover(root)
    assert result.errors == []
    assert [f.rel.rsplit("/", 1)[-1] for f in result.files] == ["asset.glb"]
