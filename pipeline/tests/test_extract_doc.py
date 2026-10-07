from extract_docs import bill, x_post

from brokeberg.extract.doc import ground


def test_header_carries_structured_fields() -> None:
    assert x_post().text.startswith("Author: @LisaMurkowski\n---\n")
    assert "Sponsor: Sen. Ossoff, Jon [D-GA]" in bill().text


def test_ground_is_verbatim_modulo_whitespace_and_quotes() -> None:
    doc = x_post("Tariffs are a  tax on   Alaska’s families.")
    assert ground("tax on Alaska's families", doc)
    assert ground("Author: @LisaMurkowski", doc)
    assert not ground("tariffs are a tax", doc)  # case matters: verbatim
    assert not ground("a tax on Alaskan families", doc)
    assert not ground("", doc)
    assert not ground(None, doc)
