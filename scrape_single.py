import os
import json
import requests
import re
from urllib.parse import unquote
from playwright.sync_api import sync_playwright

AUDIO_DIR = os.path.join("static", "native_audio")
SESSION_FILE = "bunpro_session.json"
os.makedirs(AUDIO_DIR, exist_ok=True)


def get_library_state():
    """Finds the highest existing prefix number and tracks already-downloaded files."""
    max_num = 0
    existing_base_names = set()

    if os.path.exists(AUDIO_DIR):
        for fname in os.listdir(AUDIO_DIR):
            match = re.match(r"^(\d+)\.\s*(.+)$", fname)
            if match:
                max_num = max(max_num, int(match.group(1)))
                existing_base_names.add(match.group(2))
            elif fname.endswith(".mp3"):
                existing_base_names.add(fname)

    db_path = os.path.join("static", "sentences.json")
    existing_db = []
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            existing_db = json.load(f)
        for item in existing_db:
            item_id = item.get("id", "")
            match = re.match(r"^(\d+)\.\s*(.+)$", item_id)
            if match:
                max_num = max(max_num, int(match.group(1)))
                existing_base_names.add(match.group(2))
            elif item_id:
                existing_base_names.add(item_id)

    return max_num, existing_base_names, existing_db


def download_male_audio(url, filename):
    # Fallback to force the URL to point to the male audio directory
    if "female_audio" in url:
        url = url.replace("female_audio", "male_audio")
    elif "female" in url:
        url = url.replace("female", "male")

    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return True
    return False


def login_and_save_session():
    """Opens a browser for the user to log in manually, then saves the session state."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("\n" + "=" * 50)
        print("FIRST TIME SETUP: LOGIN REQUIRED")
        print("1. A browser window will open to the Bunpro login page.")
        print("2. Please log in with your email and password.")
        print("3. Once you see your dashboard, return to this terminal and press ENTER.")
        print("=" * 50 + "\n")

        page.goto("https://bunpro.jp/login")
        input("Press ENTER here after you have successfully logged in...")

        context.storage_state(path=SESSION_FILE)
        browser.close()
        print("Session saved successfully! You won't need to log in next time.\n")


def scrape_bunpro_page(url):
    current_num, existing_base_names, existing_db = get_library_state()
    new_entries = []

    print(f"Highest existing audio number: {current_num:04d} (next will be {current_num + 1:04d})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()

        network_audio_urls = []
        page.on("request",
                lambda req: network_audio_urls.append(req.url) if ".mp3" in req.url or ".m4a" in req.url else None)

        page.add_init_script("""
            window.capturedAudio = [];
            const originalPlay = HTMLAudioElement.prototype.play;
            HTMLAudioElement.prototype.play = function() {
                if (this.src) { window.capturedAudio.push(this.src); }
                return originalPlay.apply(this, arguments);
            };
        """)

        print(f"\nLoading page: {url}")
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        print("Switching to the Examples (例文) tab...")
        try:
            examples_tab = page.locator('button[aria-controls="例文"], button[aria-controls="Examples"]').first
            if examples_tab.is_visible():
                examples_tab.click(force=True)
                page.wait_for_timeout(1000)
        except Exception:
            pass

        examples_list = page.locator('header#examples ~ ul').first
        examples = examples_list.locator('li[id^="study-question-"]').all()

        print(f"Found {len(examples)} sentences in the Examples section. Scraping ALL of them...\n")

        for i, example in enumerate(examples):
            try:
                jp_element = example.locator('p[data-force-furigana]')
                if jp_element.count() == 0:
                    continue

                # Clone the node and remove <rt>/<rp> furigana tags before extracting text
                jp_text = jp_element.first.evaluate("""
                    el => {
                        const clone = el.cloneNode(true);
                        clone.querySelectorAll('rt, rp').forEach(node => node.remove());
                        return clone.innerText;
                    }
                """).replace('\n', '').strip()

                clean_text = re.sub(r'[\\/*?:"<>|。、！？!?\s]', '', jp_text)
                if not clean_text:
                    grammar_name = unquote(url.split('/')[-1])
                    clean_text = f"{grammar_name}_{i}"

                base_name = f"{clean_text}.mp3"
                if base_name in existing_base_names:
                    print(f"[{i + 1}/{len(examples)}] Skipped (Already downloaded): {base_name}")
                    continue

                play_btn = example.locator('button[title="再生"], button[title="Play"]').first
                audio_url = None

                if play_btn.count() > 0:
                    page.evaluate("window.capturedAudio = []")
                    network_audio_urls.clear()

                    play_btn.scroll_into_view_if_needed()
                    play_btn.click(force=True)

                    page.wait_for_timeout(1500)

                    captured = page.evaluate("window.capturedAudio")
                    if captured:
                        audio_url = captured[-1]

                    if not audio_url:
                        clean_jp = jp_text.replace("。", "").replace("、", "")
                        for req_url in reversed(network_audio_urls):
                            if clean_jp in unquote(req_url):
                                audio_url = req_url
                                break

                    if not audio_url and network_audio_urls:
                        audio_url = network_audio_urls[-1]

                if audio_url:
                    next_num = current_num + 1
                    safe_name = f"{next_num:04d}. {base_name}"
                    local_filepath = os.path.join(AUDIO_DIR, safe_name)

                    print(f"[{i + 1}/{len(examples)}] Saving Audio: {safe_name}")
                    success = download_male_audio(audio_url, local_filepath)

                    if success:
                        current_num = next_num
                        existing_base_names.add(base_name)
                        new_entries.append({
                            "id": safe_name,
                            "text": jp_text,
                            "audio_file": f"native_audio/{safe_name}"
                        })
                    else:
                        print(f"[{i + 1}/{len(examples)}] Failed to download audio from URL.")
                else:
                    print(f"[{i + 1}/{len(examples)}] Skipped (No audio found): {jp_text}")

            except Exception as e:
                print(f"Error on example {i + 1}: {e}")

        browser.close()

    db_path = os.path.join("static", "sentences.json")
    total_db = existing_db + new_entries
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(total_db, f, ensure_ascii=False, indent=4)

    print(f"\nDone! Added {len(new_entries)} new files (total: {len(total_db)}).")


if __name__ == "__main__":
    print("-" * 50)

    if not os.path.exists(SESSION_FILE):
        login_and_save_session()

    target_url = input("Paste the Bunpro grammar point URL to scrape:\n> ").strip()
    if target_url:
        scrape_bunpro_page(target_url)