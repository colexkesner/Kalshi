from kalshi_weather_hitbot.data.city_bootstrap import parse_contract_terms_text


def test_parse_contract_terms_extracts_location_and_wfo():
    text = """
    Settlement uses weather.gov/wrh/Climate?wfo=LOT.
    Location: Chicago Midway, IL
    """
    out = parse_contract_terms_text(text)
    assert out.nws_wfo == "LOT"
    assert out.resolution_location_name == "Chicago Midway, IL"
    assert out.resolution_source_type == "nws_climate_daily"
