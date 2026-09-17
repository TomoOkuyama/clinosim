# Sakura H100 VM operational reference (S117 verify)

## Current state (2026-09-17)

| Field | Value |
|---|---|
| VM name | `clinosim-bench-h100` |
| VM ID | `113801842725` |
| Zone | `is1a` |
| IP address | `133.242.22.166/24` |
| Current status | `down` |
| SSH key (local) | `~/.ssh/sakura_iris_ed25519` |

**IP note**: `usacloud server list` shows the IP even when the VM is
down. Resume-prompt earlier claimed "IP は起動毎に変わる" but the
current allocation appears stable. Verify via `usacloud server list`
after boot before setting SSH config.

## Ops commands

### Boot
```bash
usacloud server boot -y --zone=is1a clinosim-bench-h100
# Wait ~2-5 min for SSH ready.
```

### Get IP (after boot)
```bash
usacloud server list --zone=is1a --output-type=json \
  | jq -r '.[] | select(.Name=="clinosim-bench-h100") | .IPAddress'
```

### SSH (assuming IP = 133.242.22.166)
```bash
ssh -i ~/.ssh/sakura_iris_ed25519 \
    -o StrictHostKeyChecking=accept-new \
    ubuntu@133.242.22.166
```

Or a persistent `~/.ssh/config` alias:
```
Host sakura
    HostName 133.242.22.166
    User ubuntu
    IdentityFile ~/.ssh/sakura_iris_ed25739
    StrictHostKeyChecking accept-new
```
Then `ssh sakura`.

### Shutdown (STOPS BILLING — do this immediately after verify)
```bash
usacloud server shutdown -y --zone=is1a clinosim-bench-h100
```

### Wait for shutdown to complete
```bash
until usacloud server read --zone=is1a clinosim-bench-h100 --output-type=json \
    | jq -r '.InstanceStatus' | grep -q down; do
    sleep 5
done
```

## Billing note

Sakura H100 (`clinosim-bench-h100`) is billed **hourly** — every boot
consumes a full hour whether we use 5 min or 55 min. See
`[[feedback_hourly_billed_gpu_use_full_hour]]`. Design each verify boot
to fill the hour: cleanup + 6 cases + shutdown should all fit within one
hour (~30 min actual work, ~30 min buffer).

Costs (2026 rates):
- H100 1x  = **¥990 / hour**
- Estimated 1-hour verify: ~¥990
- Fallback (2-hour): ¥1980

## SCP file transfer

Before boot, prepare a tarball of the verify/ dir to scp up in one go:

```bash
cd ~/workspace/clinosim
tar --exclude='verify/out' -czf /tmp/verify_bundle.tar.gz verify/
# after boot:
scp /tmp/verify_bundle.tar.gz sakura:~/verify_bundle.tar.gz
ssh sakura 'mkdir -p ~/verify && tar -xzf ~/verify_bundle.tar.gz -C ~ && ls ~/verify/'
```

## Clock sync (Time sync between Mac and H100)

The measurement combines client-side (Mac) wall-clock and server-side
(H100) `/v1/metrics` counters. If the two clocks drift, per-doc latency
attribution breaks.

Check before running cases:
```bash
ssh sakura 'date -u +%s'; date -u +%s
# Expect difference < 5 seconds
```

If drift > 5s: `ssh sakura 'sudo systemctl restart chrony'` or ntpdate.
