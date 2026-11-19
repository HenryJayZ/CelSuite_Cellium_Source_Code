# 🚀 PHASE 3 - Enhance button states + Warm-cache v2 (Kaggle mailbox)

> `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` human/live-only

## A. ✨ Enhance button state machine (PHASE_3_ADDENDUM)
- [ ] Typed errors from `enhance_with_model` (rate_limit / auth / network)
- [ ] Button states on the button itself: idle → working "✨ Pinging <model>…" (animated dots, QThread, click=cancel) → rate-limited auto-retry (max 3, backoff, "retry n/3 in Xs") → error "↻ Retry enhance" (accent) → success flash "✅ Enhanced" 1.5s → idle
- [ ] Store `_pre_enhance_prompt` before enhancing; retries use original (no stacking); user edit clears retry; local fallback = instant (skip working)
- [ ] Elapsed seconds in tooltip while working
- [ ] Tests: rate-limit retry cycle, network-error retry-once-from-original, UI not frozen (processEvents fires), cancel mid-work → idle + prompt untouched

## B. 🔥 Warm-cache v2 - watcher notebook + Kaggle mailbox (PHASE_3_SPEC)
- [ ] Queue dataset `{user}/celium-queue` (queue.json) - write via dataset version upload, read via `GET /datasets/download/{owner}/{slug}`
- [ ] Watcher notebook template (kernel_type=notebook): model loaded ONCE, poll queue every 5s over REST, gen pending jobs → `/kaggle/working/out_<id>.png` + heartbeat.json, exit on shutdown-pill / hard cap (3600s) / idle (600s)
- [ ] CacheManager (QThread): start (push notebook, wait heartbeat) → states idle/warming/ready(countdown)/streaming n/N/stopped/dead
- [ ] /imagine while ready → append job(s) to queue.json + upload version (batch = N ids in one upload); results poller every 4s via `/kernels/output`, download unseen out_<id>.png → chat + gallery, prune done ids
- [ ] Dead-cache detection (heartbeat stale >90s or status complete/error) → fallback requeue via script path (never lose images)
- [ ] /imagine-stop-cache → shutdown pill, wait ≤15s, confirm
- [ ] UI: status bubble states + ⋯ menu toggle + live countdown/done_count tooltip
- [x] Tests (mocked HTTP): mailbox round-trip, watcher compiles, batch-20 unique ids, dead-cache fallback - **111/111 green**
- [x] Wired into app: CacheManager signals → chat bubble states (warming/ready/streaming) + ⋯ toggle; /imagine queues to notebook when ready, else script path; dead-cache auto-requeues via script (never lose images)
- [x] Cover-note honored: watcher reads queue via fresh `GET /datasets/download` (NOT the frozen /kaggle/input mount)
- [x] Bug found by smoke #1 run #1: simple multipart dataset upload 400s → fixed with the proper blob flow (POST /blobs/upload → PUT signed createUrl → version with blob token)
- [x] Live Smoke Test #1 run #2 DONE: Hop B (dataset version write) = **403 datasets.update denied** + dataset reads timeout → mailbox blocked for this key. Fallback fired correctly (dead → requeue via script path). Start now **fail-fasts on 403** (90s warm deadline) instead of stalling. Script path remains the proven image path.
