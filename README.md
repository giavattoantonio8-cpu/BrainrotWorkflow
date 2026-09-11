# BrainrotWorkflow

BrainrotWorkflow is a personal automation project for turning an approved story into a two-part vertical video with local text-to-speech, on-screen captions, and a looping gameplay background. It is a learning project, not a production-ready or commercial publishing system.

## Motivation

I started this project while learning to code and experimenting with Claude Code. After seeing short-form content promoting automated TikTok workflows, I decided to build my own system to understand what was actually happening behind them, and how far I could take the idea beyond a one-off script.

## What I Built

- Optional story acquisition from public Reddit data, with basic filtering and cleanup.
- Story processing into a JSON handoff format.
- A deliberate human approval step before production.
- Earlier AI-assisted story evaluation/transformation experiments.
- Local Kokoro TTS narration for the current tested workflow.
- Estimated word timings, grouped into short subtitle phrases.
- Gameplay-background selection, vertical crop/looping, and MoviePy/Pillow caption composition.
- Part 1 and Part 2 vertical MP4 output.

## Architecture

```text
Optional Reddit acquisition
        |
        v
Story JSON inbox ----> Human approval / editorial choice
                                  |
                                  v
                     Approved story JSON (manual input)
                                  |
                                  v
      text cleanup -> story split -> Kokoro local TTS
                                  |
                                  v
          estimated word timings -> grouped captions
                                  |
                                  v
    licensed gameplay clip -> FFmpeg crop/loop -> MoviePy/Pillow composition
                                  |
                                  v
                       Part 1 / Part 2 vertical MP4s
```

## Human-in-the-Loop Design

I deliberately did not fully automate the final choice of story. The system can collect, filter, and process candidates, but I considered human judgment more reliable for audience fit, tone, and quality. In this public prototype, that approval happens by choosing the story JSON passed to `generate_video.py`; a fuller future version would represent the approval stage explicitly in the file workflow.

## Iterations

This project evolved through several separate approaches, rather than using every tool at once:

1. An original concept: Whisper transcription -> Claude-assisted evaluation/transformation -> TTS -> MoviePy video composition.
2. A Reddit acquisition component for collecting and filtering candidate stories.
3. Edge TTS and FFmpeg experiments for word-timed captions and vertical rendering.
4. A later local Kokoro TTS workflow that split stories into two parts and used MoviePy/Pillow captions.

## Current Implementation

`generate_video.py` is the public copy of the latest successfully executed prototype workflow, originally named `produce_test.py`. Its process is:

```text
story JSON -> text cleanup -> story split -> Kokoro local TTS
-> estimated word timings -> grouped subtitles -> gameplay background
-> MoviePy/Pillow composition -> Part 1 and Part 2 MP4
```

The older Whisper/Claude/Edge-TTS work is historical context, not the current implementation in this repository.

## Tech Stack

- Python
- Kokoro ONNX / `kokoro-onnx`
- NumPy and SoundFile
- MoviePy 2.x
- Pillow
- FFmpeg and FFprobe
- Requests; optional PRAW support for Reddit acquisition

## Setup

Requirements: Python 3.10+ and FFmpeg (including `ffprobe`) available on your `PATH`.

```bash
python -m venv .venv
# Activate the environment using your shell's normal command.
pip install -r requirements.txt
copy config.example.json config.json
```

On macOS/Linux, use `cp config.example.json config.json` instead of `copy`.

Then download compatible Kokoro ONNX model and voice files following the `kokoro-onnx` documentation. Keep them local, outside version control, and update the relative `model_path` and `voices_path` values in your ignored `config.json` if your filenames differ. Add a gameplay clip you have the rights to use to `assets/gameplay/`.

Run the included original placeholder fixture:

```bash
python generate_video.py data/sample_story.json
```

Generated intermediate audio is written under `work/`; videos are written under `output/videos/`. Both locations are ignored by Git.

### Optional Reddit acquisition

```bash
python reddit_scraper.py --dry-run
python reddit_scraper.py
```

The scraper can use the unauthenticated public endpoint. If you choose authenticated access, install `praw` and place your own credentials only in the ignored local `config.json`; never commit them. Review every acquired story manually before using it.

## My Role

I came up with the project idea, designed the overall workflow, and made the main architectural decisions. I chose and integrated the tools/APIs, decided to keep final story selection human-in-the-loop, evaluated the generated outputs, and iterated based on quality. I used Claude Code as a coding assistant during implementation rather than writing every line manually.

## What Worked

- The latest prototype successfully generated two-part vertical videos from story JSON files.
- Local TTS, audio assembly, caption rendering, gameplay looping/cropping, and MP4 composition worked together as one workflow.
- JSON acted as a simple handoff contract between acquisition/selection and production.
- Iterating across TTS and rendering approaches made the quality tradeoffs concrete.

## What Did Not Work

- Caption timing is estimated from synthesized-audio duration rather than force-aligned, so it is not reliably word-perfect.
- The final outputs still looked too AI-generated to justify publishing them as content.
- Several components remain prototype-quality and need stronger error handling, tests, and dependency management.
- This is not a production-ready system.

## What I Learned

- How to design an AI workflow around real inputs, outputs, and decision points.
- What to automate and what to retain for human judgment.
- How to work with an AI coding assistant while maintaining architectural ownership and critical evaluation.
- How to integrate speech synthesis, media processing, JSON handoffs, external data, and local tooling.
- Why iterative output evaluation matters more than simply making an automation run end-to-end.
- How human-in-the-loop design can be a product decision, not a missing feature.

## Demo

No generated video is included in this repository. Add a rights-cleared, reviewed demo later, for example:

```text
[Demo video](docs/demo.mp4)
```

Before adding one, confirm that the story, voice/model use, gameplay asset, and music/audio rights allow public distribution.

## Limitations

Reddit-derived text and gameplay clips may have copyright, platform-policy, attribution, privacy, or content-safety considerations. This public repository therefore includes neither collected stories nor gameplay/video outputs. Any user of the optional acquisition component is responsible for reviewing source terms and obtaining appropriate rights before publishing content.

## Future Improvements

- Add forced alignment or TTS-native timing data for more accurate captions.
- Make human approval explicit with separate inbox and approved-story directories or a small review UI.
- Replace hard-coded storytelling heuristics with configurable, testable rules.
- Add automated unit tests and a CI smoke test that does not require models or external services.
- Improve reproducible model setup and cross-platform font handling.
- Add content provenance, licensing checks, and a more deliberate visual/audio quality review process.

