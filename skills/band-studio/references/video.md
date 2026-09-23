# Video, subtitles, and color

Use this workflow for performance footage, rehearsal videos, lyric subtitles, and requested color changes. Keep the user's latest choice of edit and soundtrack. Preserve the source; render into a separate job directory. Do not start desktop playback automatically.

## Probe before editing

Record source duration, stream indexes, dimensions, frame rate, sample aspect ratio, rotation, codecs, audio layout, and color metadata. Distinguish actual source properties from creative choices. A dark preview alone does not establish that footage is HDR; check transfer function, primaries, matrix, and range before choosing an HDR-to-SDR transform.

Check the exact executable used by this job. A minimal FFmpeg build may decode media and encode H.264 while lacking `ass`, `subtitles`, or `drawtext`. A copied virtual environment may contain missing absolute links or native libraries for a different architecture. Version strings and installed directories do not prove operation.

Run the included read-only capability report:

```sh
python3 scripts/doctor.py
python3 scripts/doctor.py --ffmpeg /path/to/ffmpeg --ffprobe /path/to/ffprobe
```

Tool selection is explicit argument, then `BAND_STUDIO_FFMPEG` or `BAND_STUDIO_FFPROBE`, then `PATH`. The report checks executable responses, advertised subtitle/text filters, `libx264`, and `aac`. Each command has a 15-second timeout. Missing or failed required capabilities produce a nonzero exit code. Optional analysis CLI discovery is reported separately and does not establish that a model is installed or working. The script does not contact services or infer login/API access.

The doctor does **not** render a test image. Before the first subtitle job on a new environment, perform a small synthetic render using the selected font and language, inspect the result, and probe it. Font-file existence alone is insufficient. If repair is necessary and authorized, prefer an existing compatible binary or an isolated trustworthy installation. Do not replace global tool links or shell startup configuration merely to complete one job.

Use bounded timeouts for dependency downloads. Investigate a stalled connection before retrying. Keep transport workarounds local to the job, retain TLS verification, and do not change global network configuration unnecessarily.

## Preserve timing and the supplied text

Record source integrity, such as a SHA-256 receipt, without modifying the original. Decode a separate analysis WAV only when needed. Do not change pitch, speed, or the video timeline for lyric alignment.

Each analysis crop must store its source offset:

```text
video time = segment time + source_start_seconds
```

Also account for existing audio/video presentation-time offsets. Verify the opening, middle, and ending: a constant offset is different from accumulating drift.

Treat supplied lyrics as the text authority. Preserve words, repeated refrains, expressive pauses, and vocalizations. Remove transport artifacts such as escaped spaces deliberately, retaining the original and normalized text privately. Do not substitute an ASR guess because the user's wording seems unusual.

Arrangement instructions such as a solo marker or repetition count are not necessarily lyrics to display. Verify actual occurrences in the recording. Do not leave the previous line on screen throughout an instrumental break.

Maintain a cue ledger with stable ID, supplied text, display text, start/end time, evidence method, source reference, alignment status, and uncertainty note. Keep this ledger and real lyrics in the private job folder.

Use evidence labels instead of invented confidence percentages:

- **Verified:** text and boundaries were checked against audible material, with original-mix comparison if separation was used.
- **Supported candidate:** alignment output and independent timing anchors agree, but direct review remains incomplete.
- **Unresolved:** masking, repeated phrases, vocalizations, contradictory positions, or missing evidence remain.

A model confidence score is not a calibrated probability that a subtitle is synchronized. Waveform peaks and tempo grids can identify places to inspect, but cannot identify words.

## Separation and ASR assist review

Start with the original mix. If the voice is masked, try a short local vocal estimate with an available model. Record model identity/checksum, runtime, source offset, duration, sample rate, channels, and output paths. Verify finite samples, expected duration, and residual reconstruction when the backend supports it.

Reconstruction verifies bookkeeping, not perceptual separation quality. An estimate can leak instruments, lose consonants, or smear entrances. Keep the original mix for comparison; an estimated vocal is not the original isolated recording.

ASR proposes text and coarse positions. Forced alignment places known text against acoustic features. Neither automatically resolves sung vowels, shouts, repeated refrains, loud-room recordings, or improvised syllables. Compare results against the actual performance and retain the user's words. Candidate MIDI notes do not validate lyric timing or establish what was sung.

A text-only model may review written edit options. Do not describe that as listening, pixel analysis, or color grading. An external audio/video backend requires both documented input support and a successful current test; use it only within the user's authorized upload scope. Keep credentials out of logs and public artifacts.

Review uncertain cues in short contextual windows. Check entrances, rests, consonants, and endings. Do not fabricate word-by-word karaoke timing from evenly spaced lines. If a passage is unresolved, identify it in the review notes and deliver an explicitly described draft rather than claiming a fully synchronized final. Ask a targeted question only when the recording cannot resolve an important ambiguity. Do not add uncertainty labels to polished on-screen captions unless requested.

Keep an editable SRT or ASS sidecar. Its validity does not prove that it matches the singing or appears in the rendered video.

## Color and subtitle styling

Inspect representative frames across lighting and camera changes. Correct exposure balance, blacks, neutrals, stage-light saturation, and highlight behavior before applying a creative grade. Preserve useful shadow detail and recognizable skin appearance.

A cinematic result is not guaranteed by black bars, teal/orange color, crushed shadows, heavy grain, or sharpening. Do not claim recovery of clipped highlights or detail absent from the recording. A controlled comparison of treatments at matching timestamps is more useful than a stylistic label alone.

Choose a verified font, readable line length, safe margins, and a restrained outline or shadow. Check readability on both bright and dark frames at the intended phone size. Avoid covering faces, instrument detail, and existing graphics where possible. Select subtitle streams deliberately to avoid double-burning.

## Render once for delivery

For a straightforward grade-and-subtitle task, combine the approved filters in one final encode from the original video. If intermediates are necessary, use appropriate lossless or visually lossless masters and avoid repeated delivery compression.

Keep the selected soundtrack. Stream-copy the original audio when container compatibility and the requested edit allow it. Convert audio deliberately when necessary; do not add background music or normalization without a task reason.

Record the stream selection, filters, codecs, quality settings, pixel format, audio handling, color metadata, and container options in a private reproducible recipe. A low compression setting cannot restore lost detail. Do not upscale merely to describe a blurry source as high definition.

Render into a temporary job output and publish its final filename only after checks.

## Verify the delivered file

The included verifier performs metadata and SRT checks:

```sh
python3 scripts/verify_delivery.py /path/to/video.mp4 --srt /path/to/subtitles.srt
python3 scripts/verify_delivery.py /path/to/video.mp4 \
  --expect-duration 120 --expect-width 1920 --expect-height 1080
```

`--ffprobe` selects a tool explicitly; otherwise `BAND_STUDIO_FFPROBE` and `PATH` are used. FFprobe execution is limited to 30 seconds. Duration expectations allow 0.1 seconds for container rounding. Width and height mean encoded dimensions, before display rotation.

The SRT reader accepts UTF-8 (including BOM), CRLF or LF, positive increasing cue indexes, and standard `HH:MM:SS,mmm` timing. It rejects empty cues, invalid or negative timestamps, nonpositive cue durations, out-of-order starts, overlaps, and cues beyond the selected video duration. It allows 1 millisecond at the final boundary for numeric rounding. Unknown video duration cannot pass an SRT boundary check. Adjacent cues may meet at the same timestamp. Reported errors identify cue positions without printing the lyric text.

A zero exit code means these mechanical checks passed. It does **not** prove full-file decoding, subtitle burn-in, audio/video synchronization, correct lyrics, color quality, or listening review. Complete those checks separately:

1. Decode the full final file and inspect errors.
2. Confirm the requested source audio or authorized audio edit is present.
3. Inspect final-render frames at opening, bright/dark passages, long captions, scene transitions, instrumental gaps, repeated refrains, and ending.
4. Inspect both sides of important cue boundaries; a single screenshot cannot establish synchronization.
5. Verify representative subtitle entrances and audio/video synchronization through actual audible review or a supported audio-understanding method, recording any remaining uncertainty.
6. Confirm that the original source is unchanged.

Deliver a clickable absolute local path and a plain-language folder location, with the editable subtitle file when useful. Describe material limitations accurately; never label screenshot-only review as listening or an encoder exit as full validation.

## Public/private boundary

Publish original instructions, portable scripts, placeholder configurations, and licensed synthetic fixtures. Keep private footage, source paths, real lyrics, creative history, model binaries, credentials, caches, and job reports outside the repository. Reference third-party tools and licenses without copying their skill text. The skill coordinates tools and evidence; it does not grant accounts or guarantee musical perception.
