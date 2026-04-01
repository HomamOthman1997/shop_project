# Runtime Provider Matrix

This file is generated from source code and is intended to prevent docs/runtime drift.

## Numbers providers

| Provider | Temp | Rental | Unlimited rental | State temp | State rental | In RENTAL_PROVIDER_CODES |
|---|---:|---:|---:|---:|---:|---:|
| alisms | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| herosms | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| pvadeals | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| smsman | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| smsman_s6 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| smspool | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ |
| telabot | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| textverified | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

## Proxy providers

| Provider | Active in runtime registry |
|---|---:|
| 4g | ✅ |

## Source files

- `services/numbers/manager.py`
- `services/proxies/manager.py`
