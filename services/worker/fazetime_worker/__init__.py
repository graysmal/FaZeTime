"""FaZeTime P3 media worker (CONTRACTS §9.4, §9.16).

One Twitch source -> one FFmpeg decode -> 16 kHz PCM + sparse frames on one media timeline per
source_epoch -> local ASR -> typed observations to the API. The worker has no balance, wager or
settlement authority; transcripts and frames are untrusted data.
"""

__version__ = "0.1.0"
