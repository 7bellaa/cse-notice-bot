# PNU CSE Discord Bot — Data Flow

본 문서는 한 실행 사이클 동안의 데이터 흐름과 모듈 간 상호작용을 시각화합니다.

## 1. 전체 실행 흐름 (End-to-End Pipeline)

```mermaid
flowchart TD
    A[launchd<br/>09:00 / 18:00 KST] -->|spawn process| B[main.py<br/>한 사이클 실행]

    B --> C[config.py<br/>config.toml + .env 로드]
    C --> D{설정 유효?}
    D -- No --> X1[로그 기록 후<br/>exit 1]
    D -- Yes --> E[state.py<br/>state.json 로드]

    E --> F{state.json<br/>존재?}
    F -- No --> G[베이스라인 모드<br/>last_max_post_id = null]
    F -- Yes --> H[last_max_post_id 로드]

    G --> I[fetcher.py<br/>HTML 다운로드<br/>page=1]
    H --> I

    I --> J[parser.py<br/>HTML → List Post]
    J --> K{min post_id<br/>> last_max_id?}

    K -- Yes --> L[fetcher.py<br/>page=2 추가 fetch]
    L --> M[parser.py<br/>parse page=2]
    M --> N[posts 합치기]
    K -- No --> N

    N --> O[differ.py<br/>새 글 식별<br/>id 오름차순 정렬]

    O --> P{베이스라인<br/>모드?}
    P -- Yes --> Q[알림 스킵<br/>현재 max_id 저장]
    P -- No --> R{새 글 있음?}

    R -- No --> S[로그: '신규 없음']
    R -- Yes --> T[notifier.py<br/>각 글마다 webhook POST]

    T --> U{전송 성공?}
    U -- Yes --> V[state.py<br/>워터마크 갱신<br/>= 방금 보낸 post.id]
    U -- No --> W[로그 기록 후<br/>다음 사이클 재시도]

    V --> Y{남은 글 있음?}
    Y -- Yes --> T
    Y -- No --> Z[정상 종료 exit 0]

    Q --> Z
    S --> Z

    style A fill:#ffd54f,stroke:#000
    style Z fill:#81c784,stroke:#000
    style X1 fill:#e57373,stroke:#000
    style W fill:#e57373,stroke:#000
    style P fill:#ba68c8,stroke:#000
    style U fill:#ffb74d,stroke:#000
```

## 2. 컴포넌트 의존 관계 (Module Dependencies)

```mermaid
flowchart LR
    main[main.py<br/>orchestrator]

    main --> config[config.py]
    main --> fetcher[fetcher.py]
    main --> parser[parser.py]
    main --> differ[differ.py]
    main --> notifier[notifier.py]
    main --> state[state.py]
    main --> log[logging_setup.py]

    parser --> models[models.py<br/>Post, BoardConfig]
    differ --> models
    notifier --> models
    state --> models
    config --> models

    fetcher -.HTTP GET.-> ext1[(cse.pusan.ac.kr)]
    notifier -.HTTP POST.-> ext2[(Discord Webhook)]
    state -.read/write.-> ext3[(data/state.json)]
    config -.read.-> ext4[(config.toml + .env)]
    log -.write.-> ext5[(logs/*.log)]

    style main fill:#64b5f6,stroke:#000
    style models fill:#fff176,stroke:#000
    style parser fill:#aed581,stroke:#000
    style differ fill:#aed581,stroke:#000
    style fetcher fill:#ffb74d,stroke:#000
    style notifier fill:#ffb74d,stroke:#000
    style state fill:#ffb74d,stroke:#000
    style config fill:#ffb74d,stroke:#000
```

**범례:**
- 🟢 초록: **순수 함수** (I/O 없음, 결정론적, 테스트 쉬움)
- 🟠 주황: **I/O 모듈** (네트워크, 파일 시스템 접근)
- 🔵 파랑: **오케스트레이터**
- 🟡 노랑: **데이터 모델**

## 3. 시퀀스 다이어그램 (정상 케이스, 신규 글 2개)

```mermaid
sequenceDiagram
    participant LD as launchd
    participant M as main.py
    participant C as config.py
    participant S as state.py
    participant F as fetcher.py
    participant P as parser.py
    participant D as differ.py
    participant N as notifier.py
    participant W as Discord Webhook

    LD->>M: spawn (09:00 KST)
    M->>C: load_config()
    C-->>M: Config(boards, webhook_url)
    M->>S: load_state()
    S-->>M: last_max_post_id = 19234

    M->>F: get(board_url, page=1)
    F-->>M: html
    M->>P: parse(html)
    P-->>M: [post 19236, 19235, 19234, 19233, ...]

    Note over M,P: min_id(19233) ≤ 19234 → page 2 불필요

    M->>D: diff(posts, watermark=19234)
    D-->>M: new_posts = [19235, 19236] (오름차순)

    loop 각 신규 글
        M->>N: send(post)
        N->>W: POST webhook
        W-->>N: 204 No Content
        N-->>M: ok
        M->>S: update_watermark(post.id)
        S-->>M: ok
    end

    M->>LD: exit 0
```

## 4. 상태 저장 구조 (State Schema)

```mermaid
flowchart TB
    subgraph state["data/state.json"]
        boards["boards (object)"]
        boards --> b14221["'14221': BoardState"]
        b14221 --> wm["last_max_post_id: int"]
        b14221 --> ts["last_checked: ISO8601"]
    end

    subgraph future["향후 확장 시"]
        boards2["boards (object)"]
        boards2 --> b14221b["'14221': ..."]
        boards2 --> b14222["'14222': ..."]
        boards2 --> b14223["'14223': ..."]
    end

    state -.확장.-> future
```

```json
// 현재 (단일 게시판)
{
  "boards": {
    "14221": {
      "last_max_post_id": 19234,
      "last_checked": "2026-04-30T18:00:00+09:00"
    }
  }
}

// 미래 (다중 게시판)
{
  "boards": {
    "14221": { "last_max_post_id": 19234, "last_checked": "..." },
    "14222": { "last_max_post_id":  8721, "last_checked": "..." }
  }
}
```

## 5. 핵심 데이터 모델

```mermaid
classDiagram
    class Post {
        +int id
        +str title
        +str author
        +str date
        +str url
        +str category
        +bool has_attachment
    }

    class BoardConfig {
        +str id
        +str name
        +str url
        +str webhook_env
    }

    class BoardState {
        +int last_max_post_id
        +str last_checked
    }

    class Config {
        +list~BoardConfig~ boards
        +str log_dir
        +int max_pages
    }

    Config "1" *-- "*" BoardConfig
```

## 6. 설계 불변식 (Invariants)

다이어그램으로는 표현 어렵지만 코드/테스트가 보장해야 할 규칙:

1. **워터마크 단조 증가** — `state.last_max_post_id`는 절대 감소하지 않는다.
2. **알림 → 갱신 순서** — webhook POST 성공 응답을 받은 *뒤에만* 워터마크를 갱신한다.
3. **오름차순 전송** — 신규 글은 항상 post_id 오름차순으로 전송한다 (오래된 글부터).
4. **베이스라인 무알림** — 첫 실행 시 알림 0건, 워터마크만 저장한다.
5. **페이지 상한** — 한 사이클당 최대 2페이지까지만 fetch한다.
6. **부분 실패 보존** — 알림 도중 실패 시 이미 보낸 것까지는 워터마크에 반영, 실패 지점부터 다음 사이클에서 재시도한다.
