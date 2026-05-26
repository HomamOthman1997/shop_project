from services.numbers.order_recording_service import recording_filename, voice_recording_uri_from_calls


def test_voice_recording_uri_from_calls_accepts_nested_provider_shapes():
    assert (
        voice_recording_uri_from_calls(
            [
                {
                    "id": "call_1",
                    "recording": {"downloadUrl": "https://example.test/nested.mp3"},
                }
            ]
        )
        == "https://example.test/nested.mp3"
    )
    assert (
        voice_recording_uri_from_calls(
            [
                {
                    "id": "call_2",
                    "recording_url": "/api/pub/v2/calls/call_2/recording",
                }
            ]
        )
        == "/api/pub/v2/calls/call_2/recording"
    )


def test_recording_filename_matches_content_type():
    assert recording_filename("audio/mpeg") == "call-recording.mp3"
    assert recording_filename("audio/wav") == "call-recording.wav"
    assert recording_filename("audio/ogg") == "call-recording.ogg"
    assert recording_filename("audio/mp4") == "call-recording.m4a"
    assert recording_filename("application/octet-stream") == "call-recording.bin"
