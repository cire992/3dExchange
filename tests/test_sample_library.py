"""scripts/sample_library.py: a small library from a few real products, scanned like the real one."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from exchange.db import open_library

spec = importlib.util.spec_from_file_location(
    "sample_library", Path(__file__).parents[1] / "scripts" / "sample_library.py")
sample = importlib.util.module_from_spec(spec)
sys.modules["sample_library"] = sample
spec.loader.exec_module(sample)

MARIUS = "Marius HD-8K for Genesis 9"
DRESS = "Summer Dress for Genesis 8 Female"


def names(db_path):
    conn = open_library(db_path)
    found = {row[0] for row in conn.execute("SELECT name FROM dossier")}
    conn.close()
    return found


def snapshot(folder):
    return {p.relative_to(folder): p.stat().st_mtime_ns for p in folder.rglob("*")}


def test_a_sample_scans_as_the_products_it_holds(daz_library, tmp_path, scan, db_path, capsys):
    before = snapshot(daz_library)
    dest = tmp_path / "sample"
    assert sample.main([str(daz_library), str(dest), "--product", "Marius"]) == 0
    assert "1 products" in capsys.readouterr().out
    assert [p.name for p in (dest / "Runtime" / "Support").glob("*.dsx")] == \
        ["DAZ_3D_12345_Marius_HD-8K_for_Genesis_9.dsx"]
    scan(dest)
    found = names(db_path)
    assert MARIUS in found and DRESS not in found
    assert snapshot(daz_library) == before  # the source is only read


def test_list_names_the_products_without_copying(daz_library, tmp_path, capsys):
    dest = tmp_path / "sample"
    assert sample.main([str(daz_library), str(dest), "--list", "genesis"]) == 0
    out = capsys.readouterr().out
    assert MARIUS in out and DRESS in out
    assert not dest.exists()


def test_a_name_must_mean_one_product(daz_library):
    products = sample.read_products(daz_library)
    assert [p.name for p in sample.choose(products, [MARIUS.lower()])] == [MARIUS]
    with pytest.raises(sample.SampleError, match="matches 2 products"):
        sample.choose(products, ["genesis"])
    with pytest.raises(sample.SampleError, match="matches 0 products"):
        sample.choose(products, ["no such product"])


def test_random_picks_repeat_with_the_seed(daz_library):
    products = sample.read_products(daz_library)
    assert sample.choose(products, [], 1, seed=3) == sample.choose(products, [], 1, seed=3)
    assert len(sample.choose(products, [DRESS], 99)) == len(products)
    assert sample.choose(products, [], 1, keep=lambda p: p.name == DRESS)[0].name == DRESS


def test_random_skips_products_whose_files_moved(daz_library, tmp_path, capsys):
    products = sample.read_products(daz_library)
    marius = next(p for p in products if p.name == MARIUS)
    (daz_library / marius.files[0]).unlink()
    assert not sample.whole(daz_library, marius)
    assert sample.main([str(daz_library), str(tmp_path / "sample"), "--product", "Marius", "--dry-run"]) == 0
    assert f"of {len(marius.files)} files  {MARIUS}" in capsys.readouterr().out
    assert sample.main([str(daz_library), str(tmp_path / "sample"), "--random", "9", "--dry-run"]) == 0
    assert MARIUS not in capsys.readouterr().out


def test_files_no_manifest_lists_come_by_pattern(daz_library, tmp_path, capsys):
    saved = daz_library / "People" / "Saved"
    saved.mkdir(parents=True)
    (saved / "My Character.duf").write_text("{}", encoding="utf-8")
    dest = tmp_path / "sample"
    assert sample.main([str(daz_library), str(dest), "--file", "People/Saved/*.duf"]) == 0
    assert (dest / "People" / "Saved" / "My Character.duf").is_file()
    assert sample.main([str(daz_library), str(dest), "--file", "People/None/*.duf"]) == 2
    assert "nothing in" in capsys.readouterr().err


def test_a_sample_inside_the_source_is_refused(daz_library, capsys):
    assert sample.main([str(daz_library), str(daz_library / "sample"), "--product", "Marius"]) == 2
    assert "inside" in capsys.readouterr().err
    assert not (daz_library / "sample").exists()


def test_the_size_limit_and_dry_run_copy_nothing(daz_library, tmp_path, capsys):
    dest = tmp_path / "sample"
    assert sample.main([str(daz_library), str(dest), "--random", "2", "--max-gb", "0"]) == 2
    assert "over the limit" in capsys.readouterr().err
    assert sample.main([str(daz_library), str(dest), "--product", "Marius", "--dry-run"]) == 0
    assert "Would copy" in capsys.readouterr().out
    assert not dest.exists()


def test_copying_again_skips_what_is_there(daz_library, tmp_path, capsys):
    dest = tmp_path / "sample"
    assert sample.main([str(daz_library), str(dest), "--product", "Marius"]) == 0
    first = capsys.readouterr().out
    assert sample.main([str(daz_library), str(dest), "--product", "Marius"]) == 0
    assert "(0 copied" in capsys.readouterr().out and "(0 copied" not in first


def test_a_listed_file_that_is_gone_is_counted_not_fatal(daz_library, tmp_path, capsys):
    products = sample.read_products(daz_library)
    marius = next(p for p in products if p.name == MARIUS)
    shutil.rmtree((daz_library / marius.files[0]).parent, ignore_errors=True)
    assert sample.main([str(daz_library), str(tmp_path / "sample"), "--product", "Marius"]) == 0
    assert "listed files missing" in capsys.readouterr().out
