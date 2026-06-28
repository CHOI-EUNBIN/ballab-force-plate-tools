# core/rag_client.py
# RAG HTTP 서비스(serve.py) 호출. UI/스레드 코드 없음(순수 I/O).
import requests


class RagError(Exception):
    """사용자에게 그대로 보여줄 메시지를 담는 예외."""


def health(base_url, timeout=3):
    r = requests.get(base_url.rstrip("/") + "/health", timeout=timeout)
    r.raise_for_status()
    return r.json()


def ask(base_url, question, mode="auto", timeout=120):
    url = base_url.rstrip("/") + "/ask"
    try:
        r = requests.post(url, json={"question": question, "mode": mode}, timeout=timeout)
    except requests.exceptions.ConnectionError:
        raise RagError(f"RAG 서비스에 연결할 수 없습니다. 서버에서 serve.py가 켜져 있는지 확인하세요. (URL: {base_url})")
    except requests.exceptions.Timeout:
        raise RagError("응답이 너무 오래 걸립니다. 다시 시도해주세요.")
    if r.status_code == 502:
        msg = ""
        try:
            msg = r.json().get("error", "")
        except Exception:
            pass
        raise RagError(msg or "LM Studio가 꺼져 있는 것 같습니다.")
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        raise RagError(f"RAG 서비스 오류 (HTTP {r.status_code}).")
    return r.json()
