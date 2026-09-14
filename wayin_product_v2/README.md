# WayIn Product v2 — Vercel-ready

This version adds:

- Guest live search UI
- Amadeus hooks for flight and hotel search
- Ticketmaster live event search
- Trip builder ("Add to trip")
- WayIn AI chat via OpenAI Responses API
- Auth via secure Flask session
- Neon/Postgres persistence
- Group trip sharing by Resend email
- Group trip sharing by Twilio SMS
- Explicit user-triggered sharing to reduce accidental spam

## Required Vercel environment variables

Already needed:
- DATABASE_URL
- WAYIN_SECRET_KEY
- WAYIN_SECURE_COOKIES=1

For AI:
- OPENAI_API_KEY
- OPENAI_MODEL=gpt-5 (optional)

For flights/hotels:
- AMADEUS_CLIENT_ID
- AMADEUS_CLIENT_SECRET
- AMADEUS_BASE_URL=https://test.api.amadeus.com

For events:
- TICKETMASTER_API_KEY

For email:
- RESEND_API_KEY
- WAYIN_FROM_EMAIL

For SMS:
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_FROM_NUMBER

The app still loads without these provider keys; each provider becomes live when its variables are configured.

## Important booking note

Search results may link to a provider, but WayIn must not show a trip item as "booked" until a booking provider confirms it. Amadeus flight/hotel booking requires additional production workflow and commercial requirements.

## Deploy

Upload this folder to GitHub and set the Vercel Root Directory to this exact folder name.
