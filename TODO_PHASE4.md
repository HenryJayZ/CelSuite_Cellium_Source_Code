# 🚀 PHASE 4 - ntfy.sh Relay + Warm Cache v3 + JPEG 88% Quality

> Legend: `[ ]` todo · `[~]` in progress · `[x]` done

## A. 📬 ntfy.sh Relay Backend
- [ ] `RelayBackend` abstract base class (send, stream, poll)
- [ ] `NtfyRelay` implementation (POST to topic, `/json` poll with `poll=1`, SSE consumer)
- [ ] Factory `get_relay()` swaps on failure (ntfy → Telegram fallback)
- [ ] Topic naming: `cellium-<uuid4>-cmd` / `cellium-<uuid4>-res`
- [ ] Topic names persisted in settings (`kaggle_cache_cmd_topic`, `kaggle_cache_res_topic`)

## B. 📒 Watcher Notebook v3 (kaggle_cache.py)
- [ ] Replace dataset queue polling with ntfy SSE consumer (one persistent connection)
- [ ] Model loaded ONCE at startup; job loop → `/kaggle/working/out_<id>.png` + `heartbeat.json`
- [ ] Results path priority: 1) mid-run `/kernels/output` (verify mid-run fetch works) → 2) ntfy attachment → 3) catbox.moe
- [ ] Exit on shutdown pill / 1h hard cap / 10min idle / 3 failed SSE reconnects → clean exit
- [ ] JPEG 88% quality output in notebook (Pillow `save(quality=88, optimize=True)`)

## C. 🎛️ CacheManager v3 (QThread)
- [ ] `start()` mints topics → pushes watcher notebook → subscribes to res-topic SSE
- [ ] `/imagine` while ready → POST job JSON to cmd topic (batch = N jobs in ONE message)
- [ ] Results poll via res-topic SSE + fallback polling; download PNGs → chat bubbles
- [ ] Dead-cache detection (no heartbeat > 120s) → auto-requeue via script path
- [ ] `/imagine-stop-cache` publishes shutdown pill, waits ≤15s, confirms
- [ ] Live UI: status bubble + ⋯ menu toggle + live countdown/done_count tooltip

## D. 🎨 JPEG 88% Quality
- [ ] Notebook saves `quality=88, optimize=True` for PNG→JPEG conversion
- [ ] Settings toggle `kaggle_jpeg_quality` (default 88, range 70-95)
- [ ] Apply to both generated images and img2img outputs

## E. Settings & UI
- [ ] Settings → Image Generation: ntfy topics display + "🔥 Warm Cache v3 (ntfy)" toggle
- [ ] `/` drop-up includes `/imagine-start-cache` / `/imagine-stop-cache`
- [ ] ✨ Enhance model picker + state machine (already done)
- [ ] Batch up to 20 (already done)
- [ ] JPEG quality slider in settings (70-95, default 88)

## E. Tests & Docs
- [ ] Mocked SSE stream: 3 jobs in → 3 done-signals → 3 fetches, order kept
- [ ] Simulated ntfy 429 → RelayBackend swaps, no crash
- [ ] SSE drop mid-batch → reconnect with `since=` → zero lost/duplicates
- [ ] Live smoke: 3 prompts via ntfy, assert <25s each end-to-end, then stop-cache
- [ ] Full suite 111+ green
- [ ] Update CHANGELOG, KAGGLE_IMAGE_GEN.md, TODO_PHASE4.md