<img src="./_app/icons/README.png">
<h1 align="center">ShrinkComfy</h1>
<h3 align="center">CONVERT & SHRINK your ComfyUI PNG images to WEBP or JPG WITHOUT LOSING THE WORKFLOW</h3>
<p align=center>ComfyUI saves images as PNG with the workflow embedded inside. And these files are huge...  
This app shrinks them dramatically while keeping the workflow INTACT, so you can still drag & drop them back into ComfyUI exactly as before.
<br><br><b>Typical savings = 70–90% smaller</b> than the original PNG<b></p>
<br><br><br>



## Why another converter AGAIN ?

Every image ComfyUI generates carries its full workflow in the .PNG metadata, that's what makes drag & drop work.

BUT : Most converters strip that metadata. **ShrinkComfy doesn't.**  
It re-embeds the workflow and prompt into the converted file using the EXIF format that ComfyUI understands, so nothing is lost.



## Features

- Convert to **WEBP** (recommended) or **JPG**
- Quality slider from 25% to 100%
- Batch convert entire folders, including subfolders
- Side-by-side or slider **preview** before converting
- Sort output by **date** (by month or by day)
- Preserve **original subfolder structure**
- Optional: copy non-PNG files alongside converted output
- Optional: if you want it can do the opposite and **strip workflow data from output**
- Can do parallel workers for faster batch conversion



## Requirements

- Windows 10 or 11 (will do linux in the future)
- [Python 3.9+](https://www.python.org/downloads/) ⚠️ check **"Add Python to PATH"** during install



## Installation

```
1. Download or clone this repo
2. Double-click ShrinkComfy.bat
```

On first launch, dependencies install automatically into a local folder (`_app\.venv\`).  
Nothing is written outside the project directory. Takes ~20 seconds the first time.



## Recommended settings

| Goal | Setting |
|---|---|
| Best quality / smallest size | WEBP q90 |
| Maximum compression | WEBP q80 |
| Broad compatibility | JPG q90 |

> **Important:** Do not use WEBP Lossless because ComfyUI cannot read workflows from lossless WEBP files.  
> Any quality setting below 100 works fine with drag & drop.



## Uninstall

Delete the folder. Nothing is written anywhere else on your system 😊
