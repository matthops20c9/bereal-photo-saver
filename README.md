# bereal-photo-saver

I wanted a local backup of all my BeReal photos without relying on their app. This is a quick CLI tool that logs into your account via phone number, fetches your memory history, downloads both the primary and secondary images, and stitches them together (with the selfie in the corner) so they look exactly like they do in the app.

Only tested on Windows, but uses standard paths and should work anywhere Python does.

## Installation

1. Clone this repo.
2. Install dependencies:

```cmd
pip install -r requirements.txt
```

## How to run

First, authenticate with your phone number (including country code, e.g., `+1234567890`):

```cmd
python bereal_saver.py login
```

You'll get an SMS with a code. Type that in to save your session token locally (`~/.bereal-session.json`).

To download and stitch your memories to a local directory:

```cmd
python bereal_saver.py sync --output "D:\BeRealArchive"
```

This will download missing pictures, skip already downloaded ones, and generate a stitched image (e.g., `2024-03-15_stitched.jpg`) along with the raw source files.
