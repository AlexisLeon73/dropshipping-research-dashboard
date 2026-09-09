from app.scoring import combine_source_scores, score_google_trends_series


def test_rising_series_scores_high_with_positive_growth():
    values = [10] * 10 + list(range(10, 100, 3))
    result = score_google_trends_series(values)
    assert result["score"] > 50
    assert result["growth_pct"] > 0
    assert result["momentum_pct"] > 0


def test_flat_series_has_near_zero_growth_and_momentum():
    values = [50] * 90
    result = score_google_trends_series(values)
    assert abs(result["growth_pct"]) < 1
    assert abs(result["momentum_pct"]) < 1


def test_declining_series_has_negative_growth():
    values = list(range(100, 10, -3))
    result = score_google_trends_series(values)
    assert result["growth_pct"] < 0


def test_combine_source_scores_ignores_unconfigured_sources():
    combined = combine_source_scores({"google_trends": 80.0, "reddit": None})
    assert combined == 80.0


def test_combine_source_scores_weights_by_source():
    combined = combine_source_scores({"google_trends": 50.0, "meta_ads": 100.0})
    expected = round((50.0 * 1.0 + 100.0 * 1.2) / (1.0 + 1.2), 1)
    assert combined == expected


def test_combine_source_scores_empty_returns_zero():
    assert combine_source_scores({}) == 0.0
