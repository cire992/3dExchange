import pytest

from exchange.globs import glob_match
from exchange.scanner.tokenize import tokenize


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("Donut01_Pink", ["donut", "01", "pink"]),
        ("Barrel01_ORM", ["barrel", "01", "orm"]),
        ("HDTexture", ["hd", "texture"]),
        ("BaseColor", ["base", "color"]),
        ("Marius HD-8K", ["marius", "hd", "8", "k"]),
        ("SM_Chair_LOD0", ["sm", "chair", "lod", "0"]),
        ("Ébène_Table", ["ébène", "table"]),
        ("", []),
    ],
)
def test_tokenize(name, tokens):
    assert tokenize(name) == tokens


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("**/*.nif", "donut.nif", True),
        ("**/*.nif", "meshes/clutter/Donut.NIF", True),
        ("*.nif", "meshes/donut.nif", False),
        ("People/*/Clothing/**/*.duf", "people/Genesis 9/Clothing/Boots/Boots.duf", True),
        ("People/*/Clothing/**/*.duf", "People/Genesis 9/Hair/Bob.duf", False),
        ("downloads/**", "downloads/a/b.7z", True),
        ("data/**/Genesis 8*/**", "data/DAZ 3D/Genesis 8 Female/Morphs/x.dsf", True),
        ("file?.txt", "file1.txt", True),
        ("a+b.txt", "a+b.txt", True),
    ],
)
def test_glob_match(pattern, path, expected):
    assert glob_match(pattern, path) is expected
