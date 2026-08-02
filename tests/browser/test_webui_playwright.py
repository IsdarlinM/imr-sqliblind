from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any

import pytest

pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")
from playwright.sync_api import Page, expect

from blind_sqli.events import ScanEvent
from blind_sqli.manager import ScanManager
from blind_sqli.store import SessionStore
from blind_sqli.web_app import create_app

pytestmark = pytest.mark.browser


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entity(identifier: str, kind: str, name: str, parent_id: str | None) -> dict[str, Any]:
    return {
        "id": identifier,
        "type": kind,
        "name": name,
        "parent_id": parent_id,
        "status": "completed",
        "data": {},
    }


@pytest.fixture(scope="module")
def live_console(tmp_path_factory):
    directory = tmp_path_factory.mktemp("playwright-console")
    store = SessionStore(directory / "sessions.db")
    scan_id = "browser-e2e-scan"
    store.create_scan(
        scan_id,
        {
            "url": "https://lab.invalid/fetch",
            "parameter": "id",
            "workers": 4,
            "dialect": "sqlite",
            "oracle": "status",
        },
        _timestamp(),
    )
    entities = [
        _entity("schema-main", "schema", "main", None),
        _entity("table-users", "table", "users", "schema-main"),
        _entity("column-id", "column", "id", "table-users"),
        _entity("column-name", "column", "name", "table-users"),
        {
            **_entity("row-1", "row", "row 1", "table-users"),
            "data": {"values": {"id": "1", "name": "alice"}},
        },
    ]
    for entity in entities:
        store.record_event(
            ScanEvent(
                event_type="entity.discovered",
                scan_id=scan_id,
                payload={"entity": entity},
            )
        )
    for relation in (
        {
            "id": "rel-schema-table",
            "source_id": "schema-main",
            "target_id": "table-users",
            "kind": "contains",
        },
        {
            "id": "rel-table-column",
            "source_id": "table-users",
            "target_id": "column-id",
            "kind": "contains",
        },
    ):
        store.record_event(
            ScanEvent(
                event_type="relationship.discovered",
                scan_id=scan_id,
                payload={"relationship": relation},
            )
        )
    store.update_scan(
        scan_id,
        status="completed",
        stats={"requests": 42, "elapsed_seconds": 3.5},
        timestamp=_timestamp(),
    )

    manager = ScanManager(store)
    app = create_app(
        manager,
        auth_token="browser-test-token",
        csrf_token="browser-test-csrf",
    )
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = int(candidate.getsockname()[1])
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2)
        manager.shutdown()
        store.close()
        raise RuntimeError("The browser test server did not start")

    yield {
        "url": f"http://127.0.0.1:{port}/?token=browser-test-token",
        "store": store,
        "scan_id": scan_id,
    }

    server.should_exit = True
    thread.join(timeout=5)
    manager.shutdown()
    store.close()


def _open_scan(page: Page, live_console: dict[str, Any]) -> None:
    page.goto(live_console["url"])
    expect(page.locator(".session")).to_have_count(1)
    page.locator(".session").click()
    expect(page.locator("#treePane")).to_contain_text("main")


def test_collapsible_tree_lazy_tables_and_sse(page: Page, live_console) -> None:
    _open_scan(page, live_console)

    expect(page.locator(".professional-tree-branch")).to_have_count(5)
    page.get_by_role("button", name="Collapse all").click()
    expect(page.locator(".professional-tree-branch[open]")).to_have_count(0)

    page.locator('[data-pane="tables"]').click()
    card = page.locator(".professional-table-card")
    expect(card).to_have_count(1)
    expect(card).not_to_have_attribute("open", "")
    card.locator("summary").click()
    expect(card.locator(".professional-table-body")).to_have_attribute(
        "data-loaded", "true"
    )
    expect(card).to_contain_text("alice")

    page.locator('[data-pane="tree"]').click()
    live_console["store"].record_event(
        ScanEvent(
            event_type="entity.discovered",
            scan_id=live_console["scan_id"],
            payload={
                "entity": _entity(
                    "column-live",
                    "column",
                    "live_column",
                    "table-users",
                )
            },
        )
    )
    expect(page.locator("#treePane")).to_contain_text("live_column", timeout=5000)


def test_elastic_graph_drag_and_minimap(page: Page, live_console) -> None:
    _open_scan(page, live_console)
    page.locator('[data-pane="graph"]').click()
    expect(page.locator(".graph-node").first).to_be_visible()
    assert page.locator(".graph-node").count() >= 5
    expect(page.locator("#graphMinimap")).to_be_visible()
    page.wait_for_timeout(1200)

    nodes = page.locator(".graph-node")
    first = nodes.nth(0)
    related = nodes.nth(1)
    first_box = first.bounding_box()
    related_before = related.bounding_box()
    assert first_box and related_before

    page.mouse.move(
        first_box["x"] + first_box["width"] / 2,
        first_box["y"] + first_box["height"] / 2,
    )
    page.mouse.down()
    page.mouse.move(
        first_box["x"] + first_box["width"] / 2 + 90,
        first_box["y"] + first_box["height"] / 2 + 45,
        steps=8,
    )
    page.mouse.up()
    page.wait_for_timeout(150)

    related_after = related.bounding_box()
    assert related_after
    displacement = abs(related_after["x"] - related_before["x"]) + abs(
        related_after["y"] - related_before["y"]
    )
    assert displacement > 1


def test_mobile_layout_has_no_document_overflow(page: Page, live_console) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    _open_scan(page, live_console)
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 1
