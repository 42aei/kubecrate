# Validation status UI surface style

The existing surface is a shadcn/ui-inspired dark operations dashboard: slate background, rounded card surfaces, subtle borders, muted secondary text, green/sky semantic badges, chart-like progress bars, and ConfigMap-driven check details. The product context is GitOps readiness evidence, not marketing; the UI should optimize for trust, scan speed, and drill-down evidence.

Hard constraints inherited from repo docs:

- Base the UI on shadcn/ui framework/component language.
- Graphs and interactive overview modules must be based on shadcn/ui chart modules / Recharts-backed patterns when promoted to React.
- Keep monitored resources ConfigMap-driven and backed by live Kubernetes API output.
