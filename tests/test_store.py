import os
from pathlib import Path


def test_store_create_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOPGEN_DATA_DIR", str(tmp_path))
    import loopgen.config as config
    import loopgen.store as storemod
    s = storemod.ProjectStore()
    p = s.create("demo", "source.mp4")
    assert Path(p["folder"]).exists()
    assert s.get(p["id"])["title"] == "demo"
    s.delete(p["id"])
    assert not Path(p["folder"]).exists()
