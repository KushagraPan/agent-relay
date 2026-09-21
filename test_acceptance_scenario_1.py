"""Acceptance Scenario 1 automated integration test.

SPEC.md Acceptance Scenario 1:
"Register two agents. One sends a task; the other claims and completes it; the sender reads the result."

This test runs against the real API and real SQLite database without mocks.
"""

from __future__ import annotations

import os
import httpx
import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    """Provides an HTTP client that communicates with the real Agent Relay service.

    If a live server is running at http://127.0.0.1:8000 (or RELAY_BASE_URL),
    it communicates over standard HTTP using httpx.Client.
    Otherwise, it uses FastAPI's TestClient to run the full application in-process
    against the real SQLite database.
    """
    base_url = os.getenv("RELAY_BASE_URL", "http://127.0.0.1:8000")
    try:
        with httpx.Client(base_url=base_url, timeout=5.0) as http_client:
            resp = http_client.get("/health")
            if resp.status_code == 200:
                yield http_client
                return
    except Exception:
        pass

    with TestClient(main.app) as test_client:
        yield test_client


def test_acceptance_scenario_1_full_flow(client):
    """Executes the exact 5-step sequence of Acceptance Scenario 1:
    1. Register agent 'bob'
    2. Register agent 'uppercase'
    3. Bob sends a task to uppercase with input text
    4. Simulate the uppercase worker claiming the task, processing it, and submitting completion
    5. Assert that bob, querying the task, sees status 'completed' and the correct output
    """

    # 1. Register agent "bob" (the sender)
    bob_resp = client.post("/api/v1/agents", json={"name": "bob"})
    assert bob_resp.status_code == 201
    bob_data = bob_resp.json()
    assert "agent_id" in bob_data and "token" in bob_data
    bob_id = bob_data["agent_id"]
    bob_token = bob_data["token"]
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # 2. Register agent "uppercase" (the worker)
    worker_resp = client.post("/api/v1/agents", json={"name": "uppercase"})
    assert worker_resp.status_code == 201
    worker_data = worker_resp.json()
    assert "agent_id" in worker_data and "token" in worker_data
    worker_id = worker_data["agent_id"]
    worker_token = worker_data["token"]
    worker_headers = {"Authorization": f"Bearer {worker_token}"}

    # 3. Bob sends a task to uppercase with input text
    input_text = "hello from bob automated test"
    task_resp = client.post(
        "/api/v1/tasks",
        headers=bob_headers,
        json={"to": worker_id, "input": input_text},
    )
    assert task_resp.status_code == 201
    task_data = task_resp.json()
    assert task_data["status"] == "queued"
    task_id = task_data["task_id"]

    # 4. Simulate the uppercase worker claiming the task, processing it, and submitting completion
    claim_resp = client.post(
        "/api/v1/tasks/claim",
        headers=worker_headers,
        json={"worker_id": "test-worker-1", "wait_seconds": 0},
    )
    assert claim_resp.status_code == 200
    claim_data = claim_resp.json()
    assert claim_data["task_id"] == task_id
    assert claim_data["from"] == bob_id
    assert claim_data["input"] == input_text
    assert claim_data["attempt"] == 1
    assert "claim_token" in claim_data
    claim_token = claim_data["claim_token"]

    # The worker processes the input by converting it to uppercase
    output_text = claim_data["input"].upper()
    assert output_text == "HELLO FROM BOB AUTOMATED TEST"

    # The worker submits the completed result
    complete_resp = client.post(
        f"/api/v1/tasks/{task_id}/complete",
        headers=worker_headers,
        json={"claim_token": claim_token, "output": output_text},
    )
    assert complete_resp.status_code == 200
    complete_data = complete_resp.json()
    assert complete_data["task_id"] == task_id
    assert complete_data["status"] == "completed"

    # 5. Assert that bob, querying the task, sees status 'completed' and the correct output
    get_resp = client.get(f"/api/v1/tasks/{task_id}", headers=bob_headers)
    assert get_resp.status_code == 200
    final_task = get_resp.json()
    assert final_task["task_id"] == task_id
    assert final_task["from"] == bob_id
    assert final_task["to"] == worker_id
    assert final_task["input"] == input_text
    assert final_task["status"] == "completed"
    assert final_task["output"] == "HELLO FROM BOB AUTOMATED TEST"
    assert final_task["error"] is None
    assert final_task["attempt_count"] == 1
    assert final_task["finished_at"] is not None
