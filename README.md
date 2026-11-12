# Beam

Send up to 10 files and get one link, or ask for files and let people send them to you. Up to 10 GB per send, no account, gone after about a day.

**Live:** https://beamshare.app

https://github.com/user-attachments/assets/10cc9810-813d-4094-a9c5-316e8418fe67

## How it works

### Upload

1. **Start:** the browser sends each file's name and size plus a Turnstile token. The API checks the token and limits (10 files, 10 GB total), then returns presigned URLs for every 64 MiB part of every file.
2. **Upload:** parts go straight to R2, four at a time. Each URL is signed for its part's exact size, so R2 rejects anything bigger.
3. **Complete:** the API asks R2 which parts arrived instead of trusting the browser, then finishes the upload.

### Download

`/f/{share}/info` lists the finished files in one R2 call, and `/f/{share}/{n}` signs a 10-minute URL for that file and redirects to it.

### File requests

A request is a note in R2 at `requests/{id}/note`, with an optional name and a private switch. Creating one returns two random IDs: the request ID people share, and an owner key the requester keeps. Senders open `/r/{id}`, add their name, and upload the same way as a share, into `requests/{id}/{share}/{sender}/{filename}/{index}`. One listing of `requests/{id}/` gives every send. A request takes files for a day.

### Expiry

An R2 lifecycle rule deletes files about a day after upload and clears abandoned multipart uploads.

## Design decisions

**No database.** R2 already stores the bytes, keeps each file's name in its key (`share/index/name`), so listing a share is one call, and handles expiry. A database would just be a second copy to keep in sync.

**Bytes skip the API.** Proxying uploads means the server reads and re-sends every byte and pays for the bandwidth. With presigned URLs the API only signs, and transfer speed depends on the user's connection. Beam adds about 0.5 s per upload no matter the file size (0.2 s to start, 0.3 s to finish, measured on the live site); a 455 MB file took about 13 s on a home connection.

**Multipart for 10 GB.** A single presigned PUT caps out around 5 GB. 64 MiB parts get past that, upload in parallel, and retry individually.

**Abuse limits without accounts.** Starting an upload is the only way into storage, so that's where the checks are:

- Turnstile token required, so scripts can't start uploads freely.
- 50 GiB per IP per day and 1 TiB total per day, sized from the worst monthly bill I'd accept.
- The declared size is held at start, settled to the real size on completion, and released on cancel. A sweeper aborts uploads that never finish.

- Each request also has a 25 GB cap across everyone who sends to it, held and settled like the others.

Counters are in memory and reset when the API restarts. That keeps it to one process with no extra infrastructure; a restart resets limits but never loses files.

**Private requests without accounts.** With the private switch on, the API only lists or serves a request's files when the URL includes the owner key. The key lives in the request's note and is compared in constant time. Senders get the public link and the requester keeps the owner link, so two random IDs do the job a login would.

## Privacy

Files are stored in R2 under a random ID and deleted after about a day. Anyone with the link can download until then. IP addresses are held in memory only, to enforce limits. Anyone with a request's link can read its note. If the request is private, only the owner link can see the files.

## Stack

- **Frontend:** React, TypeScript, Vite
- **API:** Python, FastAPI, boto3
- **Storage:** Cloudflare R2
- **Hosting:** Cloudflare Workers (frontend), Heroku (API)
- **Bot protection:** Cloudflare Turnstile
- **Tests:** pytest (149) and Vitest (51) covering uploads, file requests, limits, timeouts, cleanup, abuse reports, stats, and screen scaling

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
