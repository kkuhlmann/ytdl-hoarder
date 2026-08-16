from repositories.pagination import page_count


def test_page_count_rounds_up():
    assert page_count(0, 10) == 0
    assert page_count(1, 10) == 1
    assert page_count(10, 10) == 1
    assert page_count(11, 10) == 2


def test_page_count_no_page_size_means_single_page():
    assert page_count(500, None) == 1
    assert page_count(500, 0) == 1
