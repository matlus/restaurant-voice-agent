# Plan

## Goal

A real-time voice agent for a fictional restaurant, working locally first and hosted on Vapi later. The browser page
has one microphone button and no transcript. You press it, talk, and hear the agent reply as it speaks.

## Decisions

| Topic | Decision |
| --- | --- |
| Language | Python, with FastAPI for the web host. |
| Voice pipeline | Our own thin provider layer over the official SDKs rather than a framework such as Pipecat. |
| Providers | OpenAI Realtime (`gpt-realtime-2.1`, or `-mini` to save cost) and Gemini Live (`gemini-3.1-flash-live-preview`). Confirm the exact model IDs and voice lists against each provider's docs when building the adapters. |
| Restaurant | Ember & Sprout, a "modern grill and garden" with one location and 32 dishes. |
| Diet labels | Vegan, vegetarian, pescatarian, keto, carnivore and paleo from the recipe. Gluten-free, dairy-free and nut-free derived from allergens. |
| Allergens | The nine major US allergens. |
| Reservations | The full lifecycle: check, book, look up, change and cancel. Changing or cancelling needs only the confirmation code. A caller without it proves the booking is theirs with the phone number, the name and the date it is under, and that proof is checked again on every change or cancellation. A lookup never returns the confirmation code. Caller ID or a texted one-time code would be stronger, and need a telephony or SMS provider. |
| Storage | A local SQLite file, seeded from JSON on first use. |
| Secrets | API keys in a gitignored `.env`. `.env.example` is committed. |
| Practice | PWI (see `AGENTS.md`). |

## Architecture

```text
Browser (mic button, AudioWorklet)
   |  WebSocket: 16-bit PCM audio up, audio chunks and control events down
FastAPI host (apps/voice-agent-web)
   |  RealtimeProvider interface: connect, send audio, receive events, send tool result, close
   +-- OpenAI Realtime adapter (24 kHz audio in and out)
   +-- Gemini Live adapter (16 kHz in, 24 kHz out)
   |  tool calls
Restaurant DomainFacade (packages/voice-agent-restaurant)
   |
SQLite
```

Each tool is defined once and translated into each provider's tool format. When the guest starts speaking over the
agent, the provider reports an interruption and the browser stops playback at once (barge-in). The system prompt
includes the restaurant's local date and time, so phrases like "this Friday" resolve correctly. The agent answers
allergy questions only from the data, and always mentions the shared kitchen.

For Vapi, the same facade operations are exposed as HTTP endpoints, and Vapi calls them as tool webhooks.

## Status

| Step | State |
| --- | --- |
| Scaffold the repo and adopt PWI | Done |
| Seed data: restaurant, hours, closures, tables, menu, existing bookings | Done |
| Restaurant domain with acceptance tests (46 tests), PWI review findings fixed | Done |
| OpenAI Realtime adapter and browser audio, end to end (conversation package, web host, microphone page) | Done |
| Connect the tools: menu questions and bookings by voice | Done |
| Voice catalog (four OpenAI voices) | Done |
| Gemini Live adapter | Next |
| Interruption, a latency check (turn detection), README | Done |
| Phase 2: HTTP tool endpoints and hosting on Vapi | |

## Voices

Voices come from a configuration catalog listing the provider, the voice ID, a presented gender and a short
description. Neither provider labels voices by gender, so those labels are ours. Candidates: OpenAI `marin` and
`coral` (female), `cedar` and `ash` (male); Gemini `Kore` and `Aoede` (female), `Puck` and `Charon` (male).
