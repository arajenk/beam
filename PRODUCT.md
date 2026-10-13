# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack
React + Vite + TypeScript in `frontend/`, built to static files and served as a Cloudflare Worker with static assets (https://beam.arajenkajanthira.workers.dev). Backend: FastAPI service (`src/beam/`) using Cloudflare R2 (S3 API) for storage; no database. API hosting planned on Heroku (Basic dyno).

## Users
Anyone who needs to move a file to someone (or to another of their own devices) quickly: a friend, a coworker, phone to laptop. No account, no setup; they arrive, send, and leave.

## Product Purpose
Quick, frictionless file transfer. Upload a file, get a short link, share it; the recipient downloads it. Files are temporary and disappear on their own. Success means the person gets from "I have a file" to "they have the link" in seconds, without thinking about the tool.

## Positioning
Zero friction: no account, no email, none of the limits or upsells that come with cloud storage services. Files are ephemeral, so nothing lingers and privacy is the default.

## Operating Context
- Single-file shares in v1. Multi-file shares (pick files or download a zip) are planned later.
- Share link format: `/f/{id}` with a short hex ID.
- Files expire about 1 day after upload (R2 lifecycle rule; actual deletion can take up to about 24h longer).
- Uploads and downloads go directly between the browser and R2 through presigned URLs; the API only signs and checks.
- Future idea (undecided): peer-to-peer WebRTC transfers for desktop app users.

## Capabilities and Constraints
- Max file size: 10 GiB, uploaded as presigned multipart (64 MiB parts, four in parallel).
- Abuse limits: a Turnstile check to start an upload, 50 GiB per IP per day, 1 TiB total per day. Counters live in memory and reset when the API restarts.
- No accounts and no authentication: anyone with the link can download.
- Missing or expired files appear the same to the user (not found).
- Undecided: exact copy for expiry ("about a day"), desktop app, P2P mode.

## Brand Commitments
Name: Beam. Voice, visuals and logo are not decided.

## Evidence on Hand
No users, testimonials, metrics or press. Don't make any up.

## Product Principles
1. Every step between "have a file" and "share the link" must earn its place.
2. Privacy by default: temporary files, no accounts, no tracking the user didn't ask for.
3. Be honest about limits (size, expiry) up front instead of surprising people later.
4. The recipient's experience matters as much as the sender's.
