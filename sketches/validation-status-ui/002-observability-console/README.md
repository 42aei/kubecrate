## Variant: Observability console

### Design stance
A monitoring-console view: timeline, pipeline topology, and signal panels foreground Flux reconciliation flow.

### Key choices
- Layout: distinct console layout for validation status.
- Typography: shadcn-like system UI, clear labels, scan-first hierarchy.
- Color: dark shadcn surface with semantic accent.
- Interaction: filters and clickable check rows.

### Trade-offs
- Strong at: debugging Flux failures and explaining where a reconciliation path broke.
- Weak at: less polished for non-technical demos.

### Best for
- debugging Flux failures and explaining where a reconciliation path broke
