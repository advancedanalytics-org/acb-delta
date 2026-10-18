from app.ria.textutil import content_bigrams, extract_quantities, parse_vietnamese_number


def test_vietnamese_number_words():
    assert parse_vietnamese_number("mười lăm") == 15
    assert parse_vietnamese_number("sáu mươi") == 60
    assert parse_vietnamese_number("ba mươi") == 30
    assert parse_vietnamese_number("12") == 12


def test_quantities_bounds_units_and_dates():
    qs = extract_quantities("phải đối chiếu tối đa 12 tháng một lần")
    assert [(q.raw_value, q.unit, q.bound, q.value) for q in qs] == [(12, "tháng", "max", 360)]

    qs = extract_quantities("Chậm nhất mười lăm ngày làm việc trước ngày đến hạn")
    assert qs[0].dimension == "business_day" and qs[0].raw_value == 15 and qs[0].bound == "max"

    qs = extract_quantities("lưu tối thiểu năm năm kể từ ngày đóng quan hệ")
    assert qs[0].raw_value == 5 and qs[0].unit == "năm" and qs[0].bound == "min"

    # Date parts are not durations.
    assert extract_quantities("có hiệu lực từ ngày 15 tháng 01 năm 2024") == []


def test_content_bigrams_drop_stopwords_and_boilerplate():
    grams = content_bigrams("Ngân hàng phải rà soát hồ sơ khách hàng theo quy định tại Điều này")
    assert "rà soát" in grams and "khách hàng" in grams
    assert "quy định" not in grams and "điều này" not in grams
