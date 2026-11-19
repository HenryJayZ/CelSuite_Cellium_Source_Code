# Architectural Decisions

- **2026-09-21: Phase 1/2 Design Setup**
  - Adopted strict downwards-dependency layered architecture (`UI` -> `Services` -> `Core`).
  - Imposed a soft 500-line limit per file to maintain extreme modularity and readability.
  - Mandated zero logic/behavioral changes during the extraction phase to minimize regression risk. Absolute imports (`from cellium.core...`) will be used exclusively.
