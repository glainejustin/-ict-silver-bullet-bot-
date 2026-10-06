"""Unit tests for the new free connectors, using mocked HTTP/filesystem so
they run fully offline and don't depend on live third-party services.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectors.brownfield_land import BrownfieldLandConnector  # noqa: E402
from connectors.corporate_ownership import CorporateOwnershipConnector  # noqa: E402
from connectors.gazette_insolvency import GazetteInsolvencyConnector  # noqa: E402
from connectors.open_data_csv import OpenDataCsvConnector  # noqa: E402


def _mock_response(json_data=None, content=None, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    if json_data is not None:
        resp.json.return_value = json_data
    if content is not None:
        resp.content = content
    return resp


@patch("connectors.gazette_insolvency.requests.get")
def test_gazette_insolvency_parses_entries_and_extracts_postcode(mock_get):
    mock_get.return_value = _mock_response(
        json_data={
            "entry": [
                {
                    "id": "notice-1",
                    "title": "Winding up order - Acme Properties Ltd, M14 5TP",
                    "summary": "Company wound up by court order.",
                },
            ]
        }
    )
    connector = GazetteInsolvencyConnector(search_terms=["winding up order"], max_pages=1)
    leads = connector.fetch_leads()
    assert len(leads) == 1
    assert leads[0]["source"] == "gazette_insolvency"
    assert leads[0]["postcode"] == "M14 5TP"
    assert leads[0]["status"] == "lead_to_research"


@patch("connectors.gazette_insolvency.requests.get")
def test_gazette_insolvency_handles_network_failure_gracefully(mock_get):
    mock_get.side_effect = Exception("network down")
    connector = GazetteInsolvencyConnector(search_terms=["test"], max_pages=1)
    assert connector.fetch_leads() == []


@patch("connectors.brownfield_land.requests.get")
def test_brownfield_land_parses_entities(mock_get):
    mock_get.return_value = _mock_response(
        json_data={
            "entities": [
                {"entity": 123, "name": "Former Gasworks Site", "minimum-net-dwellings": "40"},
            ]
        }
    )
    connector = BrownfieldLandConnector(max_pages=1)
    leads = connector.fetch_leads()
    assert len(leads) == 1
    assert leads[0]["source"] == "brownfield_land"
    assert "40" in leads[0]["motivation_signal"]


def test_open_data_csv_skips_when_unconfigured():
    connector = OpenDataCsvConnector(urls=[])
    assert connector.fetch_leads() == []


@patch("connectors.open_data_csv.requests.get")
def test_open_data_csv_maps_flexible_columns(mock_get):
    csv_content = (
        "Property Address,Post Code,Empty Since\n"
        "12 High Street,M14 5TP,2022-03-01\n"
    ).encode("utf-8")
    mock_get.return_value = _mock_response(content=csv_content)
    connector = OpenDataCsvConnector(urls=["https://example-council.gov.uk/empty-homes.csv"])
    leads = connector.fetch_leads()
    assert len(leads) == 1
    assert leads[0]["postcode"] == "M14 5TP"
    assert leads[0]["address"] == "12 High Street"


def test_corporate_ownership_missing_file_returns_empty(tmp_path):
    connector = CorporateOwnershipConnector(ccod_csv_path=str(tmp_path / "missing.csv"))
    assert connector.fetch_leads() == []


def test_corporate_ownership_filters_by_target_company_numbers(tmp_path):
    csv_path = tmp_path / "ccod.csv"
    csv_path.write_text(
        "Title Number,Property Address,Postcode,Proprietor Name (1),Company Registration No. (1)\n"
        "TT1,1 Acme Way,B1 1AA,Acme Ltd,01234567\n"
        "TT2,2 Other Road,B2 2BB,Other Ltd,09999999\n",
        encoding="utf-8",
    )
    connector = CorporateOwnershipConnector(
        ccod_csv_path=str(csv_path), target_company_numbers={"01234567"}
    )
    leads = connector.fetch_leads()
    assert len(leads) == 1
    assert leads[0]["postcode"] == "B1 1AA"
    assert "01234567" in leads[0]["motivation_signal"]
