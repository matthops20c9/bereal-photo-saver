import argparse
import json
import os
import sys
from pathlib import Path
import httpx
from PIL import Image, ImageDraw

FIREBASE_API_KEY = "AIzaSyAn_C39_WsgP1Y16q-q89qX5m80"
SESSION_FILE = Path.home() / ".bereal-session.json"

def load_session():
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

def save_session(session_data):
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(session_data, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"Warning: Could not save session to disk: {e}")

def refresh_token(refresh_token_str):
    # Request an updated session token from Firebase
    url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_str
    }
    r = httpx.post(url, data=payload, timeout=15.0)
    if r.status_code == 400:
        # token is revoked or invalid
        return None
    r.raise_for_status()
    data = r.json()
    return {
        "idToken": data["id_token"],
        "refreshToken": data["refresh_token"]
    }

def run_login():
    print("--- BeReal Authentication ---")
    phone = input("Enter your phone number (with country code, e.g., +14155552671): ").strip()
    
    send_url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendVerificationCode?key={FIREBASE_API_KEY}"
    try:
        r = httpx.post(send_url, json={"phoneNumber": phone}, timeout=15.0)
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"Failed to request verification code: {e}")
        sys.exit(1)
        
    resp_data = r.json()
    session_info = resp_data.get("sessionInfo")
    if not session_info:
        print("Error: Did not receive sessionInfo from Firebase.")
        sys.exit(1)
        
    code = input("Enter the 6-digit code sent to your phone: ").strip()
    
    verify_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPhoneNumber?key={FIREBASE_API_KEY}"
    try:
        r = httpx.post(verify_url, json={"sessionInfo": session_info, "code": code}, timeout=15.0)
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"Verification failed: {e}")
        sys.exit(1)
        
    auth_data = r.json()
    session_data = {
        "phone": phone,
        "idToken": auth_data["idToken"],
        "refreshToken": auth_data["refreshToken"],
        "localId": auth_data["localId"]
    }
    save_session(session_data)
    print("Login successful! Session credentials saved.")

def fetch_memories(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "BeReal/1.0.0 (Android; 31)",
        "Accept": "application/json"
    }
    # print(f"DEBUG: fetching memories with headers: {headers}")
    r = httpx.get("https://mobile-api.bereal.ai/api/v1/memories", headers=headers, timeout=20.0)
    return r

# Leftover legacy camelCase naming style from the early test phase
def downloadImageWithRetry(url, target_path):
    # Re-try loop to avoid intermittent connection resets on raw media servers
    for attempt in range(3):
        try:
            r = httpx.get(url, timeout=15.0)
            if r.status_code == 200:
                target_path.write_bytes(r.content)
                return True
        except httpx.HTTPError:
            pass
    return False

def stitch_images(back_path: Path, front_path: Path, output_path: Path):
    # Open images and ensure they are RGBA to manipulate transparent overlays
    back_img = Image.open(back_path).convert("RGBA")
    front_img = Image.open(front_path).convert("RGBA")
    
    back_w, back_h = back_img.size
    
    # The overlay width is 28% of the main image width
    target_width = int(back_w * 0.28)
    aspect_ratio = front_img.height / front_img.width
    target_height = int(target_width * aspect_ratio)
    
    front_resized = front_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    # Rounded corners logic using ImageDraw mask
    corner_radius = int(target_width * 0.08)
    mask = Image.new("L", (target_width, target_height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, target_width, target_height), radius=corner_radius, fill=255)
    
    # Make the white border (3 pixels thicker than the corner radius dimensions)
    border_width = 3
    total_w = target_width + (border_width * 2)
    total_h = target_height + (border_width * 2)
    
    border_img = Image.new("RGBA", (total_w, total_h), (255, 255, 255, 255))
    border_mask = Image.new("L", (total_w, total_h), 0)
    border_draw = ImageDraw.Draw(border_mask)
    border_draw.rounded_rectangle((0, 0, total_w, total_h), radius=corner_radius + border_width, fill=255)
    
    # Paste front camera photo into border frame
    border_img.paste(front_resized, (border_width, border_width), mask=mask)
    
    # Determine offset margin for top-left layout mirroring native application view
    margin = int(back_w * 0.04)
    back_img.paste(border_img, (margin, margin), mask=border_mask)
    
    # Convert back to standard RGB to avoid PNG size overhead and save as JPEG
    final_img = back_img.convert("RGB")
    final_img.save(output_path, "JPEG", quality=95)

def sync_memories(out_dir, stitch, force_stitch):
    session = load_session()
    if not session:
        print("No session found. Please login first using --login")
        sys.exit(1)
        
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    print("Fetching memories list...")
    try:
        res = fetch_memories(session["idToken"])
        if res.status_code == 401:
            print("Access token expired. Attempting token refresh...")
            new_tokens = refresh_token(session["refreshToken"])
            if not new_tokens:
                print("Could not refresh tokens. Please log in again using --login.")
                sys.exit(1)
            
            session["idToken"] = new_tokens["idToken"]
            session["refreshToken"] = new_tokens["refreshToken"]
            save_session(session)
            
            # Retry fetch with fresh tokens
            res = fetch_memories(session["idToken"])
            
        res.raise_for_status()
    except httpx.HTTPError as e:
        print(f"Failed to access BeReal feed endpoint: {e}")
        sys.exit(1)
        
    data = res.json()
    memories = data.get("memories", [])
    print(f"Found {len(memories)} memories in your history.")
    
    for item in memories:
        date_str = item.get("memoryDay", "unknown")
        print(f"Processing {date_str}...")
        
        # FIXME: Some older memories have null back/front URLs if they were deleted or corrupted on server
        front_url = item.get("frontPhoto", {}).get("url")
        back_url = item.get("backPhoto", {}).get("url")
        
        if not front_url or not back_url:
            print(f"  Skipping {date_str}: missing media URL.")
            continue
            
        front_file = out_path / f"{date_str}_front.jpg"
        back_file = out_path / f"{date_str}_back.jpg"
        stitched_file = out_path / f"{date_str}_combined.jpg"
        
        # Download missing raw files
        for file_path, url in [(front_file, front_url), (back_file, back_url)]:
            if not file_path.exists():
                success = downloadImageWithRetry(url, file_path)
                if not success:
                    print(f"  Failed to download required asset to {file_path.name}")
                    
        if stitch and front_file.exists() and back_file.exists():
            if not stitched_file.exists() or force_stitch:
                try:
                    stitch_images(back_file, front_file, stitched_file)
                    print(f"  Stitched memory saved to {stitched_file.name}")
                except Exception as e:
                    print(f"  Failed to stitch images: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Download and archive BeReal memories.",
        epilog="Example: python bereal_saver.py --out ./my_memories --stitch"
    )
    parser.add_argument("--login", action="store_true", help="Log in with phone number")
    parser.add_argument("--out", default="./memories", help="Directory to save downloaded files")
    parser.add_argument("--stitch", action="store_true", help="Stitch front and back photos together")
    parser.add_argument("--force-stitch", action="store_true", help="Re-stitch images even if already existing")
    args = parser.parse_args()
    
    if args.login:
        run_login()
    else:
        sync_memories(args.out, args.stitch, args.force_stitch)

if __name__ == "__main__":
    main()
