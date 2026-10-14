import asyncio, json
from pathlib import Path

class MediaError(RuntimeError): pass

async def run_ffmpeg(*args: str):
    proc=await asyncio.create_subprocess_exec("ffmpeg","-hide_banner","-loglevel","error","-y",*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    _,err=await proc.communicate()
    if proc.returncode: raise MediaError(err.decode("utf-8",errors="replace").strip() or "FFmpeg failed")

async def probe(path: Path)->dict:
    proc=await asyncio.create_subprocess_exec("ffprobe","-v","error","-print_format","json","-show_format","-show_streams",str(path),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    out,err=await proc.communicate()
    if proc.returncode: raise MediaError(err.decode("utf-8",errors="replace").strip() or "ffprobe failed")
    return json.loads(out.decode())

def duration_seconds(info:dict)->float:
    try:return float(info.get("format",{}).get("duration",0))
    except:return 0.0

async def make_video_note(src:Path,dst:Path):
    await run_ffmpeg("-i",str(src),"-t","60","-vf","scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,setsar=1","-an","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-movflags","+faststart",str(dst))

async def make_image_video_note(src:Path,dst:Path):
    await run_ffmpeg("-loop","1","-i",str(src),"-t","2","-vf","scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,setsar=1","-an","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-movflags","+faststart",str(dst))

async def make_voice(src:Path,dst:Path):
    await run_ffmpeg("-i",str(src),"-vn","-map_metadata","-1","-c:a","libopus","-b:a","128k","-vbr","on","-compression_level","10",str(dst))
