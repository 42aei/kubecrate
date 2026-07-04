# Validation status app on kind-dev-misc-local

This cluster binding enables the `validation-status` application service fixture through GitOps-managed operation on the kind-first local path.

AI-runnable validation after reconciliation:

```sh
kubectl --context kind-kind-dev-misc-local -n validation-status wait --for=condition=Available deployment/validation-status --timeout=180s
kubectl --context kind-kind-dev-misc-local -n validation-status port-forward svc/validation-status 18080:80 >/tmp/kubecrate-validation-status-port-forward.log 2>&1 &
PF_PID=$!
trap 'kill ${PF_PID}' EXIT
python3 - <<'PY'
import json
import time
from urllib.request import urlopen

for _ in range(30):
    try:
        payload = json.load(urlopen('http://127.0.0.1:18080/status.json', timeout=2))
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit('validation status JSON endpoint was not reachable')

required_top = {'app', 'version', 'overallStatus', 'checks'}
missing_top = required_top - payload.keys()
if missing_top:
    raise SystemExit(f'missing top-level fields: {sorted(missing_top)}')

required_check = {'id', 'name', 'state', 'capability', 'area', 'enabled', 'summary', 'troubleshooting'}
allowed_states = {'green', 'yellow', 'red', 'not_configured'}
checks = payload.get('checks')
if not isinstance(checks, list) or not checks:
    raise SystemExit('checks must be a non-empty list')
for check in checks:
    missing = required_check - check.keys()
    if missing:
        raise SystemExit(f"check {check.get('id', '<unknown>')} missing fields: {sorted(missing)}")
    if check['state'] not in allowed_states:
        raise SystemExit(f"check {check['id']} has invalid state {check['state']!r}")
base = next((check for check in checks if check['id'] == 'base-app-health'), None)
if not base or base['state'] != 'green' or base['enabled'] is not True:
    raise SystemExit('base-app-health must be enabled and green')
for check in checks:
    if check['id'] != 'base-app-health' and check['state'] != 'not_configured':
        raise SystemExit(f"future platform service check {check['id']} must be not_configured in this slice")
print(json.dumps({'app': payload['app'], 'version': payload['version'], 'overallStatus': payload['overallStatus'], 'checks': len(checks)}, indent=2))
PY
curl -fsS http://127.0.0.1:18080/ >/tmp/kubecrate-validation-status.html
```

The app intentionally uses port-forwarding until a later ingress slice enables an ingress reachability check.
