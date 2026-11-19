# LoanDesk AI – Agentic Loan Processing Backend

An AI-powered loan processing system that uses multiple specialized AI agents to automate application intake, document extraction, verification, credit assessment, loan eligibility evaluation, and sanction decisions.

## Overview

LoanDesk AI is a multi-agent loan processing backend built with Python and FastAPI. It uses the OpenAI Agents SDK to coordinate specialized agents through an orchestrated loan processing workflow.

The system also provides a customer-facing AI assistant that helps applicants understand loan policies, upload documents, submit applications, and track application progress.

## Key Features

- **Multi-Agent Orchestration:** A Loan Processing Manager coordinates six specialized AI agents.
- **Application Intake:** Collects applicant details and checks mandatory application information.
- **Document Intelligence:** Extracts and classifies information from PAN, Aadhaar, salary slips, ITRs, property documents, vehicle quotations, and business proofs.
- **Document Verification:** Cross-checks extracted information against application details.
- **Credit Assessment:** Evaluates CIBIL scores and existing loan obligations.
- **Loan Eligibility:** Calculates EMI and FOIR against configured lending policies.
- **Decision Management:** Records loan approval or rejection decisions.
- **Human-in-the-Loop:** Saves decision emails as drafts for human review and sending.
- **Application Tracking:** Tracks individual agent progress, application status, and processing logs.
- **AI Loan Assistant:** Supports multi-turn customer conversations and document uploads.

## Agent Architecture

The system uses six specialized agents coordinated by a central orchestrator.

| Agent | Responsibility |
|---|---|
| Email Intake Agent | Checks application email and mandatory details |
| Document Extraction Agent | Extracts structured information from uploaded documents |
| Document Verification Agent | Cross-checks applicant and document information |
| Credit Assessment Agent | Retrieves credit score and existing obligations |
| Eligibility & Risk Agent | Calculates EMI, FOIR, and risk grade |
| Sanction / Decision Agent | Records the final decision and prepares the sanction or rejection letter |

**Loan Processing Manager:** Coordinates the agents, delegates tasks, handles workflow decisions, and produces the final processing summary.

**Loan Assistant:** Interacts with customers, helps collect information, identifies loan types from documents, and submits applications after customer confirmation.

## Technology Stack

- Python
- FastAPI
- OpenAI Agents SDK
- OpenAI GPT-4o-mini (default model)
- MySQL
- SQLite session storage
- PyMySQL
- PyPDF
- Uvicorn
- Python-dotenv

## Document Processing

Supported document formats include:

- PDF
- PNG
- JPG / JPEG
- WEBP
- TXT

Document classification supports:

- PAN Card
- Aadhaar
- Salary Slip / ITR / Bank Statement
- Property Documents
- Vehicle Quotations
- Business Proof (GST / Udyam)

Image documents are processed using an OpenAI vision model. PDF text is extracted using PyPDF. The system also includes Aadhaar-like number masking before storing chat-uploaded document text.

## Loan Eligibility Policy

The current configured policy includes:

| Parameter | Policy |
|---|---|
| Minimum CIBIL Score | 700 |
| Maximum FOIR | 50% |
| Maximum Loan Amount | ₹25,00,000 |
| Minimum Tenure | 6 months |
| Maximum Tenure | 84 months |
| Interest Rate for CIBIL ≥ 780 | 10.5% p.a. |
| Interest Rate for CIBIL 700–779 | 12.6% p.a. |

These are configurable example policy rules implemented in the project, not actual bank lending terms.

## Processing Workflow

1. Applicant submits a loan application.
2. Application details and documents are stored.
3. The processing scheduler receives the application.
4. The Loan Processing Manager delegates tasks to specialist agents.
5. Documents are extracted and verified.
6. Credit score and existing obligations are assessed.
7. EMI and FOIR are calculated.
8. The final decision is recorded.
9. A sanction or rejection email draft is prepared for human review.
10. Application progress and logs remain available through the API.

## API Overview

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/applications` | Create a loan application |
| GET | `/api/applications` | List applications |
| GET | `/api/applications/{app_id}` | View application details |
| POST | `/api/applications/{app_id}/send-email` | Send reviewed decision email |
| GET | `/api/drafts` | Retrieve decision email drafts |
| POST | `/api/chat` | Interact with the AI loan assistant |
| POST | `/api/chat/upload` | Upload loan documents |
| GET | `/api/chat/state` | Retrieve chat application readiness |
| GET | `/api/scheduler` | View scheduler status |
| GET | `/api/health` | Health check |

## Project Structure

```text
loandesk-backend/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── agent_definitions.py
│   ├── pipeline.py
│   ├── applications.py
│   ├── tools.py
│   ├── chat_tools.py
│   ├── docreader.py
│   ├── db.py
│   ├── email_service.py
│   └── task_scheduler.py
│
├── schema.sql
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

*The structure above represents the main backend modules; update it to match the final repository contents.*

## Setup and Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/loandesk-ai-backend.git
cd loandesk-ai-backend
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

**Windows**
```bash
.venv\Scripts\activate
```

**macOS / Linux**
```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and configure your local settings.

Required configuration includes:

```env
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=loandesk

CORS_ORIGINS=http://localhost:3000
```

Never commit your actual `.env` file or API keys.

### 5. Initialize MySQL

Create a MySQL user and database with permissions to create and modify the required tables. The application initializes the schema and runs migrations during startup.

### 6. Start the backend

```bash
uvicorn app.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

## Important Implementation Notes

- The current CIBIL score function is a simulated implementation and must be integrated with an authorized credit bureau service for real-world use.
- The default application endpoint can generate mock documents when no documents are supplied. Customer document uploads are handled separately through the chat upload endpoint.
- The email workflow prepares drafts for human review; SMTP delivery occurs when the reviewer triggers the send endpoint.
- Existing loan EMI calculations use the configured fixed rate in the current implementation.
- This repository is a development project and is not a production-ready lending or credit decision platform.

## Security Considerations

- Keep API keys and database credentials in environment variables.
- Do not commit real applicant information or uploaded identity documents.
- Review access controls, authentication, authorization, encryption, and audit requirements before production deployment.
- Use authorized services for credit bureau integration.

## Author

**Roobini Supraja**

B.Tech – Artificial Intelligence and Data Science

AI/ML Engineer | Machine Learning | Agentic AI | Computer Vision

---

*LoanDesk AI – Automating loan processing through intelligent multi-agent workflows.*