#!/usr/bin/env python3
"""
Content Mate v2.2 — Airtable Utilities
Common CRUD operations for Airtable.
"""

import json
import ssl
import certifi
import subprocess
from urllib.request import Request, urlopen
from urllib.parse import quote

SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def api_get(url, headers=None):
    req = Request(url, headers=headers or {})
    resp = urlopen(req, context=SSL_CTX)
    return json.loads(resp.read())


def api_request(url, data=None, method="GET", headers=None):
    h = headers or {}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=h, method=method)
    resp = urlopen(req, context=SSL_CTX)
    return json.loads(resp.read())


def curl_get(url):
    """Fallback to curl for requests that fail with urllib."""
    out = subprocess.run(["curl", "-s", url], capture_output=True, text=True)
    return json.loads(out.stdout)


class AirtableClient:
    def __init__(self, config: dict):
        self.token = config["airtable_token"]
        self.base_id = config["base_id"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _url(self, table_id, record_id=None):
        base = f"https://api.airtable.com/v0/{self.base_id}/{table_id}"
        if record_id:
            base += f"/{record_id}"
        return base

    def get_record(self, table_id: str, record_id: str) -> dict:
        return api_get(self._url(table_id, record_id), self.headers)

    def search(self, table_id: str, formula: str = None, sort_field: str = None,
               sort_dir: str = "desc", max_records: int = 100, view: str = None) -> list:
        url = self._url(table_id) + "?"
        params = []
        if formula:
            params.append(f"filterByFormula={quote(formula)}")
        if sort_field:
            params.append(f"sort%5B0%5D%5Bfield%5D={quote(sort_field)}")
            params.append(f"sort%5B0%5D%5Bdirection%5D={sort_dir}")
        if max_records:
            params.append(f"maxRecords={max_records}")
        if view:
            params.append(f"view={view}")
        url += "&".join(params)
        data = api_get(url, self.headers)
        return data.get("records", [])

    def create_record(self, table_id: str, fields: dict) -> dict:
        data = {"records": [{"fields": fields}]}
        result = api_request(self._url(table_id), data, method="POST",
                            headers={**self.headers, "Content-Type": "application/json"})
        return result.get("records", [{}])[0]

    def update_record(self, table_id: str, record_id: str, fields: dict) -> dict:
        data = {"fields": fields}
        return api_request(self._url(table_id, record_id), data, method="PATCH",
                          headers={**self.headers, "Content-Type": "application/json"})

    def delete_record(self, table_id: str, record_id: str) -> dict:
        return api_request(self._url(table_id, record_id), method="DELETE",
                          headers=self.headers)

    def search_all(self, table_id: str) -> list:
        """Get all records (handles pagination)."""
        all_records = []
        offset = None
        while True:
            url = self._url(table_id)
            if offset:
                url += f"?offset={offset}"
            data = api_get(url, self.headers)
            all_records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break
        return all_records
