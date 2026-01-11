"""
LangGraph-based support ticket triage agent.
Refactored from procedural FastAPI logic into a minimal LangGraph workflow.
"""

import json, os, re
from operator import add
from typing import TypedDict, Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Load environment variables from .env file (for LangSmith tracing)
load_dotenv()

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from langchain_core.messages import BaseMessage, ToolMessage, AIMessage

# -----------------------------------------------------------------------------
# FastAPI setup and mock data loading (preserved from original)
# -----------------------------------------------------------------------------

app = FastAPI(title="LangGraph Triage Agent")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MOCK_DIR = os.path.join(ROOT, "mock_data")


def load(name):
    with open(os.path.join(MOCK_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


ORDERS = load("orders.json")
ISSUES = load("issues.json")
REPLIES = load("replies.json")


# -----------------------------------------------------------------------------
# LangGraph State Definition
# Required keys: messages, ticket_text, order_id, issue_type, evidence, recommendation
# -----------------------------------------------------------------------------

class TriageState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add]  # Accumulates messages across nodes
    ticket_text: str                              # Raw ticket text from user
    order_id: str | None                          # Order ID (extracted or provided)
    issue_type: str | None                        # Classified issue type
    evidence: dict | None                         # Order data fetched as evidence
    recommendation: str | None                    # Drafted reply text


# -----------------------------------------------------------------------------
# Tool Definition: fetch_order (for ToolNode)
# -----------------------------------------------------------------------------

@tool
def fetch_order(order_id: str) -> dict:
    """Fetch order details from mock database by order_id."""
    for o in ORDERS:
        if o["order_id"] == order_id:
            return o
    return {"error": "Order not found", "order_id": order_id}


# ToolNode wrapping the fetch_order tool
tools = [fetch_order]
tool_node = ToolNode(tools)


# -----------------------------------------------------------------------------
# Node: ingest
# Purpose: Initialize state from input, extract order_id if missing
# -----------------------------------------------------------------------------

def ingest(state: TriageState) -> TriageState:
    """Ingest ticket and extract order_id from text if not provided."""
    ticket_text = state.get("ticket_text", "")
    order_id = state.get("order_id")

    # Extract order_id from text using existing regex logic
    if not order_id:
        m = re.search(r"(ORD\d{4})", ticket_text, re.IGNORECASE)
        if m:
            order_id = m.group(1).upper()

    return {"order_id": order_id}


# -----------------------------------------------------------------------------
# Node: classify_issue
# Purpose: Classify the issue type based on keyword rules (preserved logic)
# -----------------------------------------------------------------------------

def classify_issue(state: TriageState) -> TriageState:
    """Classify ticket issue type using keyword matching rules."""
    text = state.get("ticket_text", "").lower()

    for rule in ISSUES:
        if rule["keyword"] in text:
            return {"issue_type": rule["issue_type"]}

    return {"issue_type": "unknown"}


# -----------------------------------------------------------------------------
# Node: prepare_fetch
# Purpose: Create a tool call message to invoke fetch_order via ToolNode
# -----------------------------------------------------------------------------

def prepare_fetch(state: TriageState) -> TriageState:
    """Prepare tool call for fetching order data."""
    order_id = state.get("order_id")

    # Create an AIMessage with tool_calls to trigger the ToolNode
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "id": "fetch_order_call",
            "name": "fetch_order",
            "args": {"order_id": order_id}
        }]
    )
    return {"messages": [tool_call_msg]}


# -----------------------------------------------------------------------------
# Node: process_fetch_result
# Purpose: Extract order data from tool result and store as evidence
# -----------------------------------------------------------------------------

def process_fetch_result(state: TriageState) -> TriageState:
    """Process the tool result and store order as evidence."""
    messages = state.get("messages", [])

    # Find the ToolMessage with our result
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            try:
                evidence = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            except json.JSONDecodeError:
                evidence = {"raw": msg.content}
            return {"evidence": evidence}

    return {"evidence": None}


# -----------------------------------------------------------------------------
# Node: draft_reply
# Purpose: Generate reply using template (preserved logic)
# -----------------------------------------------------------------------------

def draft_reply(state: TriageState) -> TriageState:
    """Draft a reply using issue-specific templates."""
    issue_type = state.get("issue_type", "unknown")
    evidence = state.get("evidence") or {}

    # Find matching template
    template = next(
        (r["template"] for r in REPLIES if r["issue_type"] == issue_type),
        "Hi {{customer_name}}, we are reviewing order {{order_id}}."
    )

    # Render template with order data
    recommendation = template.replace(
        "{{customer_name}}", evidence.get("customer_name", "Customer")
    ).replace(
        "{{order_id}}", evidence.get("order_id", "")
    )

    return {"recommendation": recommendation}


# -----------------------------------------------------------------------------
# Conditional Edge: check if order_id exists
# -----------------------------------------------------------------------------

def should_proceed(state: TriageState) -> str:
    """Route based on whether order_id was successfully extracted."""
    if state.get("order_id"):
        return "has_order"
    return "missing_order"


# -----------------------------------------------------------------------------
# Graph Construction
# -----------------------------------------------------------------------------

def build_graph():
    """Build and compile the triage LangGraph."""
    graph = StateGraph(TriageState)

    # Add nodes
    graph.add_node("ingest", ingest)
    graph.add_node("classify_issue", classify_issue)
    graph.add_node("prepare_fetch", prepare_fetch)
    graph.add_node("fetch_order", tool_node)       # ToolNode for order fetching
    graph.add_node("process_fetch_result", process_fetch_result)
    graph.add_node("draft_reply", draft_reply)

    # Set entry point
    graph.set_entry_point("ingest")

    # Add conditional edge after ingest: check if order_id exists
    graph.add_conditional_edges(
        "ingest",
        should_proceed,
        {
            "has_order": "classify_issue",
            "missing_order": END  # Will be handled as error in endpoint
        }
    )

    # Linear flow: classify -> prepare_fetch -> fetch_order -> process -> draft
    graph.add_edge("classify_issue", "prepare_fetch")
    graph.add_edge("prepare_fetch", "fetch_order")
    graph.add_edge("fetch_order", "process_fetch_result")
    graph.add_edge("process_fetch_result", "draft_reply")
    graph.add_edge("draft_reply", END)

    return graph.compile()


# Compile graph once at module load
triage_graph = build_graph()


# -----------------------------------------------------------------------------
# FastAPI Endpoints
# -----------------------------------------------------------------------------

class TriageInput(BaseModel):
    ticket_text: str
    order_id: str | None = None


class TriageOutput(BaseModel):
    order_id: str
    issue_type: str
    order: dict
    reply_text: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/triage/invoke", response_model=TriageOutput)
def triage_invoke(body: TriageInput):
    """
    Invoke the LangGraph triage workflow.
    Classifies ticket, fetches order, and drafts reply.
    """
    # Initialize state with input
    initial_state: TriageState = {
        "messages": [],
        "ticket_text": body.ticket_text,
        "order_id": body.order_id,
        "issue_type": None,
        "evidence": None,
        "recommendation": None
    }

    # Run the graph
    result = triage_graph.invoke(initial_state)

    # Handle missing order_id
    if not result.get("order_id"):
        raise HTTPException(
            status_code=400,
            detail="order_id missing and not found in text"
        )

    # Handle order not found
    evidence = result.get("evidence") or {}
    if evidence.get("error"):
        raise HTTPException(status_code=404, detail="order not found")

    return TriageOutput(
        order_id=result["order_id"],
        issue_type=result.get("issue_type", "unknown"),
        order=evidence,
        reply_text=result.get("recommendation", "")
    )


# -----------------------------------------------------------------------------
# Preserve original utility endpoints for backward compatibility
# -----------------------------------------------------------------------------

@app.get("/orders/get")
def orders_get(order_id: str):
    for o in ORDERS:
        if o["order_id"] == order_id:
            return o
    raise HTTPException(status_code=404, detail="Order not found")


@app.get("/orders/search")
def orders_search(customer_email: str | None = None, q: str | None = None):
    matches = []
    for o in ORDERS:
        if customer_email and o["email"].lower() == customer_email.lower():
            matches.append(o)
        elif q and (o["order_id"].lower() in q.lower() or o["customer_name"].lower() in q.lower()):
            matches.append(o)
    return {"results": matches}


@app.post("/classify/issue")
def classify_issue_endpoint(payload: dict):
    text = payload.get("ticket_text", "").lower()
    for rule in ISSUES:
        if rule["keyword"] in text:
            return {"issue_type": rule["issue_type"], "confidence": 0.85}
    return {"issue_type": "unknown", "confidence": 0.1}


@app.post("/reply/draft")
def reply_draft(payload: dict):
    issue_type = payload.get("issue_type", "unknown")
    order = payload.get("order", {})
    template = next(
        (r["template"] for r in REPLIES if r["issue_type"] == issue_type),
        "Hi {{customer_name}}, we are reviewing order {{order_id}}."
    )
    reply = template.replace(
        "{{customer_name}}", order.get("customer_name", "Customer")
    ).replace(
        "{{order_id}}", order.get("order_id", "")
    )
    return {"reply_text": reply}
