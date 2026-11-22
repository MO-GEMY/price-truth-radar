from app.catalog_search import build_catalog_query, exact_catalog_sql, fuzzy_catalog_sql


def test_microwave_spellings_share_one_product_concept():
    standard = build_catalog_query("ميكروويف")
    for spelling in ("ميكرويف", "مايكرويف", "مايكروويف", "الميكروويف", "مِيكروويف", "microwave", "Microwaves"):
        query = build_catalog_query(spelling)
        assert query.terms == standard.terms
        assert query.demote_microwave_parts
        assert fuzzy_catalog_sql(query, 20) is None


def test_mixed_language_brand_and_capacity_stay_required():
    mixed = build_catalog_query("مايكروويف شارب ٢٥ لتر")
    english = build_catalog_query("microwave Sharp 25L")
    assert mixed.terms == english.terms
    assert [term.concept for term in mixed.terms] == ["microwave", "sharp", None]
    assert [term.fuzzy_word for term in mixed.terms] == [None, None, None]
    assert exact_catalog_sql(mixed, 20)[1]["prefer_arabic"] is True
    assert exact_catalog_sql(english, 20)[1]["prefer_arabic"] is False


def test_multiword_capacity_aliases_and_model_numbers_stay_intact():
    assert build_catalog_query("١٢٨ جيجا بايت").terms == build_catalog_query("128GB").terms
    assert build_catalog_query("١٫٥ حصان").terms == build_catalog_query("1.5HP").terms

    terms = build_catalog_query("Sharp R-770AR(ST)").terms
    assert len(terms) == 4
    assert "770ar" in terms[2].pattern
    assert all(term.fuzzy_word is None for term in terms)


def test_fuzzy_matching_can_relax_a_spelling_without_relaxing_a_model_number():
    query = build_catalog_query("samsng A17")
    sql, params = fuzzy_catalog_sql(query, 20)
    assert params["word_0"] == "samsng"
    assert "word_1" not in params
    assert "AND p.search_document ~ :term_1" in sql
    assert "a17" in params["term_1"]


def test_explicit_accessory_search_keeps_appliance_demotion_disabled():
    for phrase in ("microwave dish", "غطاء ميكرويف"):
        query = build_catalog_query(phrase)
        assert not query.demote_microwave_parts
        sql, params = exact_catalog_sql(query, 20)
        assert "p.search_document ~ :term_0 AND p.search_document ~ :term_1" in sql
        assert params["demote_parts"] is False
