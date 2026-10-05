"""Files on disk without SUPABASE_SERVICE_KEY, in Supabase Storage with it (here a fake, nothing leaves the machine)."""
import hashlib

import httpx
import pytest

from api import storage


def test_on_disk_once_per_owner():
    sha = storage.save("anna", b"rapport")
    storage.save("anna", b"rapport")
    assert sha == hashlib.sha256(b"rapport").hexdigest()
    assert storage.read("anna", sha) == b"rapport"
    assert [p.name for p in (storage.DATA / "filer" / "anna").iterdir()] == [sha]
    storage.delete("anna", sha)
    assert not (storage.DATA / "filer" / "anna" / sha).exists()


@pytest.fixture
def supabase(monkeypatch):
    """A fake Storage: the requests are checked and the files kept in a dict."""
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_test")
    files = {}
    prefix = f"{storage.SUPABASE_URL}/storage/v1/object/filer/"

    def call(method):
        def handler(url, headers, content=None, timeout=None):
            assert url.startswith(prefix) and headers["apikey"] == "sb_secret_test"
            path = url.removeprefix(prefix)
            if method == "POST":
                assert headers["x-upsert"] == "true"
                files[path] = content
            elif method == "DELETE":
                files.pop(path, None)
            elif path not in files:
                return httpx.Response(404, request=httpx.Request(method, url))
            return httpx.Response(200, content=files.get(path, b""), request=httpx.Request(method, url))
        return handler

    for method in ("post", "get", "delete"):
        monkeypatch.setattr(httpx, method, call(method.upper()))
    return files


def test_in_supabase_under_the_owner(supabase):
    sha = storage.save("anna", b"rapport")
    assert list(supabase) == [f"anna/{sha}"]
    assert storage.read("anna", sha) == b"rapport"
    with pytest.raises(httpx.HTTPStatusError):
        storage.read("bertil", sha)  # Bertil's folder does not have it
    storage.delete("anna", sha)
    assert supabase == {}
    assert not (storage.DATA / "filer").exists()  # nothing on disk
