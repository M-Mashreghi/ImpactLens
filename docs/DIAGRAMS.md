# ImpactLens Diagrams

Mermaid diagrams for **ImpactLens — Financial News → Portfolio Impact Engine**.

**Related documents:** [ARCHITECTURE.md](./ARCHITECTURE.md) · [ROADMAP.md](./ROADMAP.md) · [PHASES.md](./PHASES.md)

---

## 1. System Architecture

```mermaid
flowchart TB
    USER[Analyst / Investor]
    NEWS[News Sources\nRSS / HTTP / Manual]
    PORT[Portfolio CSV / Snapshot]

    subgraph IMPACTLENS[ImpactLens]
        ING[News Ingestion]
        NORM[Normalize + Deduplicate]
        LLM[Structured LLM Event Analyzer]
        ER[Entity / Security Resolver]
        PF[Portfolio Service]
        EXP[Exposure Engine]
        SCORE[Deterministic Impact Scorer]
        EXPL[Explanation + Evidence]
        DB[(SQLite)]
        API[FastAPI]
        UI[Streamlit Dashboard]
        JOBS[Scheduler / Jobs]
        MD[Market Data Adapter]
        RES[Event Study / Historical Analogs]
        ALERT[Alert Service]
    end

    NEWS --> ING --> NORM --> LLM --> ER
    PORT --> PF
    ER --> EXP
    PF --> EXP
    EXP --> SCORE --> EXPL
    EXPL --> DB
    NORM --> DB
    LLM --> DB
    PF --> DB
    SCORE --> DB
    DB --> API --> UI --> USER
    JOBS --> ING
    SCORE --> ALERT --> USER
    SCORE --> RES
    MD --> RES
    RES --> DB
```

---

## 2. End-to-End News Impact Sequence

```mermaid
sequenceDiagram
    autonumber
    participant S as News Source
    participant I as Ingestion
    participant D as Deduplicator
    participant A as LLM Analyzer
    participant E as Entity Resolver
    participant P as Portfolio Service
    participant X as Exposure Engine
    participant C as Impact Scorer
    participant DB as SQLite
    participant U as Dashboard/Alert

    S->>I: New article/headline
    I->>I: Capture source + timestamps
    I->>D: Normalize text + metadata
    D->>DB: Check hash/canonical link

    alt Duplicate
        D->>DB: Link to canonical news
        D-->>I: Skip duplicate analysis
    else New item
        D->>DB: Persist canonical news
        D->>A: Structured event analysis
        A-->>D: Event + entities + evidence
        D->>DB: Persist analysis/version
        D->>E: Resolve proposed entities
        E->>DB: Read security master
        E-->>D: Canonical entities/securities
        D->>P: Load target portfolio snapshot
        P-->>D: Holdings + weights
        D->>X: Event + holdings + relationships
        X-->>D: Exposure matches
        D->>C: Score components
        C-->>D: Deterministic impact result
        D->>DB: Persist impact + components
        D->>U: Feed/alert if threshold met
    end
```

---

## 3. Portfolio Exposure Mapping

```mermaid
flowchart LR
    EVT[Validated News Event]
    ENT[Resolved Entity / Factor]
    DIRECT[Direct Holding]
    SECTOR[Sector / Industry]
    COUNTRY[Country / Geography]
    MACRO[Macro / Commodity Factor]
    REL[Verified Relationship Graph]
    POS[Portfolio Position]
    MATCH[Exposure Match]

    EVT --> ENT
    ENT --> DIRECT --> POS
    ENT --> SECTOR --> POS
    ENT --> COUNTRY --> POS
    ENT --> MACRO --> POS
    ENT --> REL --> POS
    POS --> MATCH

    note1[Every non-direct path requires\nstored relationship metadata/provenance]
    REL -.-> note1
    SECTOR -.-> note1
    COUNTRY -.-> note1
    MACRO -.-> note1
```

---

## 4. Impact Score Decomposition

```mermaid
flowchart LR
    W[Position Exposure\nweight/notional]
    R[Relationship Weight]
    S[Event Severity]
    C[Confidence]
    Q[Relevance]
    D[Direction Sign]
    COMP[Position Component]
    AGG[Portfolio Impact Score]
    LEVEL[Priority Level]

    W --> COMP
    R --> COMP
    S --> COMP
    C --> COMP
    Q --> COMP
    D --> COMP
    COMP --> AGG --> LEVEL
```

Conceptual only. The exact formula is versioned in code/config and must be covered by numerical fixtures.

---

## 5. News Processing State Machine

```mermaid
stateDiagram-v2
    [*] --> Discovered
    Discovered --> Fetched: fetch metadata/text
    Fetched --> Normalized: clean + hash
    Normalized --> Duplicate: canonical duplicate found
    Normalized --> PendingAnalysis: unique item
    PendingAnalysis --> Analyzed: valid structured output
    PendingAnalysis --> Uncertain: insufficient/ambiguous evidence
    PendingAnalysis --> Failed: provider/schema failure after policy
    Analyzed --> Resolved: entity resolution complete
    Resolved --> Scored: portfolio impact computed
    Scored --> Alerted: threshold + alert policy
    Scored --> [*]: no alert required
    Alerted --> [*]
    Duplicate --> [*]
    Uncertain --> [*]
    Failed --> [*]
```

---

## 6. LLM Analysis Boundary

```mermaid
flowchart TB
    TXT[Untrusted Article Text]
    PROMPT[Versioned Prompt + Schema]
    LLM[LLM Provider]
    JSON[Structured Candidate Output]
    SCHEMA[Pydantic Validation]
    EVID[Evidence Validation]
    VALID[Validated Event Analysis]
    UNC[Uncertain / Failed]

    TXT --> PROMPT --> LLM --> JSON --> SCHEMA
    SCHEMA -->|valid| EVID
    SCHEMA -->|invalid after retry| UNC
    EVID -->|supported| VALID
    EVID -->|unsupported claims| UNC
```

---

## 7. Historical Event Study Flow

```mermaid
flowchart LR
    NEWS[News Event\npublished_at]
    CAL[Exchange Calendar\n+ Timezone]
    ANCHOR[Event Anchor Session]
    PRICES[Market Data]
    BENCH[Benchmark Data]
    WIN[Configured Event Window]
    RET[Security Return]
    BRET[Benchmark Return]
    AR[Abnormal Return]
    RESULT[Stored Event Study]

    NEWS --> CAL --> ANCHOR --> WIN
    PRICES --> RET
    BENCH --> BRET
    WIN --> RET
    WIN --> BRET
    RET --> AR
    BRET --> AR --> RESULT
```

---

## 8. Point-in-Time Guard

```mermaid
flowchart TB
    T[Historical Evaluation Time T]
    P[Portfolio Snapshot <= T]
    N[News published <= T]
    F[Features available <= T]
    M[Market observations allowed by window]
    EVAL[Evaluation Dataset]

    T --> P --> EVAL
    T --> N --> EVAL
    T --> F --> EVAL
    T --> M --> EVAL

    FUTURE[Future data > T]
    FUTURE -. blocked .-> EVAL
```

---

## 9. Dashboard Information Flow

```mermaid
flowchart LR
    DB[(SQLite)]
    API[FastAPI]
    FEED[Impact Feed]
    DETAIL[News Detail]
    PORT[Portfolio View]
    HIST[Historical Context]
    ALERT[Alerts]

    DB --> API
    API --> FEED
    API --> DETAIL
    API --> PORT
    API --> HIST
    API --> ALERT
```

---

## 10. Deployment Diagram

```mermaid
flowchart TB
    subgraph HOST[Single Host / Docker Compose]
        API[ImpactLens API]
        UI[Streamlit UI]
        JOB[Scheduler / Worker]
        DB[(SQLite Volume)]
        CACHE[(Bounded Market Cache)]
    end

    NEWS[External News Sources]
    LLM[LLM Provider]
    MD[Market Data Provider]
    USER[User Browser]

    USER --> UI
    UI --> API
    API --> DB
    JOB --> DB
    JOB --> NEWS
    JOB --> LLM
    JOB --> MD
    JOB --> CACHE
    API --> CACHE
```

---

## Diagram Maintenance

- Keep state names aligned with `ARCHITECTURE.md` and implementation.
- Update scoring diagrams when the scoring equation/component model changes.
- Do not add an indirect exposure path without documenting its provenance model.
- Update historical diagrams if event-time/session rules change.
- 2026-10-13: diagrams reviewed against the v1 implementation (state names match `NewsStatus`; deployment matches `docker-compose.yml`).
