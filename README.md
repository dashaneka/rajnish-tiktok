# tiktok telegram downloader

created by rajnish sahani

send an individual public tiktok video or photo-post link to your telegram bot. videos use yt-dlp's best available format; photo posts use images exposed in the requested post's page data. files are sent as telegram documents without re-encoding. telegram may still show a playable video preview.

## deploy on render from your phone

1. create a **new** github repository named `rajnish-tiktok` under `dashaneka`. keep your working instagram and pinterest repositories separate.
2. unzip `tiktok_telegram_bot.zip`. upload these five files directly to the repository root: `bot.py`, `tiktok_downloader.py`, `requirements.txt`, `Dockerfile`, and `render.yaml`. you may also upload this readme and the tests folder. do not upload just the zip or the outer folder.
3. create a separate tiktok downloader bot with @BotFather using `/newbot`. use its new token; do not reuse your other bots' tokens.
4. open [deploy on render](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fdashaneka%2Frajnish-tiktok).
5. enter the new token in `BOT_TOKEN`, then deploy. render supplies `RENDER_EXTERNAL_URL`; the bot binds to `0.0.0.0:$PORT` and registers an authenticated telegram webhook at `/telegram`.
6. once the service is live, send `/start`, then a public tiktok link.

if you choose another repository name, replace `dashaneka/rajnish-tiktok` in the deployment link. private repositories need render's github app to have access. keep bot tokens only in render's environment settings, never in github or this readme.

## supported links and behavior

- `https://www.tiktok.com/@creator/video/1234567890123456789`
- `https://www.tiktok.com/@creator/photo/1234567890123456789`
- tiktok short links, including `vm.tiktok.com`, `vt.tiktok.com`, and `www.tiktok.com/t/...` that redirect to an individual post.
- photo-post images are returned separately, in post order, up to 35 images; this does not turn them into a slideshow video or include their soundtrack.
- older `/video/` links that expose only a photo-post soundtrack fall back to photo extraction; they do not silently return only the audio.
- profiles, live streams, private content, bulk account downloads, and non-tiktok URLs are unsupported.
- `/start`, `/help`, and `/id` are included.

## access, file limits, and cleanup

`ALLOWED_USER_IDS` is blank by default: anyone who knows your bot can use it. for personal access, send `/id` and put your numeric telegram user id into this setting. comma-separated ids are supported. update the corresponding `value` in `render.yaml` as well before a later blueprint sync, so it does not reset the setting to blank.

`MAX_UPLOAD_MB=49` is the per-file upload ceiling for this project. larger files are rejected without reducing quality. `MAX_TEMP_MB=256` limits temporary storage, and `DOWNLOAD_TIMEOUT_SECONDS=420` bounds each download. one download runs at a time. temporary files are removed after success, upload failure, or download failure. timed-out or cancelled subprocesses, including ffmpeg children on linux, are killed before cleanup. yt-dlp caching is disabled; no downloaded media is intentionally retained. render's ephemeral disk is reset on restart/redeploy.

free render web services can sleep after inactivity, delaying the next request. all free services in one workspace share the monthly free instance-hour allowance. three continuously active bots can consume it faster. official details: https://render.com/docs/free.

## real limits and verification

this project does **not** promise that tiktok will accept requests from render or every hosting provider. tiktok can block a server ip, require a challenge, or change its page format. no login cookies, third-party downloader services, or paid proxies are included. the bot reports a useful failure instead of claiming success. retries are bounded. the highest format exposed to the downloader is not necessarily the creator's camera original; watermark removal is not guaranteed.

local automated tests cover extraction, post isolation, document uploads, cleanup, subprocess deadlines, storage limits, redirects, and webhook configuration. public live test outcomes are recorded in `REVIEW.md`; telegram delivery and deployment need your real bot token and render service to verify.

## local setup

requires python 3.10+ and ffmpeg on your PATH; docker includes ffmpeg.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set your token
python bot.py
```

without a webhook URL, local use runs telegram polling. stop the render instance if you run the same token locally; a bot should have one active receiver. optionally set `WEBHOOK_SECRET` to 1–256 letters, digits, underscores or hyphens; otherwise a secret is derived from the token. `WEBHOOK_URL`, when supplied, must be an https origin with no path or query.

## tests

```bash
pip install -r requirements.txt
pip install pytest
python -m pytest -q
```

## updating extraction

if tiktok changes its website, review yt-dlp's official releases and update the version in `requirements.txt`, then test and redeploy. photo extraction may also need changes. credentials are not required for the configured public-post workflow.
