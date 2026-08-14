"""Meeting summarization module.

Business-layer responsibilities only: audio capture, voice-activity
segmentation, task scheduling to AIM, minutes persistence and UI
notification. No LLM / model inference here.
"""