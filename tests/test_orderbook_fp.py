from kalshi_weather_hitbot.kalshi.models import normalize_orderbook


def test_orderbook_fp_parsing_prefers_fixed_point_levels():
    response = {
        "orderbook": {"yes": [[35, 1]], "no": [[65, 1]]},
        "orderbook_fp": {
            "yes_dollars": [["0.41", "3.00"], ["0.44", "7.00"]],
            "no_dollars": [["0.52", "2.00"], ["0.56", "8.00"]],
        },
    }

    out = normalize_orderbook(response)

    assert out.best_yes_bid_cents == 44
    assert out.yes_bid_size == 7
    assert out.best_no_bid_cents == 56
    assert out.no_bid_size == 8
    assert out.best_yes_ask_cents == 44
    assert out.best_no_ask_cents == 56
