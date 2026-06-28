import types
import pytest
from core import rag_client


class _Resp:
    def __init__(self, status, payload, ctype="application/json"):
        self.status_code = status; self._p = payload
        self.headers = {"content-type": ctype}
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400:
            raise rag_client.requests.exceptions.HTTPError("http %s" % self.status_code)


def test_ask_success(monkeypatch):
    monkeypatch.setattr(rag_client.requests, "post",
                        lambda *a, **k: _Resp(200, {"answer": "ok", "sources": []}))
    assert rag_client.ask("http://x", "q")["answer"] == "ok"


def test_ask_connection_error(monkeypatch):
    def boom(*a, **k): raise rag_client.requests.exceptions.ConnectionError()
    monkeypatch.setattr(rag_client.requests, "post", boom)
    with pytest.raises(rag_client.RagError) as e:
        rag_client.ask("http://x", "q")
    assert "연결할 수 없습니다" in str(e.value)


def test_ask_llm_502_message(monkeypatch):
    monkeypatch.setattr(rag_client.requests, "post",
                        lambda *a, **k: _Resp(502, {"error": "LM Studio가 꺼져 있는 것 같습니다."}))
    with pytest.raises(rag_client.RagError) as e:
        rag_client.ask("http://x", "q")
    assert "LM Studio" in str(e.value)


def test_ask_timeout(monkeypatch):
    def boom(*a, **k): raise rag_client.requests.exceptions.Timeout()
    monkeypatch.setattr(rag_client.requests, "post", boom)
    with pytest.raises(rag_client.RagError) as e:
        rag_client.ask("http://x", "q")
    assert "오래 걸립니다" in str(e.value)
