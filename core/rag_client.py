# core/rag_client.py
# RAG HTTP 서비스(serve.py) 호출. UI/스레드 코드 없음(순수 I/O).
import requests


class RagError(Exception):
    """사용자에게 그대로 보여줄 메시지를 담는 예외."""


def health(base_url, timeout=3):
    try:
        r = requests.get(base_url.rstrip("/") + "/health", timeout=timeout)
    except requests.exceptions.ConnectionError:
        raise RagError(f"Cannot connect to the RAG service. (URL: {base_url})")
    except requests.exceptions.Timeout:
        raise RagError("The response is taking too long. Please try again.")
    r.raise_for_status()
    return r.json()


def ask(base_url, question, mode="auto", timeout=120):
    url = base_url.rstrip("/") + "/ask"
    try:
        r = requests.post(url, json={"question": question, "mode": mode}, timeout=timeout)
    except requests.exceptions.ConnectionError:
        raise RagError(f"Cannot connect to the RAG service. Make sure serve.py is running. (URL: {base_url})")
    except requests.exceptions.Timeout:
        raise RagError("The response is taking too long. Please try again.")
    if r.status_code == 502:
        msg = ""
        try:
            msg = r.json().get("error", "")
        except (ValueError, AttributeError):
            pass
        raise RagError(msg or "LM Studio appears to be offline.")
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        raise RagError(f"RAG service error (HTTP {r.status_code}).")
    return r.json()
