# Beam

Send a file, get a link. Files up to 10 GB, no account, gone after about a day.

**Live:** https://beamshare.app

<video src="https://github.com/user-attachments/assets/4f7951b5-c2cf-4c62-a395-ee78dfdb393d" controls></video>

## How it works

### Upload

1. **Start:** the browser sends the file's name, size, and a Turnstile token. The API checks the token and limits, then returns a presigned URL for each 64 MiB part.
2. **Upload:** parts go straight to R2, four at a time. Each URL is signed for its part's exact size, so R2 rejects anything bigger.
3. **Complete:** the API asks R2 which parts arrived instead of trusting the browser, then finishes the upload.

### Download

`/f/{id}` checks the file exists, signs a 10-minute R2 URL with the original filename, and redirects to it.

### Expiry

An R2 lifecycle rule deletes files about a day after upload and clears abandoned multipart uploads.

## Design decisions

**No database.** R2 already stores the bytes, keeps the filename as object metadata, and handles expiry. A database would just be a second copy to keep in sync.

**Bytes skip the API.** Proxying uploads means the server reads and re-sends every byte and pays for the bandwidth. With presigned URLs the API only signs, and transfer speed depends on the user's connection. Beam adds about 0.5 s per upload no matter the file size (0.2 s to start, 0.3 s to finish, measured on the live site); a 455 MB file took about 13 s on a home connection.

**Multipart for 10 GB.** A single presigned PUT caps out around 5 GB. 64 MiB parts get past that, upload in parallel, and retry individually.

**Abuse limits without accounts.** Starting an upload is the only way into storage, so that's where the checks are:

- Turnstile token required, so scripts can't start uploads freely.
- 50 GiB per IP per day and 1 TiB total per day, sized from the worst monthly bill I'd accept.
- The declared size is held at start, settled to the real size on completion, and released on cancel. A sweeper aborts uploads that never finish.

Counters are in memory and reset when the API restarts. That keeps it to one process with no extra infrastructure; a restart resets limits but never loses files.

## Privacy

Files are stored in R2 under a random ID and deleted after about a day. Anyone with the link can download until then. IP addresses are held in memory only, to enforce limits.

## Stack

- **Frontend:** React, TypeScript, Vite
- **API:** Python, FastAPI, boto3
- **Storage:** Cloudflare R2
- **Hosting:** Cloudflare Workers (frontend), Heroku (API)
- **Bot protection:** Cloudflare Turnstile
- **Tests:** pytest, 49 tests covering uploads, limits, cleanup, and abuse reports

## Running locally

Needs [uv](https://docs.astral.sh/uv/), Node, and an R2 bucket named `beam` with a CORS policy allowing `http://localhost:5173`.

```sh
# API: put R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
# TURNSTILE_SECRET (and optionally CORS_ORIGINS) in .env
uv run fastapi dev src/beam/main.py

# Frontend (uses Cloudflare's always-pass Turnstile test key by default)
cd frontend && npm install && npm run dev

# Tests
uv run pytest
```
