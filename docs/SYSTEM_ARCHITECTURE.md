# EvidenceDesk system architecture

The diagrams show the architecture implemented in this checkout. Dashed arrows indicate optional integrations or deployment-specific paths.

## System overview

```mermaid
flowchart LR
    User["Authors, reviewers and admins"]
    IdP["OIDC identity provider"]
    MCPHost["External MCP host"]
    Operator["Operator / CLI"]

    subgraph Clients["Client and protocol entry points"]
        UI["React / TypeScript browser app<br/>Evidence, import, review, workflow and export"]
        Proxy["Vite development proxy<br/>Same-origin /api"]
        API["FastAPI / Uvicorn<br/>Session, evidence, questionnaire, retrieval and workflow APIs"]
        MCP["MCP stdio server<br/>Scoped search, questionnaire reads and draft submission"]
    end

    subgraph App["Application services"]
        Auth["Access controls<br/>JWT / JWKS, tenant membership, roles and source ACLs<br/>Local API-key mode for development"]
        Evidence["Evidence lifecycle<br/>Text ingestion, versions, approval, revocation and expiry"]
        Workbook["Workbook service<br/>XLSX preflight, mapping, import and export"]
        Review["Questionnaire and review service<br/>Extractive baseline, revisions, citations and approvals"]
        Graph["LangGraph drafting<br/>Bounded advances and human review"]
        Worker["Isolated phase processes<br/>Retrieval and drafting with hard cutoffs"]
        Retrieval["Retrieval foundation<br/>Authorized corpus, exact chunks, lexical / vector / hybrid"]
    end

    subgraph Data["Data and provider adapters"]
        SQL[("Authoritative SQLite<br/>Evidence, ACLs, audit, original XLSX, revisions,<br/>approvals, export snapshots and job / phase ledgers")]
        Checkpoint[("SQLite workflow sidecar<br/>Graph checkpoints and cancellation control")]
        Memory["In-memory retrieval index<br/>Optional scoped ID cache in retrieval service"]
        PG[("Optional PostgreSQL / pgvector<br/>Rebuildable derived index")]
        Model["Deterministic fixture providers"]
        Gateway["Optional trusted HTTPS model gateway"]
    end

    User --> UI
    IdP -. "Access tokens" .-> UI
    UI --> Proxy --> API
    MCPHost -->|"stdio"| MCP
    Operator -->|"Admin, retrieval rebuild, workflow step"| App
    API --> Auth
    MCP --> Auth
    Auth --> SQL
    API --> Evidence & Workbook & Review & Graph & Retrieval
    MCP --> Retrieval & Review
    Evidence --> SQL
    Workbook --> SQL
    Review --> SQL
    Review -. "Opt-in foundation drafting" .-> Retrieval
    Graph --> SQL & Checkpoint & Worker
    Graph -->|"Publishes unapproved revision"| Review
    Worker --> Retrieval
    Retrieval -->|"Rechecks source authority and provenance"| SQL
    Retrieval --> Memory & Model
    Retrieval -.-> PG & Gateway

    classDef primary fill:#e7f0ff,stroke:#345f9e,color:#102849
    class API,Graph,SQL primary
```

## Workbook and evidence lifecycle

```mermaid
flowchart TD
    Text["UTF-8 evidence upload"] --> Pending["Pending immutable evidence version"] --> ApprovedEvidence["Evidence approval"]
    Original["Source XLSX"] --> Preflight["Bounded multipart / ZIP / XML validation and openpyxl inspection"]
    Preflight --> Mapping["Explicit per-sheet mapping and preview"]
    Mapping --> Import["Idempotent import<br/>Immutable workbook and source-cell provenance"]
    Import --> Item["Questionnaire item"]
    Item --> Baseline["Deterministic extractive baseline"]
    Item -.-> Foundation["Opt-in retrieval foundation draft"]
    Item -.-> Graph["LangGraph<br/>Classify → retrieve → assess → draft → verify"]
    ApprovedEvidence --> Baseline & Foundation & Graph
    Baseline & Foundation & Graph --> Revision["Unapproved revision with citations"]
    Revision --> Human["Reviewer checks provenance, edits and explicitly approves current revision"]
    Human --> Export["Export rechecks current revision, access and evidence<br/>Writes approved answers into a workbook copy"]
    Export --> Bundle["Download ZIP<br/>Completed XLSX, unresolved CSV and JSON manifest"]
    Export --> Receipt["Persisted export receipt"]
    Change["Evidence version, revocation, expiry or ACL change"] -->|"Can invalidate dependencies"| Human & Export
```

## Optional protocols, deployment and verification

```mermaid
flowchart TD
    subgraph Optional["Optional integrations and experiments"]
        A2AClient["Standalone A2A questionnaire service"]
        A2AExpert["Standalone A2A evidence expert"]
        A2ACorpus[("Shared authoritative SQLite<br/>Evidence and expert tasks")]
        Graph["Primary LangGraph workflow"]
        AutoGen["AutoGen researcher / writer / verifier experiment"]
        DSPy["DSPy optimization and provider-routing comparisons"]
        A2AClient -->|"A2A 1.0 JSON-RPC discovery, task and artifact"| A2AExpert
        A2AClient -->|"Verifies returned provenance and injects scoped evidence"| Graph
        A2AClient & A2AExpert -->|"OIDC-scoped evidence access"| A2ACorpus
    end

    subgraph Runtime["Deployment and operations"]
        Local["Local Compose<br/>Loopback API and persistent /data volume"]
        Staging["Staging Compose recipe<br/>Loopback API, prepared /data and trusted JWKS"]
        TLS["Operator-managed TLS proxy"]
        Container["Non-root Python API image<br/>Readiness probe and read-only container recipe"]
        Persist[("Persistent SQLite and workflow sidecar")]
        Trace["Content-free local tracing"]
        LangSmith["Optional explicit LangSmith export"]
        Backup["Operator backup / restore<br/>Preserve the SQLite database and sidecar together"]
        Local & Staging --> Container
        TLS -.-> Staging
        Container --> Persist & Trace
        Trace -.-> LangSmith
        Backup --> Persist
    end

    subgraph Verification["GitHub Actions and local checks"]
        CI["CI workflow"]
        Checks["Backend tests, frontend build / tests, Playwright,<br/>HTTP smoke, protocol demos, evaluations and dependency checks"]
        Fixtures["Synthetic workbooks, signed OIDC fixtures and evaluation datasets"]
        CI --> Checks
        Fixtures --> Checks
        AutoGen & DSPy --> Checks
    end
```

The staging recipe covers the API. The frontend build expects a same-origin production `/api` route, whose hosting remains operator work. The repository records local synthetic validation and lists live IdP, paid providers, and Docker/staging rollback among the unverified external gates.

Repository references: [FastAPI entry point](../app/main.py), [frontend](FRONTEND.md), [access](ACCESS.md), [workbooks](WORKBOOKS.md), [retrieval](RETRIEVAL.md), [workflows](WORKFLOWS.md), [MCP](MCP.md), [A2A](A2A.md), [AutoGen](AUTOGEN.md), [operations](OPERATIONS.md), [CI](../.github/workflows/ci.yml).

