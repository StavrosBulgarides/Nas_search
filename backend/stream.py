from __future__ import annotations

import logging
import os
import signal
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _probe_video_codec(file_path: str) -> Optional[str]:
    """Use ffprobe to detect the video codec."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                file_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        logger.exception("ffprobe failed for %s", file_path)
        return None


def _build_ffmpeg_cmd(file_path: str, video_codec: Optional[str]) -> list:
    """Build the ffmpeg command for streaming as fragmented MP4."""
    # If the video is already H.264, just remux (fast, no transcoding)
    if video_codec == "h264":
        video_args = ["-c:v", "copy"]
        logger.info("Stream: remuxing %s (h264 copy)", file_path)
    else:
        # Transcode to H.264
        video_args = [
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
        ]
        logger.info("Stream: transcoding %s (codec=%s -> h264)", file_path, video_codec)

    return [
        "ffmpeg",
        "-i", file_path,
        *video_args,
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "frag_keyframe+empty_moov+faststart",
        "-f", "mp4",
        "-v", "error",
        "pipe:1",
    ]


@router.get("/api/stream")
async def stream_video(path: str = Query(..., description="Container file path")):
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")

    # Basic path traversal protection
    real = os.path.realpath(path)
    if not real.startswith("/mnt/nas"):
        raise HTTPException(status_code=403, detail="Access denied")

    video_codec = _probe_video_codec(path)
    cmd = _build_ffmpeg_cmd(path, video_codec)

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    def generate():
        try:
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            process.stdout.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    filename = Path(path).stem + ".mp4"
    return StreamingResponse(
        generate(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )
