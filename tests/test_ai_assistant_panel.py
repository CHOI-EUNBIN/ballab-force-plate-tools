from ui.ai_assistant_panel import doi_url


def test_doi_url_with_doi():
    assert doi_url("10.1016/j.gaitpost.2014.09.024") == "https://doi.org/10.1016/j.gaitpost.2014.09.024"


def test_doi_url_empty():
    assert doi_url("") == ""
    assert doi_url(None) == ""


def test_doi_url_already_url():
    assert doi_url("https://doi.org/10.1/x") == "https://doi.org/10.1/x"
