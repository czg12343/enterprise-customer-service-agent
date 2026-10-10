from app.rag.parser import split_text


def test_pdf_page_boundaries_are_preserved_in_chunks():
    chunks = split_text("第一页退货政策\f第二页保修政策", chunk_size=100, overlap=0)

    assert [chunk["page_number"] for chunk in chunks] == [1, 2]
    assert chunks[0]["content"] == "第一页退货政策"
    assert chunks[1]["content"] == "第二页保修政策"

