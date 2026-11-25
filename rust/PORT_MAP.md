# Port map: iphone-mirror-windows

2 of 5 units have a Rust port; no original changed since it was recorded.

## Ports

| Unit | Crate | In Rust | Kept in the original | Cases | Last diff | Original |
| --- | --- | --- | --- | ---: | ---: | --- |
| `iphone_mirror/fairplay/` | `rust/fairplay-rs` | `z_xor`, `x_xor`, `generate_key_schedule`, `decrypt_message`, `modified_md5`, `sap_hash`, `generate_session_key`, `playfair_decrypt` | `FairPlay`, `L`, `U`, `rol8`, `rol8x`, `weird_ror8`, `weird_rol8`, `weird_rol32`, `CInt`, `UCharBuf`, `garble`, `cycle` | 465 | 465/465 | unchanged |
| `iphone_mirror/stream_ops/` | `rust/stream-ops-rs` | `avcc_to_annexb`, `decrypt_mirror_nal`, `parse_avcc_config`, `decrypt_audio_rtp`, `scale_pcm_i16`, `visible_size`, `encode_txt_records` | - | 1524 | 1524/1524 | unchanged |

## Not ported yet

In the order `analyze` suggests.

| Unit | Status | Lines | Exports | Readiness |
| --- | --- | ---: | ---: | ---: |
| `iphone_mirror/` | caution | 3662 | 37 | 0 |
| `tools/` | blocked | 377 | 0 | 45 |
| `iphone_mirror/control/` | blocked | 1618 | 0 | 1 |

2 of these units have no port on purpose (2 blocked, 0 kept in the original), so 1 unit is left to port:

- `tools/`: blocked, Uses dynamic code (eval, new Function or computed imports)
- `iphone_mirror/control/`: blocked, Uses dynamic code (eval, new Function or computed imports)

Regenerate with `rust-anything map --write`. Commit this file: when the original changes upstream, the next map marks every port whose recording it outdated.
