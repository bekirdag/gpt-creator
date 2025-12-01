You are Codex, acting as the lead systems architect. Draft a System Design Specification (SDS) that realises the Product Requirements Document (PDR) provided below, without assuming any particular stack or surface.

Process:
1. Read the PDR excerpt to understand product goals and constraints.
2. Identify only the architecture domains that the PDR calls for (e.g., CLI/daemon, library, API, UI, data/storage, integrations, deployment/runtime, operability). If a domain is not mentioned, mark it out of scope rather than inventing it.
3. Decompose each applicable domain into progressively detailed sections and subsections. Include data stores, APIs, deployment, observability, security, and runbooks only when the PDR requires them.
4. Before writing narrative content, output a complete SDS table of contents ordered from high-level architecture down to implementation and operations details that are in scope.

Respond with strict JSON using this schema:
{
  "document_title": "System Design Specification",
  "sections": [
    {
      "title": "Top-level heading",
      "summary": "1-3 sentence synopsis of scope",
      "subsections": [
        {
          "title": "Sub heading",
          "summary": "Short summary",
          "subsections": [
            {
              "title": "Nested heading",
              "summary": "Short summary"
            }
          ]
        }
      ]
    }
  ]
}

Rules:
- Order sections top-down: architecture overview → components/interaction model → data & storage (only if present) → interfaces/contracts → runtime/operations → testing/quality/risk.
- Provide 4–7 top-level sections that reflect the PDR; skip domains that are out of scope.
- Populate subsection arrays when deeper guidance is needed; leave empty when no additional breakdown is required.
- Output JSON only.

## PDR Excerpt
