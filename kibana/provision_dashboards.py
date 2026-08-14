"""Provision Kibana Data Views, visualizations, saved searches, and a
dashboard for the Solitude Triage Service — via Kibana's HTTP APIs, so it's
scripted/repeatable rather than built by hand in the UI.

Usage:
    python kibana/provision_dashboards.py --kibana-url http://localhost:5601

Idempotent: every object is created with a fixed id and ?overwrite=true, so
re-running this after re-ingesting data just refreshes the same objects.
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

HEADERS = {"kbn-xsrf": "true", "Content-Type": "application/json"}


def put_data_view(base: str, auth, id_: str, title: str, name: str) -> str:
    """Create/update a Data View and return its id."""
    resp = requests.post(
        f"{base}/api/data_views/data_view",
        auth=auth, headers=HEADERS,
        json={"data_view": {"id": id_, "title": title, "name": name, "timeFieldName": "timestamp"}, "override": True},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"data view {id_} failed: {resp.status_code} {resp.text}")
    return resp.json()["data_view"]["id"]


def put_saved_object(base: str, auth, obj_type: str, id_: str, attributes: dict, references: list[dict]) -> str:
    resp = requests.post(
        f"{base}/api/saved_objects/{obj_type}/{id_}?overwrite=true",
        auth=auth, headers=HEADERS,
        json={"attributes": attributes, "references": references},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"{obj_type} {id_} failed: {resp.status_code} {resp.text}")
    return id_


def visualization(title: str, vis_type: str, params: dict, aggs: list[dict]) -> dict:
    return {
        "title": title,
        "visState": json.dumps({"title": title, "type": vis_type, "params": params, "aggs": aggs}),
        "uiStateJSON": "{}",
        "description": "",
        "version": 1,
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})
        },
    }


def index_ref(index_pattern_ref_name: str, data_view_id: str) -> dict:
    return {"name": index_pattern_ref_name, "type": "index-pattern", "id": data_view_id}


def build_signin_over_time_vis():
    return visualization(
        "Sign-ins over time by risk level", "histogram",
        {
            "type": "histogram", "grid": {"categoryLines": False}, "legendPosition": "right",
            "addTooltip": True, "addLegend": True, "addTimeMarker": False,
        },
        [
            {"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
            {"id": "2", "enabled": True, "type": "date_histogram", "schema": "segment",
             "params": {"field": "timestamp", "interval": "auto", "min_doc_count": 1}},
            {"id": "3", "enabled": True, "type": "terms", "schema": "group",
             "params": {"field": "risk_level", "size": 5, "order": "desc", "orderBy": "1"}},
        ],
    )


def build_pie_vis(title: str, field: str, size: int = 10) -> dict:
    return visualization(
        title, "pie",
        {"type": "pie", "addTooltip": True, "addLegend": True, "legendPosition": "right", "isDonut": True},
        [
            {"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
            {"id": "2", "enabled": True, "type": "terms", "schema": "segment",
             "params": {"field": field, "size": size, "order": "desc", "orderBy": "1"}},
        ],
    )


def build_table_vis(title: str, field: str, size: int = 10) -> dict:
    return visualization(
        title, "table",
        {"perPage": size, "showPartialRows": False, "showMetricsAtAllLevels": False, "showTotal": False},
        [
            {"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
            {"id": "2", "enabled": True, "type": "terms", "schema": "bucket",
             "params": {"field": field, "size": size, "order": "desc", "orderBy": "1"}},
        ],
    )


def build_saved_search(title: str, columns: list[str], kql: str) -> dict:
    return {
        "title": title,
        "columns": columns,
        "sort": [["timestamp", "desc"]],
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps({
                "query": {"query": kql, "language": "kuery"},
                "filter": [],
                "indexRefName": "kibanaSavedObjectMeta.searchSourceJSON.index",
            })
        },
    }


def panel(index: int, panel_type: str, ref_name: str, x: int, y: int, w: int = 24, h: int = 15) -> dict:
    return {
        "version": "8.15.0",
        "type": panel_type,
        "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(index)},
        "panelIndex": str(index),
        "embeddableConfig": {},
        "panelRefName": ref_name,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kibana-url", default="http://localhost:5601")
    ap.add_argument("--username", default=None)
    ap.add_argument("--password", default=None)
    args = ap.parse_args()

    auth = (args.username, args.password) if args.username else None
    base = args.kibana_url.rstrip("/")

    print(f"Provisioning Kibana objects at {base} ...")

    signin_dv = put_data_view(base, auth, "m365-signin-logs-view", "m365-signin-logs-*", "M365 Sign-in Logs")
    audit_dv = put_data_view(base, auth, "m365-audit-logs-view", "m365-audit-logs-*", "M365 Audit Logs")
    print(f"  data views: {signin_dv}, {audit_dv}")

    SIGNIN_REF = index_ref("kibanaSavedObjectMeta.searchSourceJSON.index", signin_dv)
    AUDIT_REF = index_ref("kibanaSavedObjectMeta.searchSourceJSON.index", audit_dv)

    # -- visualizations --
    put_saved_object(base, auth, "visualization", "vis-signins-over-time",
                      build_signin_over_time_vis(), [SIGNIN_REF])
    put_saved_object(base, auth, "visualization", "vis-signins-by-country",
                      build_pie_vis("Sign-ins by country", "location_country"), [SIGNIN_REF])
    put_saved_object(base, auth, "visualization", "vis-client-app-usage",
                      build_pie_vis("Client app usage (legacy vs modern)", "client_app"), [SIGNIN_REF])
    put_saved_object(base, auth, "visualization", "vis-top-users",
                      build_table_vis("Top users by sign-in volume", "user_principal_name"), [SIGNIN_REF])
    put_saved_object(base, auth, "visualization", "vis-audit-operations",
                      build_pie_vis("Audit log operations breakdown", "operation", size=15), [AUDIT_REF])
    print("  visualizations created")

    # -- saved searches --
    put_saved_object(
        base, auth, "search", "search-risky-signins",
        build_saved_search(
            "Risky / legacy-auth sign-ins",
            ["timestamp", "user_principal_name", "location_country", "client_app", "risk_level"],
            'risk_level: (medium or high) or client_app: ("Authenticated SMTP" or "POP" or "IMAP4" or "Other clients" or "Exchange ActiveSync")',
        ),
        [{"name": "kibanaSavedObjectMeta.searchSourceJSON.index", "type": "index-pattern", "id": signin_dv}],
    )
    put_saved_object(
        base, auth, "search", "search-mailrule-consent-events",
        build_saved_search(
            "Mail rule & app consent audit events",
            ["timestamp", "user_principal_name", "operation", "workload", "parameters"],
            'operation: ("New-InboxRule" or "Set-InboxRule" or "New-TransportRule" or "Set-TransportRule" or "Consent to application")',
        ),
        [{"name": "kibanaSavedObjectMeta.searchSourceJSON.index", "type": "index-pattern", "id": audit_dv}],
    )
    print("  saved searches created")

    # -- dashboard --
    panels = [
        panel(1, "visualization", "panel_1", 0, 0, w=48, h=15),
        panel(2, "visualization", "panel_2", 0, 15),
        panel(3, "visualization", "panel_3", 24, 15),
        panel(4, "visualization", "panel_4", 0, 30),
        panel(5, "visualization", "panel_5", 24, 30),
        panel(6, "search", "panel_6", 0, 45, w=48, h=15),
        panel(7, "search", "panel_7", 0, 60, w=48, h=15),
    ]
    dashboard_attrs = {
        "title": "Solitude Reloaded — M365 Triage Overview",
        "description": "Sign-in and audit log overview across ingested triage cases. Filter by case_id in the search bar to focus on a single incident.",
        "panelsJSON": json.dumps(panels),
        "optionsJSON": json.dumps({"useMargins": True, "hidePanelTitles": False}),
        "timeRestore": False,
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})
        },
    }
    dashboard_refs = [
        {"name": "panel_1", "type": "visualization", "id": "vis-signins-over-time"},
        {"name": "panel_2", "type": "visualization", "id": "vis-signins-by-country"},
        {"name": "panel_3", "type": "visualization", "id": "vis-client-app-usage"},
        {"name": "panel_4", "type": "visualization", "id": "vis-top-users"},
        {"name": "panel_5", "type": "visualization", "id": "vis-audit-operations"},
        {"name": "panel_6", "type": "search", "id": "search-risky-signins"},
        {"name": "panel_7", "type": "search", "id": "search-mailrule-consent-events"},
    ]
    put_saved_object(base, auth, "dashboard", "solitude-m365-triage-overview", dashboard_attrs, dashboard_refs)
    print("  dashboard created")

    print()
    print(f"Done. Open: {base}/app/dashboards#/view/solitude-m365-triage-overview")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.ConnectionError as e:
        print(f"ERROR: could not reach Kibana — is it running? ({e})", file=sys.stderr)
        sys.exit(1)
