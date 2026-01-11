"""
Tests for the LangGraph triage agent.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import (
    app,
    triage_graph,
    ingest,
    classify_issue,
    draft_reply,
    fetch_order,
    ORDERS,
)


# -----------------------------------------------------------------------------
# FastAPI TestClient
# -----------------------------------------------------------------------------

client = TestClient(app)


# -----------------------------------------------------------------------------
# Unit Tests: Individual Nodes
# -----------------------------------------------------------------------------

class TestIngestNode:
    """Tests for the ingest node."""

    def test_extracts_order_id_from_text(self):
        """Should extract order_id from ticket text using regex."""
        state = {"ticket_text": "Help with order ORD1001 please", "order_id": None}
        result = ingest(state)
        assert result["order_id"] == "ORD1001"

    def test_preserves_provided_order_id(self):
        """Should not override explicitly provided order_id."""
        state = {"ticket_text": "Help with order ORD1001", "order_id": "ORD9999"}
        result = ingest(state)
        assert result["order_id"] == "ORD9999"

    def test_handles_missing_order_id(self):
        """Should return None if no order_id found in text."""
        state = {"ticket_text": "I have a problem", "order_id": None}
        result = ingest(state)
        assert result["order_id"] is None

    def test_case_insensitive_extraction(self):
        """Should extract order_id regardless of case."""
        state = {"ticket_text": "order ord1002 is late", "order_id": None}
        result = ingest(state)
        assert result["order_id"] == "ORD1002"


class TestClassifyIssueNode:
    """Tests for the classify_issue node."""

    def test_classifies_damaged_item(self):
        """Should classify 'broken' keyword as damaged_item."""
        state = {"ticket_text": "My item arrived broken"}
        result = classify_issue(state)
        assert result["issue_type"] == "damaged_item"

    def test_classifies_refund_request(self):
        """Should classify 'refund' keyword as refund_request."""
        state = {"ticket_text": "I want a refund please"}
        result = classify_issue(state)
        assert result["issue_type"] == "refund_request"

    def test_classifies_late_delivery(self):
        """Should classify 'late' keyword as late_delivery."""
        state = {"ticket_text": "My order is late"}
        result = classify_issue(state)
        assert result["issue_type"] == "late_delivery"

    def test_returns_unknown_for_unmatched(self):
        """Should return 'unknown' for unrecognized issues."""
        state = {"ticket_text": "Hello there"}
        result = classify_issue(state)
        assert result["issue_type"] == "unknown"


class TestDraftReplyNode:
    """Tests for the draft_reply node."""

    def test_drafts_reply_with_customer_data(self):
        """Should render template with customer name and order_id."""
        state = {
            "issue_type": "damaged_item",
            "evidence": {"customer_name": "John Doe", "order_id": "ORD1001"}
        }
        result = draft_reply(state)
        assert "John Doe" in result["recommendation"]
        assert "ORD1001" in result["recommendation"]

    def test_handles_missing_evidence(self):
        """Should use defaults when evidence is missing."""
        state = {"issue_type": "unknown", "evidence": None}
        result = draft_reply(state)
        assert "Customer" in result["recommendation"]


class TestFetchOrderTool:
    """Tests for the fetch_order tool."""

    def test_fetches_existing_order(self):
        """Should return order data for valid order_id."""
        result = fetch_order.invoke({"order_id": "ORD1001"})
        assert result["order_id"] == "ORD1001"
        assert "customer_name" in result

    def test_returns_error_for_invalid_order(self):
        """Should return error for non-existent order_id."""
        result = fetch_order.invoke({"order_id": "ORD9999"})
        assert "error" in result


# -----------------------------------------------------------------------------
# Integration Tests: Full Graph
# -----------------------------------------------------------------------------

class TestTriageGraph:
    """Integration tests for the complete triage graph."""

    def test_full_workflow_with_order_in_text(self):
        """Should process ticket with order_id in text."""
        result = triage_graph.invoke({
            "messages": [],
            "ticket_text": "My order ORD1001 arrived broken",
            "order_id": None,
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        })

        assert result["order_id"] == "ORD1001"
        assert result["issue_type"] == "damaged_item"
        assert result["evidence"]["customer_name"] == "Ava Chen"
        assert "Ava Chen" in result["recommendation"]

    def test_full_workflow_with_explicit_order_id(self):
        """Should process ticket with explicitly provided order_id."""
        result = triage_graph.invoke({
            "messages": [],
            "ticket_text": "I want a refund",
            "order_id": "ORD1002",
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        })

        assert result["order_id"] == "ORD1002"
        assert result["issue_type"] == "refund_request"
        assert result["evidence"]["customer_name"] == "David Lee"

    def test_workflow_ends_early_without_order_id(self):
        """Should end early if no order_id can be extracted."""
        result = triage_graph.invoke({
            "messages": [],
            "ticket_text": "I have a problem",
            "order_id": None,
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        })

        assert result["order_id"] is None
        assert result["issue_type"] is None


# -----------------------------------------------------------------------------
# API Tests: FastAPI Endpoints
# -----------------------------------------------------------------------------

class TestTriageEndpoint:
    """Tests for the /triage/invoke endpoint."""

    def test_successful_triage(self):
        """Should return complete triage result."""
        response = client.post(
            "/triage/invoke",
            json={"ticket_text": "Order ORD1001 is broken"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["order_id"] == "ORD1001"
        assert data["issue_type"] == "damaged_item"
        assert "order" in data
        assert "reply_text" in data

    def test_with_explicit_order_id(self):
        """Should accept explicit order_id in request."""
        response = client.post(
            "/triage/invoke",
            json={"ticket_text": "Need refund", "order_id": "ORD1002"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["order_id"] == "ORD1002"
        assert data["issue_type"] == "refund_request"

    def test_missing_order_id_returns_400(self):
        """Should return 400 if order_id cannot be extracted."""
        response = client.post(
            "/triage/invoke",
            json={"ticket_text": "I have a problem"}
        )
        assert response.status_code == 400
        assert "order_id missing" in response.json()["detail"]

    def test_invalid_order_returns_404(self):
        """Should return 404 for non-existent order."""
        response = client.post(
            "/triage/invoke",
            json={"ticket_text": "Help with ORD9999"}
        )
        assert response.status_code == 404


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check(self):
        """Should return ok status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestUtilityEndpoints:
    """Tests for utility endpoints."""

    def test_orders_get(self):
        """Should fetch order by ID."""
        response = client.get("/orders/get", params={"order_id": "ORD1001"})
        assert response.status_code == 200
        assert response.json()["order_id"] == "ORD1001"

    def test_orders_get_not_found(self):
        """Should return 404 for invalid order."""
        response = client.get("/orders/get", params={"order_id": "INVALID"})
        assert response.status_code == 404

    def test_classify_issue(self):
        """Should classify issue from text."""
        response = client.post(
            "/classify/issue",
            json={"ticket_text": "broken item"}
        )
        assert response.status_code == 200
        assert response.json()["issue_type"] == "damaged_item"

    def test_reply_draft(self):
        """Should draft reply with template."""
        response = client.post(
            "/reply/draft",
            json={
                "issue_type": "refund_request",
                "order": {"customer_name": "Test User", "order_id": "ORD0001"}
            }
        )
        assert response.status_code == 200
        assert "Test User" in response.json()["reply_text"]
