# Licence register

Every third-party component that affects whether we may operate commercially. Reviewed
before Phase 1 and on every dependency addition. "Verify" means: read the actual licence file
in the pinned version, not the README.

## TTS models

| Model | Licence | Commercial use | Notes | Status |
|---|---|---|---|---|
| Qwen3-TTS 1.7B / 0.6B (Base, CustomVoice, VoiceDesign) + tokenizer | Apache-2.0 | Yes | Weights and tokenizer released under Apache-2.0 (Jan 2026) | **Approved** |
| Kokoro-82M | Apache-2.0 | Yes | `.litertlm` bundle from `litert-community` is Apache-2.0 per model card | **Approved** |
| Chatterbox (Resemble AI) | MIT | Yes | English-first; candidate fallback | Approved (unused) |
| CosyVoice 3 | Apache-2.0 | Yes | Alternative provider | Approved (unused) |
| MOSS-TTS-Realtime | Apache-2.0 | Yes | Watch; newer | Under review |
| Phonon 31M | Apache-2.0 | Yes | Ultra-light, low quality; offline draft only | Approved |
| PocketTTS 100M | CC BY 4.0 | Yes, with attribution | Attribution required in-app | Verify attribution UX |
| Piper | MIT engine | Yes | **Per-voice model licences vary** — audit each voice before shipping | Restricted |
| XTTS-v2 (Coqui) | CPML | **No** — non-commercial | Excluded | **Blocked** |
| F5-TTS | MIT code / CC-BY-NC weights | **No** | Weights are non-commercial | **Blocked** |
| Bark | MIT | Yes | Not shortlisted (quality/pace) | — |

## Managed TTS

| Provider | Terms risk | Notes |
|---|---|---|
| Google Cloud TTS (Chirp 3 HD) | Commercial use permitted; output usable in applications | Google claims no ownership of generated audio; confirm current terms at integration |
| Amazon Polly | Commercial use permitted | Brand Voice is enterprise-only |
| ElevenLabs | **Commercial licence requires a paid plan** | Free tier output is not licensed for commercial use. Do not use free tier in production |

## Parsers and document handling

| Library | Licence | Commercial | Note |
|---|---|---|---|
| pypdfium2 | Apache-2.0 / BSD-3 | Yes | Preferred PDF renderer |
| pdfminer.six | MIT | Yes | Text extraction fallback |
| pdfplumber | MIT | Yes | Layout-aware extraction |
| python-docx | MIT | Yes | DOCX |
| selectolax / lxml | MIT / BSD | Yes | HTML |
| ebooklib | AGPL-3.0 | **No** (for SaaS) | **Blocked.** Use a permissive EPUB reader or parse the container directly |
| PyMuPDF (fitz) | **AGPL-3.0** or commercial | **No** without a paid licence | **Blocked.** The most common trap in this category |
| Docling (IBM) | MIT | Yes | Layout understanding, if PDF quality demands it |

## Audio

| Component | Licence | Note |
|---|---|---|
| FFmpeg | LGPL-2.1+ (or GPL if built with GPL components) | Ship an LGPL build; avoid `--enable-gpl` and nonfree codecs. AAC encoding via the native encoder is fine; `libfdk_aac` is non-free |
| loudnorm / ebur128 filters | LGPL | Part of FFmpeg |
| faster-whisper | MIT | ASR round-trip QC |
| Parakeet-TDT | CC-BY-4.0 (NVIDIA) | Alternative QC ASR; check model card |

## Catalogue sources

| Source | Terms | Obligation |
|---|---|---|
| Project Gutenberg | Public domain in the **US**; trademark terms restrict use of the "Project Gutenberg" name | Do not imply endorsement; strip PG header/licence boilerplate from the text; respect bulk-access guidance (mirror or self-host Gutendex rather than hammering the site) |
| Gutendex | MIT (software) | Recommended to self-host for long-term use; public instance is a courtesy |
| Standard Ebooks | PD texts; their *production* is released CC0 | Attribute Standard Ebooks as the source of the edition |
| Open Library | Metadata under CC0; cover images may have separate rights | Use for metadata and edition discovery, not as a text source |

## Infrastructure and libraries to verify at integration

- Postgres 16 (PostgreSQL Licence), pgvector (PostgreSQL Licence)
- Next.js (MIT), React (MIT), Tailwind (MIT)
- React Native (MIT), AndroidX Media3 (Apache-2.0)
- FastAPI (MIT), Pydantic (MIT), SQLAlchemy (MIT), Alembic (MIT)
- uv (Apache-2.0/MIT), pnpm (MIT)

## Rules

1. A dependency with an unverified licence does not enter `main`.
2. Copyleft (GPL/AGPL) in the server path is treated as blocked unless a commercial licence is
   purchased — the SaaS is the distribution.
3. Model weights are dependencies. Record `weights_sha256` and the licence in the model
   registry row, not just in this file.
4. Output rights are separate from model rights. For managed providers, record the terms
   version date at integration.
