# Boot 11 inflight state (2026-09-20)

**Status**: narrate running on H100 (PID 1885), started ~10:24 UTC.

## Configuration

- **Cohort**: JP p=10000 s=2532, generated 30,572 patients
- **Prompt**: Fix A JA deployed (`~/clinosim/clinosim/modules/llm_service/prompts/ja/narrative_seed_bundle.yaml` md5=b8e50dd4)
- **vLLM**: fresh boot, max-num-seqs 64, PC ON, FP16 KV, gdn-prefill triton, VLLM_USE_FLASHINFER_SAMPLER=0
- **narrate**: `--country JP --concurrency 64 --version-id boot11_jp_p10000_s2532`
- **Expected wall clock**: ~5 hours (58,000 docs / 3.4 doc/s JP rate)

## Files on H100

- `/home/ubuntu/boot11_run.sh` — narrate wrapper
- `/home/ubuntu/boot11_run.stdout` — nohup stdout (`wrote N ... elapsed=T` at end)
- `/home/ubuntu/boot11_narrate.log` — narrate stdout (tee)
- `/home/ubuntu/boot11_metrics_before.txt` — vLLM /metrics pre-run
- `/home/ubuntu/boot11_metrics_after.txt` — vLLM /metrics post-run (written by wrapper on exit)
- `/home/ubuntu/vllm_boot11.log` — vLLM server log
- `/home/ubuntu/boot11_gen.log` — cohort gen log
- `/home/ubuntu/boot11_jp_p10000_s2532/cif/` — cohort (1.3GB CIF)

## Resume protocol if session times out

1. SSH: `ssh -i ~/.ssh/sakura_iris_ed25519 ubuntu@133.242.22.166`
2. Check status: `ps -o etime= -p 1885` (still running if PID exists)
3. Live progress: `curl -s http://127.0.0.1:8000/metrics | grep -E '^vllm:(e2e_request_latency_seconds_count|generation_tokens_total)'`
4. If PID 1885 gone: `tail ~/boot11_run.stdout` for elapsed + doc count
5. Shutdown after: pack artifacts to `boot11_artifacts.tar.gz`, scp to Mac, `usacloud server shutdown -y 113801842725`
6. Update `verify/EMPIRICAL_RESULTS.md` with Boot 11 results

## Billing

- H100 booted this session at hour 13 (~10:14 UTC)
- Expected shutdown: hour 18 (~15:30 UTC), ¥4,950 additional
- Cumulative: ¥16,830 across Boot 4-11
