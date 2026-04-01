# Cards Bot Phone Verification Concept

## Scope

This concept is for the cards bot only.

It is not intended to become a global verification system across all project bots.

## Chosen Verification Model

The chosen model is:

1. The bot asks the user to verify a phone number
2. The bot generates a short verification token
3. The user sends an SMS from their phone to our dedicated Syrian phone number
4. The SMS contains the requested token
5. Our Android app receives the inbound SMS
6. The Android app forwards raw inbound SMS data to our server
7. The server parses the SMS and confirms the verification

## Why This Model Was Chosen

Compared with outbound OTP sending from our device, this model:

- keeps more logic on the bot/server side
- keeps the Android app simpler
- avoids SMS sending logic and SIM-routing complexity in the first version
- reduces Android-side business logic

The Android app should be a forwarder, not the source of truth.

## Android App Role

The Android app should do only these things:

- listen for inbound SMS
- collect:
  - sender phone number
  - message body
  - timestamp
  - optional SIM slot if available
- send that raw data to the server

The Android app should not:

- decide whether a user is verified
- parse business meaning deeply
- hold verification state as a source of truth

## Server Role

The server should:

- create verification requests
- generate single-use tokens
- store pending verification state
- receive inbound SMS payloads from the Android app
- parse and match tokens
- normalize sender numbers
- mark the user as verified when conditions match

## User Flow

Proposed flow:

1. User enters the cards bot flow that requires verification
2. Bot asks the user to share their phone or otherwise bind the target phone number
3. Bot generates a token such as:
   - `PH-365215`
4. Bot tells the user:
   - send this exact code by SMS to our verification number
5. Android app forwards inbound SMS messages to the server
6. Server matches:
   - token
   - sender phone number
   - expiry window
7. If valid:
   - mark user verified
   - allow continuation in the cards flow

## Data Model Guidance

Recommended collections/tables:

### `phone_verification_requests`

Fields:

- `user_id`
- `bot_id`
- `phone_number_expected`
- `token`
- `status`
- `created_at`
- `expires_at`
- `matched_inbound_sms_id`
- `verified_at`

### `inbound_sms_events`

Fields:

- `sender_phone`
- `body`
- `received_at`
- `device_id`
- `sim_slot`
- `processed`
- `matched_request_id`

## Token Rules

Recommended:

- short
- uppercase
- easy to type
- single-use
- time-limited

Example:

- `PH-365215`

Recommended constraints:

- expire after 5 to 10 minutes
- invalidate after first successful use
- reject duplicates/replays

## Matching Rules

The server should verify:

- token exists
- token status is pending
- token is not expired
- sender phone matches expected user phone after normalization
- token has not been used before

## Android Constraints

Current device assumptions from discussion:

- one Android device only
- two SIMs available
- app is local only, not distributed publicly
- no root should be assumed
- Huawei / Android 10 class device is acceptable

For this chosen inbound-SMS model:

- SIM1 default is much less important than in outbound-SMS design
- the critical requirement is stable inbound SMS listening and forwarding

## Security Notes

- App-to-server authentication is required
- Raw inbound SMS should be accepted only from the trusted device
- Do not trust the client app to finalize verification
- Keep all verification truth on the server

## Deferred Extensions

Not part of the first version:

- outbound OTP sending from the device
- payment notification parsing
- Syriatel Cash automation
- Sham Cash notification automation
- multi-device fleet management
- public app distribution

## Recommended MVP

First version should include only:

- cards-bot verification request creation
- Android inbound SMS forwarding
- server-side matching
- verified/not-verified result handling in the cards bot

That is enough to validate the concept before adding anything else.
