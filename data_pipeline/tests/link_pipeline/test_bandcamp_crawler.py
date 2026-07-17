import pytest
from unittest.mock import MagicMock
import json

from data_pipeline.link_pipeline.crawler import BandcampCrawler


@pytest.fixture
def crawler():
    return BandcampCrawler("https://bandcamp.com/discover/rock/digital?s=new")


class TestOnResponse:
    def test_on_response_adds_items_from_items_key(self, crawler):
        mock_resp = MagicMock()
        mock_resp.url = "/api/discover/3/discover_web"
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "items": [{"item_id": 1}, {"item_id": 2}]
        }

        crawler._on_response(mock_resp)

        assert len(crawler.discover_payloads) == 2

    def test_on_response_adds_items_from_results_key(self, crawler):
        mock_resp = MagicMock()
        mock_resp.url = "/api/discover/3/discover_mobile_web"
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "results": [{"item_id": 10}, {"item_id": 11}, {"item_id": 12}]
        }

        crawler._on_response(mock_resp)

        assert len(crawler.discover_payloads) == 3

    def test_on_response_ignores_non_matching_urls(self, crawler):
        mock_resp = MagicMock()
        mock_resp.url = "https://bandcamp.com/some/other/endpoint"
        mock_resp.ok = True

        crawler._on_response(mock_resp)

        assert len(crawler.discover_payloads) == 0
        mock_resp.json.assert_not_called()

    def test_on_response_ignores_failed_responses(self, crawler):
        mock_resp = MagicMock()
        mock_resp.url = "/api/discover/3/discover_web"
        mock_resp.ok = False

        crawler._on_response(mock_resp)

        assert len(crawler.discover_payloads) == 0
        mock_resp.json.assert_not_called()

    def test_on_response_handles_invalid_json(self, crawler):
        mock_resp = MagicMock()
        mock_resp.url = "/api/discover/3/discover_web"
        mock_resp.ok = True
        mock_resp.json.side_effect = ValueError("not JSON")

        # Should not raise
        crawler._on_response(mock_resp)

        assert len(crawler.discover_payloads) == 0

    def test_on_response_accumulates_across_calls(self, crawler):
        for i in range(3):
            mock_resp = MagicMock()
            mock_resp.url = "/api/discover/3/discover_web"
            mock_resp.ok = True
            mock_resp.json.return_value = {"items": [{"item_id": i}]}
            crawler._on_response(mock_resp)

        assert len(crawler.discover_payloads) == 3


class TestGetDiscoverPayloads:
    def test_returns_empty_list_initially(self, crawler):
        assert crawler.get_discover_payloads() == []

    def test_returns_accumulated_payloads(self, crawler):
        crawler.discover_payloads = [{"item_id": 1}, {"item_id": 2}]

        result = crawler.get_discover_payloads()

        assert len(result) == 2
        assert result[0]["item_id"] == 1


class TestPrintTimingStats:
    def test_print_timing_stats_no_data(self, crawler, capsys):
        crawler._print_timing_stats()

        captured = capsys.readouterr()
        assert "No timing data" in captured.out

    def test_print_timing_stats_with_data(self, crawler, capsys):
        crawler.click_times = [1.0, 2.0, 3.0]

        crawler._print_timing_stats()

        captured = capsys.readouterr()
        assert "Total clicks: 3" in captured.out
        assert "Average time" in captured.out


class TestEndBrowser:
    def test_end_browser_closes_browser_and_playwright(self, crawler):
        mock_browser = MagicMock()
        mock_playwright = MagicMock()
        crawler.browser = mock_browser
        crawler.playwright = mock_playwright

        crawler._end_browser()

        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()

    def test_end_browser_handles_none_browser(self, crawler):
        crawler.browser = None
        crawler.playwright = None

        # Should not raise
        crawler._end_browser()
