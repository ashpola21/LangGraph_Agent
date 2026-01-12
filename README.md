# LangGraph Triage Agent

A minimal LangGraph-based support ticket triage agent that classifies tickets, fetches order data, and drafts replies.

## Architecture

```
┌─────────┐    ┌────────────────┐    ┌───────────────┐    ┌─────────────┐    ┌─────────────────────┐    ┌─────────────┐
│  ingest │───▶│ classify_issue │───▶│ prepare_fetch │───▶│ fetch_order │───▶│ process_fetch_result│───▶│ draft_reply │
└─────────┘    └────────────────┘    └───────────────┘    │  (ToolNode) │    └─────────────────────┘    └─────────────┘
     │                                                     └─────────────┘
     │ (if no order_id)
     ▼
   [END]
```

### State
| Key | Description |
|-----|-------------|
| `messages` | Accumulated messages for tool calls |
| `ticket_text` | Raw support ticket text |
| `order_id` | Order ID (extracted or provided) |
| `issue_type` | Classified issue type |
| `evidence` | Fetched order data |
| `recommendation` | Drafted reply text |

### Nodes
- **ingest**: Extracts `order_id` from ticket text using regex
- **classify_issue**: Classifies issue type via keyword matching
- **fetch_order**: ToolNode that fetches order from mock database
- **draft_reply**: Renders reply using issue-specific templates

## Setup

```bash
# Clone the repo
git clone https://github.com/ashpola21/LangGraph_Agent.git


# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Running the Server

```bash
source venv/bin/activate
uvicorn app.main:app --reload
```

Server runs at `http://127.0.0.1:8000`

## API Usage

### Triage a Ticket

```bash
curl -X POST http://127.0.0.1:8000/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "My order ORD1001 arrived broken, please help!"}'
```

**Response:**
```json
{
  "order_id": "ORD1001",
  "issue_type": "damaged_item",
  "order": {
    "order_id": "ORD1001",
    "customer_name": "Ava Chen",
    "email": "ava.chen@example.com",
    "items": [{"sku": "SKU-101-A", "name": "Wireless Mouse", "quantity": 2}],
    "status": "delivered"
  },
  "reply_text": "Hi Ava Chen, sorry your item arrived damaged. We will send a replacement for order ORD1001."
}
```

### With Explicit Order ID

```bash
curl -X POST http://127.0.0.1:8000/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I want a refund", "order_id": "ORD1002"}'
```

### Health Check

```bash
curl http://127.0.0.1:8000/health
```

## Running Tests

```bash
source venv/bin/activate
pytest tests/ -v
```

## LangSmith Tracing

To enable tracing, create a `.env` file:

```bash
cp .env.example .env
# Edit .env with your LangSmith API key
```

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_api_key_here
LANGCHAIN_PROJECT=langgraph-triage-agent
```

## Project Structure

```
LangGraph_Agent/
├── app/
│   └── main.py           # LangGraph agent + FastAPI endpoints
├── mock_data/
│   ├── orders.json       # Mock order database
│   ├── issues.json       # Issue classification rules
│   └── replies.json      # Reply templates
├── tests/
│   └── test_triage.py    # Unit and integration tests
├── .github/
│   └── workflows/
│       └── ci.yml        # GitHub Actions CI
├── requirements.txt
├── .env.example
└── README.md
```


